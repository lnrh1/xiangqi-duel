"""对局编排：棋手、人类输入、事件流、留言与日志。"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass

from .agent import AgentDecision, EnginePlayer, LLMPlayer
from .game import Game, IllegalMove
from .simulation import Simulation
from .llm import LLMError, PRESETS, ProviderConfig, make_client
from .moves import other
from .pieces import BLACK, COLOR_ZH, RED

TRACE_TYPES = ("thinking", "tool_call", "llm_step", "error")


@dataclass
class PlayerSpec:
    """一名棋手的配置（kind: llm / engine / human）。"""

    kind: str = "engine"
    provider: str = "engine"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.6
    depth: int = 3
    time_limit: float = 5.0
    label: str = ""

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        provider = str(data.get("provider") or "engine").strip()
        kind = data.get("kind") or ("human" if data.get("human") else "engine")
        if kind not in ("llm", "engine", "human"):
            kind = "engine" if provider == "engine" else "llm"
        if provider == "engine":
            kind = "engine" if kind != "human" else "human"
        if kind == "llm" and provider not in PRESETS and not data.get("base_url"):
            raise ValueError(
                "未知提供商 %r，可选：%s（也可以自定义 base_url）"
                % (provider, "、".join(sorted(PRESETS)))
            )
        try:
            temperature = float(data.get("temperature", 0.6))
        except (TypeError, ValueError):
            temperature = 0.6
        try:
            depth = int(data.get("depth", 3))
        except (TypeError, ValueError):
            depth = 3
        try:
            time_limit = float(data.get("time_limit", 5.0))
        except (TypeError, ValueError):
            time_limit = 5.0
        return cls(
            kind=kind,
            provider=provider,
            model=str(data.get("model") or ""),
            api_key=str(data.get("api_key") or ""),
            base_url=str(data.get("base_url") or ""),
            temperature=temperature,
            depth=depth,
            time_limit=time_limit,
            label=str(data.get("label") or ""),
        )

    def to_public(self):
        if self.kind == "engine":
            label = self.label or "本地引擎"
            return {"kind": "engine", "provider": "engine", "model": "alpha-beta", "label": label, "depth": self.depth}
        if self.kind == "human":
            return {"kind": "human", "provider": "human", "model": "", "label": self.label or "人类"}
        preset = PRESETS.get(self.provider, {})
        return {
            "kind": "llm",
            "provider": self.provider,
            "model": self.model or preset.get("model", ""),
            "label": self.label or "%s · %s" % (self.provider, self.model or preset.get("model", "")),
            "temperature": self.temperature,
            "has_api_key": bool(self.api_key),
        }

    def make_player(self, side, emit, seed=0, enabled_tools=None):
        if self.kind == "engine":
            return EnginePlayer(
                side,
                depth=self.depth,
                time_limit=self.time_limit,
                seed=seed,
                emit=emit,
                label=self.label,
            )
        if self.kind == "human":
            raise ValueError("human players are driven by the Match")
        preset = PRESETS.get(self.provider, {})
        config = ProviderConfig(
            provider=self.provider,
            model=self.model or preset.get("model", ""),
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=self.temperature,
        ).resolved()
        if not config.api_key and preset.get("kind") != "engine":
            raise ValueError(
                "提供商 %s 缺少 API Key：请在界面上填写，或设置环境变量 %s"
                % (self.provider, " / ".join(preset.get("env", ())) or "（该提供商无需 Key）")
            )
        client = make_client(config)
        return LLMPlayer(
            side, client, config, emit=emit, seed=seed, enabled_tools=enabled_tools
        )


class Match:
    """一场对局：在后台线程里推进，向订阅者广播状态。"""

    def __init__(
        self,
        red_spec,
        black_spec,
        human_side=None,
        max_plies=300,
        fen=None,
        seed=1,
        game_id=None,
        players=None,
        enabled_tools=None,
        free=False,
    ):
        self.id = game_id or uuid.uuid4().hex[:10]
        self.red_spec = red_spec
        self.black_spec = black_spec
        self.human_side = human_side
        self.free = bool(free)
        self.mode = "free" if self.free else ("human" if human_side else "aivai")
        self.enabled_tools = list(enabled_tools) if enabled_tools else None
        self.pending_draw = None
        self.draw_proposer = None
        self.draw_by_user = False
        self.human_sim = None
        self.max_plies = max_plies
        self.game = Game(fen=fen, max_plies=max_plies)
        self.seed = seed
        self.lock = threading.RLock()
        self.subscribers = []
        self.trace = []
        self.chat = []
        self.thinking = None
        self.thread = None
        self.stop_event = threading.Event()
        self.human_queue = queue.Queue()
        self.started_at = time.time()
        self.finished_at = None
        self.errors = []
        self.usage = {
            RED: {"input": 0, "output": 0, "total": 0, "cached": 0, "context": 0},
            BLACK: {"input": 0, "output": 0, "total": 0, "cached": 0, "context": 0},
        }
        self.players = {}
        specs = {RED: red_spec, BLACK: black_spec}
        for color in (RED, BLACK) if not self.free else ():
            if color == human_side:
                continue
            if players and color in players:
                self.players[color] = players[color]
            else:
                self.players[color] = specs[color].make_player(
                    color,
                    self._agent_event,
                    seed=seed + (1 if color == BLACK else 0),
                    enabled_tools=self.enabled_tools,
                )

    # ------------------------------------------------------------- event bus
    def subscribe(self):
        channel = queue.Queue(maxsize=256)
        with self.lock:
            self.subscribers.append(channel)
        return channel

    def unsubscribe(self, channel):
        with self.lock:
            if channel in self.subscribers:
                self.subscribers.remove(channel)

    def _broadcast(self, event):
        with self.lock:
            for channel in list(self.subscribers):
                try:
                    channel.put_nowait(event)
                except queue.Full:
                    pass

    def _agent_event(self, event):
        event = dict(event)
        event.setdefault("at", time.time())
        if event.get("type") == "thinking_delta":
            if self.mode == "aivai":
                self._broadcast(event)
            return
        if event.get("type") == "sim":
            if self.mode == "aivai" or event.get("side") == self.human_side:
                self._broadcast(
                    {
                        "type": "sim",
                        "side": event.get("side"),
                        "snapshot": event.get("snapshot"),
                    }
                )
            return
        if event.get("type") in TRACE_TYPES:
            entry = self._record_trace(event)
            if self.mode == "aivai":
                self._broadcast({"type": "trace", "entry": entry})
            return
        self._broadcast(event)

    def _record_trace(self, event):
        kind = event.get("type")
        with self.lock:
            ply = len(self.game.history) + 1
        entry = {
            "id": len(self.trace) + 1,
            "side": event.get("side"),
            "kind": kind,
            "ply": ply,
            "at": event.get("at", time.time()),
        }
        if kind == "thinking":
            entry["text"] = (event.get("text") or "")[:1200]
            entry["variant"] = event.get("variant", "plan")
        elif kind == "tool_call":
            entry["name"] = event.get("name")
            entry["arguments"] = event.get("arguments")
            entry["ok"] = event.get("ok", True)
            entry["result"] = (event.get("result") or "")[:900]
        elif kind == "llm_step":
            entry["step"] = event.get("step")
        else:
            entry["text"] = (event.get("text") or "")[:900]
        with self.lock:
            self.trace.append(entry)
            if len(self.trace) > 600:
                del self.trace[:200]
        return entry

    # ---------------------------------------------------------------- control
    def start(self, block=False):
        if self.free:
            self._broadcast({"type": "state", "snapshot": self.snapshot()})
            return
        self.thread = threading.Thread(
            target=self._run, name="xiangqi-match-%s" % self.id, daemon=True
        )
        self.thread.start()
        if block:
            self.thread.join()

    def stop(self, reason="对局被终止"):
        self.stop_event.set()
        self.human_queue.put(None)
        for player in list(self.players.values()):
            cancel = getattr(player, "cancel", None)
            if cancel is not None:
                try:
                    cancel()
                except Exception:  # noqa: BLE001
                    pass
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2)
        with self.lock:
            if self.game.status == "playing":
                self.game.abort(reason)
        self._broadcast({"type": "state", "snapshot": self.snapshot()})

    def is_running(self):
        return self.thread is not None and self.thread.is_alive()

    # ------------------------------------------------------------------ loop
    def _run(self):
        try:
            self._broadcast({"type": "state", "snapshot": self.snapshot()})
            while True:
                with self.lock:
                    if self.game.status != "playing":
                        break
                    if len(self.game.history) >= self.max_plies:
                        self.game.declare_draw("达到最大手数，判和")
                        break
                    side = self.game.turn
                    self.thinking = side
                self._broadcast({"type": "state", "snapshot": self.snapshot()})

                if self.stop_event.is_set():
                    break

                player = self.players.get(side)
                if player is None:
                    item = self._wait_human()
                    if item is None:
                        break
                    try:
                        with self.lock:
                            self.game.play(item[0], item[1])
                            had_sim = self.human_sim is not None
                            self.human_sim = None
                        if had_sim:
                            self._broadcast(
                                {"type": "sim", "side": self.human_side, "snapshot": None}
                            )
                    except IllegalMove as exc:
                        self._error(str(exc))
                        self.game.resign(side, "非法着法")
                        break
                else:
                    with self.lock:
                        view = self.game.clone()
                    try:
                        decision = player.choose(view)
                    except Exception as exc:  # noqa: BLE001 - keep the match alive
                        if self.stop_event.is_set():
                            break
                        self._error("AI 异常：%s" % exc)
                        self.game.resign(side, "AI 异常")
                        break
                    self._deliver_messages(side, decision.messages)
                    with self.lock:
                        for key in ("input", "output", "total", "cached"):
                            self.usage[side][key] += decision.usage.get(key, 0)
                        self.usage[side]["context"] = decision.context_tokens or decision.usage.get("input", 0)
                    if self.stop_event.is_set():
                        break
                    with self.lock:
                        if self.game.status != "playing":
                            break
                    if decision.draw_offer is not None:
                        note = decision.draw_offer
                        with self.lock:
                            self.chat.append(
                                {
                                    "side": side,
                                    "text": "提议和棋" + ("：" + note if note else ""),
                                    "at": time.time(),
                                    "ply": len(self.game.history) + 1,
                                }
                            )
                        opponent = other(side)
                        if opponent in self.players:
                            self.players[opponent].inbox.put(
                                {
                                    "from": "opponent",
                                    "text": "对手提议和棋"
                                    + ("（%s）" % note if note else "")
                                    + "；如果你同意，请调用 offer_draw。",
                                }
                            )
                        if self.pending_draw and self.pending_draw[0] != side:
                            self.game.declare_draw("双方同意和棋")
                            break
                        if self.pending_draw is None:
                            self.draw_proposer = side
                        self.pending_draw = (side, note)
                        self._broadcast({"type": "state", "snapshot": self.snapshot()})

                    if decision.resign:
                        self.game.resign(
                            side,
                            decision.resign_reason or decision.comment or "认输",
                        )
                        break
                    if decision.error:
                        self._error(decision.error)
                    try:
                        with self.lock:
                            self.game.play(
                                decision.piece_id,
                                decision.to,
                                comment=decision.comment,
                                thinking=decision.thinking,
                                usage=decision.usage,
                            )
                    except IllegalMove as exc:
                        self._error("AI 着法无效：%s" % exc)
                        self.game.resign(side, "AI 着法无效")
                        break

                with self.lock:
                    self.thinking = None
                self._broadcast({"type": "state", "snapshot": self.snapshot()})
        finally:
            with self.lock:
                self.thinking = None
                if self.game.status == "playing":
                    self.game.abort("对局中止")
                self.finished_at = time.time()
                snapshot = self.snapshot()
                result = self.game.result
            self._broadcast({"type": "state", "snapshot": snapshot})
            self._broadcast({"type": "end", "result": result, "snapshot": snapshot})
            if result and not self.stop_event.is_set():
                threading.Thread(
                    target=self._post_game, name="postgame-%s" % self.id, daemon=True
                ).start()

    def _post_game(self):
        """赛后对话：胜者或提出和棋的一方先发言，各 3 条后结束。"""
        try:
            with self.lock:
                result = dict(self.game.result or {})
            if not result or self.stop_event.is_set():
                return
            if self.draw_by_user:
                return
            if result.get("code") == "aborted":
                return
            if len(self.players) != 2:
                return
            if not all(hasattr(player, "postgame_speak") for player in self.players.values()):
                return
            winner = result.get("winner")
            starter = winner if winner in self.players else (self.draw_proposer or RED)
            if starter not in self.players:
                starter = RED if RED in self.players else BLACK
            transcript = []
            for index in range(6):
                side = starter if index % 2 == 0 else other(starter)
                player = self.players.get(side)
                if player is None:
                    break
                sent = sum(1 for item in transcript if item["side"] == side)
                remaining = max(0, 3 - sent)
                system = self._post_game_system(side, result, starter, remaining, index)
                user = self._post_game_user(result, transcript)
                text, usage = player.postgame_speak(system, [{"role": "user", "content": user}])
                text = (text or "").strip()[:280]
                if not text:
                    text = "……"
                with self.lock:
                    self.chat.append(
                        {
                            "side": side,
                            "text": text,
                            "at": time.time(),
                            "ply": len(self.game.history) + 1,
                            "postgame": True,
                        }
                    )
                    for key in ("input", "output", "total", "cached"):
                        self.usage[side][key] += int((usage or {}).get(key, 0) or 0)
                transcript.append({"side": side, "text": text})
                self._broadcast({"type": "state", "snapshot": self.snapshot()})
                if self.stop_event.wait(0.8):
                    return

            # 最后再调用发起方一次，只读不回复；下一局前不再有往返。
            starter_player = self.players.get(starter)
            if starter_player is not None:
                system = self._post_game_system(starter, result, starter, 0, 6, read_only=True)
                user = self._post_game_user(result, transcript)
                starter_player.postgame_speak(system, [{"role": "user", "content": user}])
        except Exception as exc:  # noqa: BLE001
            self._error("赛后对话异常：%s" % exc)

    def _post_game_outcome(self, result):
        code = result.get("code") or ""
        reason = {
            "checkmate": "将死", "stalemate": "困毙", "resign": "认输",
            "agreement": "双方同意和棋", "threefold": "三次重复局面",
            "perpetual": "长将", "sixty-move": "60 回合无吃子",
            "insufficient": "子力不足", "aborted": "对局中止",
        }.get(code, result.get("reason") or "")
        winner = result.get("winner")
        if winner:
            return "%s方胜（%s）" % (COLOR_ZH.get(winner, winner), reason or "结束")
        return "和棋" + ("（%s）" % reason if reason else "")

    def _post_game_system(self, side, result, starter, remaining, index, read_only=False):
        color = COLOR_ZH.get(side, side)
        outcome = self._post_game_outcome(result)
        if read_only:
            return (
                "对局已经结束：%s。你执%s方。赛后对话已经结束，现在请你只读上面的对话内容，"
                "不要输出任何回复、评论或新消息；下一局开始前不会再有人给你回信。"
                % (outcome, color)
            )
        if side == starter:
            start_line = "你是本场赛后对话的发起方，由你先说。"
        else:
            start_line = "对方发起了赛后对话，你依次回应。"
        if remaining <= 1:
            last_line = (
                "这是你的最后一条消息。发送后，如果对方还有最后一条，之后在下一局开始前不会再有新的回信；"
                "请把想说的话说完。"
            )
        else:
            last_line = "请珍惜剩余发言次数，不要重复已经说过的内容。"
        template = chr(10).join([
            "对局已经结束：%s。你执%s方。",
            "现在是赛后对话，最多 3 轮，双方各 3 条，共 6 条。",
            "%s",
            "你还可以发送 %d 条消息。",
            "%s",
            "请用中文简短发言，不超过 80 字；可以复盘关键手、表达感想或回应对方。"
            "不要使用工具，不要输出 JSON 或标题。",
        ])
        return template % (outcome, color, start_line, remaining, last_line)

    def _post_game_user(self, result, transcript):
        lines = ["对局结果：%s" % self._post_game_outcome(result)]
        lines.append("总手数：%d" % len(self.game.history))
        recent = self.game.history[-24:]
        if recent:
            lines.append("最近着法：" + " ".join(str(getattr(item, "notation", item)) for item in recent))
        lines.append("此前的赛后对话：")
        if not transcript:
            lines.append("（还没有人发言）")
        for item in transcript:
            lines.append("%s方：%s" % (COLOR_ZH.get(item["side"], item["side"]), item["text"]))
        lines.append("轮到你发言。")
        return chr(10).join(lines)

    def _wait_human(self):
        while not self.stop_event.is_set():
            try:
                return self.human_queue.get(timeout=0.5)
            except queue.Empty:
                continue
        return None

    def _error(self, text):
        with self.lock:
            self.errors.append(text)
            self.errors = self.errors[-5:]
        self._broadcast({"type": "error", "text": text})

    def _deliver_messages(self, side, messages):
        if not messages:
            return
        opponent = other(side)
        for text in messages:
            with self.lock:
                self.chat.append(
                    {
                        "side": side,
                        "text": text,
                        "at": time.time(),
                        "ply": len(self.game.history) + 1,
                    }
                )
            if opponent in self.players:
                self.players[opponent].inbox.put({"from": "opponent", "text": text})
        self._broadcast({"type": "state", "snapshot": self.snapshot()})

    # ------------------------------------------------------------- human side
    def resign(self, side, reason="认输"):
        """Resign on behalf of a side (human player or agent)."""
        with self.lock:
            if self.game.status != "playing":
                return
            self.game.resign(side, reason)
            snapshot = self.snapshot()
        self._broadcast({"type": "state", "snapshot": snapshot})

    def request_draw(self, side):
        with self.lock:
            if self.game.status != "playing":
                return
            if self.mode != "human" or side != self.human_side:
                raise ValueError("只有人类一方可以求和")
            self.draw_by_user = True
            self.draw_proposer = side
            self.game.declare_draw("人类求和")
            snapshot = self.snapshot()
        self._broadcast({"type": "state", "snapshot": snapshot})

    def free_move(self, piece_id, to):
        with self.lock:
            if self.game.status != "playing":
                raise IllegalMove("对局已经结束")
            piece = self.game.piece(piece_id)
            if piece is None:
                raise IllegalMove("没有棋子 %s" % (piece_id,))
            saved_turn = self.game.turn
            self.game.turn = piece.color
            try:
                record = self.game.play(piece_id, to, adjudicate=True)
            except Exception:
                self.game.turn = saved_turn
                raise
        self._broadcast({"type": "state", "snapshot": self.snapshot()})
        return record

    def submit_human_move(self, piece_id, to):
        if self.human_side is None:
            raise IllegalMove("这场对局没有人类棋手")
        with self.lock:
            if self.game.status != "playing":
                raise IllegalMove("对局已经结束")
            if self.game.turn != self.human_side:
                raise IllegalMove("还没轮到你走棋")
            move = self.game.find_move(piece_id, to)
            if move is None:
                raise IllegalMove(self.game.illegal_reason(piece_id, to))
        self.human_queue.put((piece_id, to))
        return True

    def say(self, text):
        text = str(text or "").strip()[:200]
        if not text:
            return
        label = "观众" if self.mode == "aivai" else "对手"
        with self.lock:
            self.chat.append(
                {
                    "side": "user",
                    "text": text,
                    "at": time.time(),
                    "ply": len(self.game.history) + 1,
                }
            )
            for player in self.players.values():
                player.inbox.put({"from": "human", "label": label, "text": text})
        self._broadcast({"type": "state", "snapshot": self.snapshot()})

    def _sims_locked(self):
        sims = {}
        if self.mode == "aivai":
            for color in (RED, BLACK):
                sim = getattr(self.players.get(color), "sim", None)
                if sim is not None:
                    sims[color] = sim.snapshot()
        elif self.human_sim is not None:
            sims[self.human_side] = self.human_sim.snapshot()
        return sims

    def start_human_sim(self):
        if self.mode != "human":
            raise ValueError("只有人机模式可以使用推演棋盘")
        if self.enabled_tools is not None and "start_simulation" not in self.enabled_tools:
            raise ValueError("推演棋盘工具未启用")
        if self.game.status != "playing":
            raise ValueError("对局已结束")
        if self.human_sim is None:
            self.human_sim = Simulation(self.game)
        snapshot = self.human_sim.snapshot()
        self._broadcast({"type": "sim", "side": self.human_side, "snapshot": snapshot})
        return snapshot

    def human_sim_move(self, piece_id, to):
        if self.mode != "human" or self.human_sim is None:
            raise ValueError("当前没有推演棋盘")
        record, ended = self.human_sim.move(piece_id, to)
        snapshot = self.human_sim.snapshot()
        if ended:
            self.human_sim = None
        self._broadcast(
            {
                "type": "sim",
                "side": self.human_side,
                "snapshot": snapshot,
                "ended": ended,
            }
        )
        if ended:
            self._broadcast({"type": "state", "snapshot": self.snapshot()})
        return {
            "ok": True,
            "snapshot": snapshot,
            "ended": ended,
            "plies": snapshot["plies"],
            "limit": snapshot["limit"],
            "notation": record.notation,
        }

    def end_human_sim(self):
        self.human_sim = None
        self._broadcast({"type": "sim", "side": self.human_side, "snapshot": None})
        self._broadcast({"type": "state", "snapshot": self.snapshot()})

    # -------------------------------------------------------------- snapshots
    def snapshot(self):
        with self.lock:
            snap = self.game.snapshot()
            if self.free:
                legal = {}
                saved_turn = self.game.turn
                try:
                    for piece in list(self.game.board.pieces.values()):
                        self.game.turn = piece.color
                        targets = self.game.legal_moves(piece.id)
                        if targets:
                            legal[piece.id] = [move.to_str for move in targets]
                finally:
                    self.game.turn = saved_turn
                snap["legal"] = legal
            snap.update(
                {
                    "match_id": self.id,
                    "mode": self.mode,
                    "human_side": self.human_side,
                    "thinking": self.thinking,
                    "players": {
                        RED: self.red_spec.to_public(),
                        BLACK: self.black_spec.to_public(),
                    },
                    "chat": self.chat[-60:],
                    "trace": self.trace[-120:] if self.mode == "aivai" else [],
                    "trace_hidden": self.mode == "human",
                    "usage": self.usage,
                    "tools": self.enabled_tools,
                    "errors": self.errors[-5:],
                    "sims": self._sims_locked(),
                    "started_at": self.started_at,
                }
            )
            return snap

    def log(self):
        with self.lock:
            return {
                "schema": "xiangqi-duel/match@1",
                "id": self.id,
                "mode": self.mode,
                "human_side": self.human_side,
                "start_fen": self.game.start_fen,
                "players": {
                    RED: self.red_spec.to_public(),
                    BLACK: self.black_spec.to_public(),
                },
                "moves": [m.to_dict() for m in self.game.history],
                "chat": self.chat,
                "trace": self.trace,
                "result": self.game.result,
                "usage": self.usage,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }
