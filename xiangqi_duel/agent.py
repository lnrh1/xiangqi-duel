"""棋手实现：LLM 代理（独立上下文 + 工具调用）与本地引擎代理。"""
from __future__ import annotations

import json
import queue
import random
import time
from dataclasses import dataclass, field

from .engine import choose_move
from .llm import LLMError
from .moves import other
from .pieces import BLACK, COLOR_ZH, RED
from .tools import ToolBox, tool_specs

MAX_STEPS = 8
MAX_BLOCKS = 8  # 每个 AI 独立保留的回合块数量


SYSTEM_PROMPT = """你是一名中国象棋高手，正在参加一场正式对弈。你执{color}方。
请始终用中文思考和发言，棋谱使用中文记谱法（如“炮二平五”）。

# 棋盘与编号
- 棋盘 9 列 10 行：列用 a-i 表示，行用 0-9 表示。
- 红方在下方（y=0 是红方底线），黑方在上方（y=9 是黑方底线），中间是楚河汉界。
- 红兵向 y 增大的方向前进，黑卒向 y 减小的方向前进。
- 每枚棋子都有稳定编号，走子后不变：
  red_chariot_1/2、red_horse_1/2、red_elephant_1/2、red_advisor_1/2、
  red_general、red_cannon_1/2、red_soldier_1..5；黑方为 black_ 前缀同构。

# 规则要点
- 车走直线；马走日、蹩马腿；炮走直线、吃子必须隔一个棋子；象走田、不过河；
  士和将只能在九宫内活动；将帅不能照面。
- 兵卒过河前只能向前，过河后可以左右。
- 将死对方或让对方无子可走（困毙）即获胜；长将判负；三次重复局面判和；
  60 回合无吃子判和。

# 你的工具
get_board、list_pieces、list_pieces_in_area、get_piece、describe_square、
list_legal_moves、move、get_status、get_history、send_message、resign。
查坐标用 get_piece(棋子编号) 或 describe_square(格子)；
按范围找子用 list_pieces_in_area(x_min, x_max, y_min, y_max)。

# 对局要求
1. 轮到你时，先用工具了解局面，然后必须调用且只调用一次 move(piece_id, to)。
2. 不要用文字描述代替 move 工具调用；不要走对方的棋子。
3. 想对对手说话就调用 send_message（每回合最多一条，80 字以内）。
4. 只有败局已定时才 resign。
5. 思考时用中文简要说明计划（一两句），然后立即调用工具。
"""


@dataclass
class AgentDecision:
    piece_id: str = ""
    to: str = ""
    resign: bool = False
    comment: str = ""
    thinking: str = ""
    messages: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    steps: int = 0
    error: str = ""
    fallback: bool = False


def side_zh(color):
    return COLOR_ZH[color]


class LLMPlayer:
    """一个 LLM 棋手：保留自己的对话上下文，按回合调用工具。"""

    kind = "llm"

    def __init__(
        self,
        side,
        client,
        config,
        emit=None,
        fallback="random",
        seed=0,
        max_steps=MAX_STEPS,
        max_blocks=MAX_BLOCKS,
        label="",
    ):
        self.side = side
        self.client = client
        self.config = config
        self.emit = emit or (lambda event: None)
        self.fallback = fallback
        self.rng = random.Random(seed)
        self.max_steps = max_steps
        self.max_blocks = max_blocks
        self.label = label or "%s / %s" % (config.provider, config.model)
        self.blocks = []
        self.inbox = queue.Queue()
        self.usage_total = {"input": 0, "output": 0, "total": 0}
        self.turns = 0
        self.toolbox = None

    # ------------------------------------------------------------------ turn
    def choose(self, game):
        self.turns += 1
        self.toolbox = ToolBox(game, self.side)
        block = []
        self._drain_inbox(block)
        block.append({"role": "user", "content": self._turn_prompt(game)})
        self.blocks.append(block)
        while len(self.blocks) > self.max_blocks:
            self.blocks.pop(0)
        messages = self._messages()
        last_text = ""
        system = SYSTEM_PROMPT.format(color=side_zh(self.side))

        for step in range(self.max_steps):
            self.emit({"type": "llm_step", "side": self.side, "step": step + 1})
            try:
                result = self.client.chat(system, messages, tools=tool_specs())
            except LLMError as exc:
                self.emit({"type": "error", "side": self.side, "text": str(exc)})
                return self._fallback(game, last_text, error=str(exc))
            self._merge_usage(result.usage)
            if result.reasoning:
                self.emit(
                    {
                        "type": "thinking",
                        "side": self.side,
                        "text": result.reasoning,
                        "variant": "reasoning",
                    }
                )
            if result.text:
                last_text = result.text
                self.emit(
                    {
                        "type": "thinking",
                        "side": self.side,
                        "text": result.text,
                        "variant": "plan",
                    }
                )

            if not result.tool_calls:
                block.append({"role": "assistant", "content": result.text})
                nudge = (
                    "请不要只说话：现在必须调用 move(piece_id, to) 走一步棋。"
                    "需要先查看着法可以调用 list_legal_moves。"
                )
                block.append({"role": "user", "content": nudge})
                messages = self._messages()
                continue

            block.append(
                {
                    "role": "assistant",
                    "content": result.text,
                    "tool_calls": [
                        {"id": call.id, "name": call.name, "arguments": call.arguments}
                        for call in result.tool_calls
                    ],
                }
            )
            for call in result.tool_calls:
                outcome = self.toolbox.call(call.name, call.arguments)
                content = json.dumps(outcome, ensure_ascii=False)
                if len(content) > 4000:
                    content = content[:4000] + "...(truncated)"
                block.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": content,
                    }
                )
                self.emit(
                    {
                        "type": "tool_call",
                        "side": self.side,
                        "name": call.name,
                        "arguments": call.arguments,
                        "ok": bool(outcome.get("ok")),
                        "result": self._summarise(outcome),
                    }
                )
                if call.name == "move" and outcome.get("ok"):
                    piece_id, to = self.toolbox.pending
                    return self._decision(
                        piece_id=piece_id,
                        to=to,
                        comment=last_text,
                        steps=step + 1,
                    )
                if call.name == "resign" and outcome.get("ok"):
                    return self._decision(
                        resign=True, comment=last_text or "认输", steps=step + 1
                    )
            messages = self._messages()

        self.emit(
            {
                "type": "error",
                "side": self.side,
                "text": "AI 在 %d 步内没有给出合法着法" % self.max_steps,
            }
        )
        return self._fallback(game, last_text, error="no move within step limit")

    # -------------------------------------------------------------- helpers
    def _messages(self):
        return [message for block in self.blocks for message in block]

    def _drain_inbox(self, block):
        while True:
            try:
                item = self.inbox.get_nowait()
            except queue.Empty:
                return
            who = "对手" if item.get("from") == "opponent" else "观众"
            block.append(
                {
                    "role": "user",
                    "content": "%s给你留言：「%s」" % (who, item.get("text", "")),
                }
            )

    def _turn_prompt(self, game):
        last = game.history[-1] if game.history else None
        recent = game.history[-6:]
        recent_text = "、".join(
            "第%d手 %s %s" % (m.ply, side_zh(m.side), m.notation) for m in recent
        )
        if last is None:
            last_text = "无（对局开始）"
        else:
            last_text = "第%d手 %s %s（%s→%s）" % (
                last.ply,
                side_zh(last.side),
                last.notation,
                last.from_square,
                last.to_square,
            )
        material = game.material()
        lines = [
            "第 %d 回合（第 %d 手），现在轮到你执%s方走棋。"
            % (game.fullmove, len(game.history) + 1, side_zh(self.side)),
            "你是否被将军：%s" % ("是" if game.in_check() else "否"),
            "上一步：%s" % last_text,
            "最近着法：%s" % (recent_text or "暂无"),
            "子力：红 %d，黑 %d" % (material[RED], material[BLACK]),
            "",
            "当前棋盘（大写=红方，小写=黑方）：",
            game.ascii(),
            "",
            "请先用工具查看局面，用中文简要说明计划，然后调用 move(piece_id, to)。",
        ]
        return "\n".join(lines)

    def _summarise(self, outcome):
        data = dict(outcome)
        data.pop("board", None)
        data.pop("piece_id_help", None)
        text = json.dumps(data, ensure_ascii=False)
        if len(text) > 700:
            text = text[:700] + "…"
        return text

    def _merge_usage(self, usage):
        for key in ("input", "output", "total"):
            self.usage_total[key] = self.usage_total.get(key, 0) + usage.get(key, 0)

    def _decision(self, **kwargs):
        kwargs.setdefault("messages", list(self.toolbox.outbox))
        kwargs.setdefault("usage", dict(self.usage_total))
        return AgentDecision(**kwargs)

    def _fallback(self, game, text, error=""):
        if self.fallback == "forfeit":
            return self._decision(
                resign=True, comment=text, error=error, fallback=True
            )
        moves = game.legal_moves()
        if not moves:
            return self._decision(resign=True, comment=text, error=error, fallback=True)
        move = self.rng.choice(moves)
        self.emit(
            {
                "type": "error",
                "side": self.side,
                "text": "AI 未能给出着法，随机走一步 %s" % move.to_str,
            }
        )
        return self._decision(
            piece_id=move.piece_id,
            to=move.to_str,
            comment=text,
            error=error,
            fallback=True,
        )


class EnginePlayer:
    """本地 alpha-beta 引擎棋手，无需 API。"""

    kind = "engine"

    def __init__(self, side, depth=3, time_limit=5.0, seed=None, emit=None, label=""):
        self.side = side
        self.depth = depth
        self.time_limit = time_limit
        self.seed = seed
        self.emit = emit or (lambda event: None)
        self.label = label or "本地引擎（深度 %d）" % depth
        self.inbox = queue.Queue()
        self.usage_total = {"input": 0, "output": 0, "total": 0}

    def choose(self, game):
        self.emit(
            {
                "type": "thinking",
                "side": self.side,
                "text": "本地引擎思考中（深度 %d）…" % self.depth,
                "variant": "plan",
            }
        )
        started = time.time()
        move = choose_move(
            game, depth=self.depth, time_limit=self.time_limit, seed=self.seed
        )
        if move is None:
            return AgentDecision(resign=True, comment="无子可走")
        elapsed = time.time() - started
        self.emit(
            {
                "type": "tool_call",
                "side": self.side,
                "name": "engine_move",
                "arguments": {"depth": self.depth, "seconds": round(elapsed, 2)},
                "ok": True,
                "result": "引擎选择 %s %s（%.2fs）"
                % (move.from_square, move.to_square, elapsed),
            }
        )
        return AgentDecision(
            piece_id=move.piece_id,
            to=move.to_str,
            comment="",
            thinking="",
            usage={},
            steps=1,
        )
