"""供 LLM 使用的工具接口。

所有工具都用稳定的棋子编号（red_horse_1、black_cannon_2 ...）寻址，
代理不必直接处理坐标。工具定义是 OpenAI function-calling 格式，
其他提供商可自行转换。
"""
from __future__ import annotations

import json

from .coords import in_palace, numeric_square, parse_coord, square as square_name
from .game import IllegalMove
from .moves import in_check, is_attacked, other
from .notation import move_text
from .pieces import COLOR_ZH, normalize_piece_id
from .simulation import Simulation

PIECE_ID_HELP = (
    "棋子编号在对局中保持不变，例如 red_horse_1、black_advisor_2、"
    "red_general。格子写成 列-行 的纯数字：列 1-9，行 1-10；"
    "1-1 是红方左下角，9-10 是黑方右上角。"
)

SIM_TOOLS = {
    "list_pieces",
    "get_piece",
    "list_legal_moves",
    "get_status",
    "get_history",
    "list_pieces_in_area",
    "describe_square",
}

MAX_MESSAGES_PER_GAME = 6
MAX_MESSAGE_CHARS = 80


def tool_specs(allowed=None):
    """OpenAI 风格的 function 定义列表。"""
    specs = [
        {
            "type": "function",
            "function": {
                "name": "get_board",
                "description": (
                    "查看当前棋盘、FEN、轮到谁走、是否被将军、双方子力"
                    "以及合法着法数量。" + PIECE_ID_HELP
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_pieces",
                "description": "列出棋盘上的棋子及其编号、类型和位置。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "color": {
                            "type": "string",
                            "enum": ["both", "red", "black"],
                            "description": "列出哪一方，默认 both。",
                        }
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_piece",
                "description": "查看某枚棋子的类型、位置和所有可走点位。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "piece_id": {
                            "type": "string",
                            "description": "例如 red_horse_1。",
                        }
                    },
                    "required": ["piece_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_legal_moves",
                "description": (
                    "列出合法着法：给出 piece_id 时只看这一枚棋子，"
                    "不给出时列出你所有棋子的可走着法。每个着法包含目标格、"
                    "UCCI 坐标、中文记谱和被吃的棋子编号。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "piece_id": {
                            "type": "string",
                            "description": "可选，例如 red_horse_1。",
                        }
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "move",
                "description": (
                    "走一步棋：给出 piece_id 和目标格 to 即可；"
                    "也可以用 from 指定棋子当前所在格。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "piece_id": {
                            "type": "string",
                            "description": "要走的棋子，例如 red_cannon_1。",
                        },
                        "to": {
                            "type": "string",
                            "description": "目标格，例如 3-3（列 1-9，行 1-10）。",
                        },
                    },
                    "required": ["to"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_status",
                "description": "查看轮次、对局状态、结果、将军、着数、重复局面次数和子力。",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_history",
                "description": "查看最近若干步着法（中文记谱、吃子以及双方留言）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "last": {
                            "type": "integer",
                            "description": "返回最近多少步，默认 8。",
                        }
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_message",
                "description": (
                    "给对手发一条消息，会显示在对局界面上，对手下一回合读到。"
                    "可以寒暄、心理战或回应对方留言。每回合最多一条，"
                    "不超过 80 字。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "要发送的中文内容，不超过 80 字。",
                        }
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "start_simulation",
                "description": (
                    "进入推演棋盘：在虚拟棋盘上可以控制双方棋子试走（红黑按正常轮次交替），最多 8 步；"
                    "推演中的 move / list_legal_moves 等自动作用于虚拟棋盘，不影响真实对局。"
                    "注意：频繁推演会明显拖长一局的时间，只在关键局面使用。"
                ),
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "end_simulation",
                "description": "退出推演棋盘，回到真实对局。",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "offer_draw",
                "description": (
                    "向对手提议和棋，note 会显示在对局界面上。如果对手也调用 "
                    "offer_draw，双方同意，立即和棋。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note": {
                            "type": "string",
                            "description": "附言，例如“局面均势，和棋吧”。",
                        }
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "note",
                "description": (
                    "给自己记一条备忘，不发给对手；后续回合会出现在你的提示里。"
                    "适合记录计划、要防守的点或对手的习惯。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "备忘内容，40 字以内。"}
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "resign",
                "description": "认输。只在局面已经无望时使用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {"type": "string", "description": "简短原因。"}
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_pieces_in_area",
                "description": (
                    "按坐标范围列出棋子（含编号、x/y、格子名）。"
                    "x 是列号 0-8（a=0 ... i=8），y 是行号 0-9"
                    "（0 是红方底线）。不传参数就是全盘。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x_min": {"type": "integer", "description": "最小列号 0-8，默认 0"},
                        "x_max": {"type": "integer", "description": "最大列号 0-8，默认 8"},
                        "y_min": {"type": "integer", "description": "最小行号 0-9，默认 0"},
                        "y_max": {"type": "integer", "description": "最大行号 0-9，默认 9"},
                        "color": {
                            "type": "string",
                            "enum": ["both", "red", "black"],
                            "description": "只看哪一方，默认 both",
                        },
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "describe_square",
                "description": (
                    "查询单个格子：坐标、格子上的棋子、是否在九宫内、"
                    "是否被红方或黑方攻击。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "square": {
                            "type": "string",
                            "description": "格子名，例如 h2",
                        }
                    },
                    "required": ["square"],
                    "additionalProperties": False,
                },
            },
        },
    ]
    specs = [s for s in specs if s["function"]["name"] != "get_board"]
    if allowed:
        specs = [s for s in specs if s["function"]["name"] in allowed]
    return specs


TOOL_NAMES = [spec["function"]["name"] for spec in tool_specs()]


class ToolBox:
    """为一方的工具调用提供执行环境。

    move 只做合法性校验并返回预览，不落子；由外层（Match）统一执行，
    以便记录历史、留言和计时。
    """

    def __init__(self, game, side, allowed=None, player=None):
        self.game = game
        self.side = side
        self.player = player
        self.pending = None
        self.outbox = []
        self.messages_sent = 0
        self.resign_reason = ""
        self.draw_offer = None
        self.notes = []
        self.allowed = set(allowed) if allowed else None

    @property
    def sim(self):
        return getattr(self.player, "sim", None) if self.player is not None else None

    # ------------------------------------------------------------- dispatch
    def call(self, name, arguments=None):
        if self.allowed is not None and name not in self.allowed and name != "move":
            return {"ok": False, "error": "工具 %s 已被对局设置禁用" % (name,)}
        if isinstance(arguments, str):
            text = arguments.strip()
            if not text:
                arguments = {}
            else:
                try:
                    arguments = json.loads(text)
                except ValueError:
                    return {
                        "ok": False,
                        "error": "arguments 必须是 JSON 对象，收到 %r" % (text[:200],),
                    }
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "arguments 必须是 JSON 对象"}
        if name == "start_simulation":
            return self._t_start_simulation()
        if name == "end_simulation":
            return self._t_end_simulation()
        if self.sim is not None and name == "move":
            try:
                return self._t_sim_move(arguments)
            except IllegalMove as exc:
                return {"ok": False, "error": str(exc)}
        if self.sim is not None and name in SIM_TOOLS:
            saved = self.game
            self.game = self.sim.game
            try:
                return self._dispatch(name, arguments)
            finally:
                self.game = saved
        return self._dispatch(name, arguments)

    def _dispatch(self, name, arguments):
        handler = getattr(self, "_t_" + name, None)
        if handler is None:
            return {"ok": False, "error": "未知工具 %r" % (name,)}
        try:
            return handler(**arguments)
        except IllegalMove as exc:
            return {"ok": False, "error": str(exc)}
        except (TypeError, ValueError, KeyError) as exc:
            return {"ok": False, "error": "参数错误：%s" % (exc,)}

    # -------------------------------------------------------------- helpers
    def _require_own_piece(self, piece_id=None, frm=None):
        if piece_id is None and frm is not None:
            x, y = parse_coord(frm)
            piece = self.game.board.piece_at(x, y)
            if piece is None:
                raise IllegalMove("%s 上没有棋子" % (frm,))
            return piece
        if piece_id is None:
            raise IllegalMove("缺少 piece_id（也可以用 from 指定棋子所在格）")
        try:
            normalised = normalize_piece_id(piece_id, self.side)
        except ValueError as exc:
            raise IllegalMove(str(exc))
        piece = self.game.piece(normalised)
        if piece is None:
            mine = sorted(p.id for p in self.game.board.side_pieces(self.side))
            raise IllegalMove(
                "未知棋子编号 %r；你方棋子有：%s" % (piece_id, "、".join(mine))
            )
        return piece

    def _piece_summary(self, piece):
        return {
            "id": piece.id,
            "color": piece.color,
            "type": piece.type,
            "name": piece.name_zh,
            "square": numeric_square(piece.x, piece.y),
            "x": piece.x + 1,
            "y": piece.y + 1,
            "glyph": piece.glyph,
        }

    # ---------------------------------------------------------------- tools
    def _t_list_pieces(self, color="both"):
        color = str(color).lower()
        if color not in ("both", "red", "black"):
            raise ValueError("color 只能是 both、red 或 black")
        wanted = None if color == "both" else color
        pieces = [
            self._piece_summary(p)
            for p in sorted(self.game.board.pieces.values(), key=lambda p: p.id)
            if wanted is None or p.color == wanted
        ]
        return {
            "ok": True,
            "pieces": pieces,
            "count": len(pieces),
            "your_color": self.side,
        }

    def _t_get_piece(self, piece_id):
        piece = self._require_own_piece(piece_id)
        moves = self.sim.legal_moves_for(piece.id) if self.sim else self.game.legal_moves(piece.id)
        return {
            "ok": True,
            "piece": self._piece_summary(piece),
            "legal_moves": [numeric_square(*m.to) for m in moves],
            "move_details": [self._move_detail(m, piece.color) for m in moves],
            "in_check": in_check(self.game.board, self.game.turn),
            "simulation": bool(self.sim),
        }

    def _move_detail(self, move, color):
        board = self.game.board
        captured = board.pieces.get(move.capture_id) if move.capture_id else None
        preview = board.clone()
        preview.make(move)
        return {
            "to": numeric_square(*move.to),
            "notation": move_text(board, move, color),
            "capture": captured.id if captured else None,
            "capture_name": captured.name_zh if captured else None,
            "gives_check": bool(in_check(preview, other(color))),
        }

    def _t_list_legal_moves(self, piece_id=None):
        board = self.game.board
        if piece_id is not None:
            piece = self._require_own_piece(piece_id)
            color = piece.color if self.sim else self.side
            moves = self.sim.legal_moves_for(piece.id) if self.sim else self.game.legal_moves(piece.id)
            details = [self._move_detail(move, color) for move in moves]
            return {
                "ok": True,
                "piece_id": piece.id,
                "your_color": self.side,
                "moves": {piece.id: details} if details else {},
                "move_count": len(details),
                "piece_count": 1 if details else 0,
                "simulation": bool(self.sim),
            }
        if self.sim:
            pieces = sorted(board.side_pieces(self.game.turn), key=lambda p: p.id)
        else:
            pieces = sorted(board.side_pieces(self.side), key=lambda p: p.id)
        result = {}
        total = 0
        for piece in pieces:
            moves = self.sim.legal_moves_for(piece.id) if self.sim else self.game.legal_moves(piece.id)
            if not moves:
                continue
            result[piece.id] = [numeric_square(*move.to) for move in moves]
            total += len(moves)
        return {
            "ok": True,
            "piece_id": None,
            "your_color": self.side,
            "moves": result,
            "move_count": total,
            "piece_count": len(result),
            "simulation": bool(self.sim),
        }

    def _t_list_pieces_in_area(self, x_min=1, x_max=9, y_min=1, y_max=10, color="both"):
        try:
            x_min, x_max = int(x_min), int(x_max)
            y_min, y_max = int(y_min), int(y_max)
        except (TypeError, ValueError):
            raise ValueError("x/y 范围必须是整数")
        if not 1 <= x_min <= x_max <= 9:
            raise ValueError("x 范围需满足 1 <= x_min <= x_max <= 9")
        if not 1 <= y_min <= y_max <= 10:
            raise ValueError("y 范围需满足 1 <= y_min <= y_max <= 10")
        x_min, x_max, y_min, y_max = x_min - 1, x_max - 1, y_min - 1, y_max - 1
        color = str(color).lower()
        if color not in ("both", "red", "black"):
            raise ValueError("color 只能是 both、red 或 black")
        pieces = []
        for piece in sorted(self.game.board.pieces.values(), key=lambda p: (p.y, p.x)):
            if not (x_min <= piece.x <= x_max and y_min <= piece.y <= y_max):
                continue
            if color != "both" and piece.color != color:
                continue
            pieces.append(self._piece_summary(piece))
        return {
            "ok": True,
            "x_min": x_min + 1,
            "x_max": x_max + 1,
            "y_min": y_min + 1,
            "y_max": y_max + 1,
            "color": color,
            "pieces": pieces,
            "count": len(pieces),
        }

    def _t_describe_square(self, square="1-1"):
        x, y = parse_coord(square)
        board = self.game.board
        piece = board.piece_at(x, y)
        return {
            "ok": True,
            "square": numeric_square(x, y),
            "x": x + 1,
            "y": y + 1,
            "piece": self._piece_summary(piece) if piece else None,
            "in_red_palace": in_palace("red", x, y),
            "in_black_palace": in_palace("black", x, y),
            "on_red_side": y <= 4,
            "attacked_by_red": is_attacked(board, x, y, "red"),
            "attacked_by_black": is_attacked(board, x, y, "black"),
        }

    def _t_move(self, piece_id=None, to=None, **extra):
        game = self.game
        if game.status != "playing":
            raise IllegalMove("对局已结束：%s" % (game.result,))
        if game.turn != self.side:
            raise IllegalMove(
                "现在轮到%s走棋，不是你" % (COLOR_ZH[game.turn],)
            )
        if to is None:
            raise IllegalMove("缺少目标格 to（例如 3-3）")
        tx, ty = parse_coord(to)
        target = square_name(tx, ty)
        frm = extra.get("from") or extra.get("source")
        piece = self._require_own_piece(piece_id, frm)
        if piece.color != self.side:
            raise IllegalMove("%s 属于%s方" % (piece.id, COLOR_ZH[piece.color]))
        move = game.find_move(piece.id, target)
        if move is None:
            targets = [numeric_square(*m.to) for m in game.legal_moves(piece.id)]
            raise IllegalMove(
                "%s 不能走到 %s；可走：%s"
                % (piece.id, numeric_square(tx, ty), ", ".join(targets) or "无")
            )

        preview = game.board.clone()
        preview.make(move)
        gives_check = in_check(preview, other(self.side))
        captured = game.board.occ.get(move.to)
        self.pending = (piece.id, move.to_str)
        return {
            "ok": True,
            "piece_id": piece.id,
            "from": numeric_square(*move.frm),
            "to": numeric_square(*move.to),
            "notation": move_text(game.board, move, self.side),
            "capture": captured,
            "check": gives_check,
            "turn": other(self.side),
            "note": "着法已接受，本回合结束后生效。",
        }

    def _t_send_message(self, text=""):
        if self.game.status != "playing":
            return {"ok": False, "error": "对局已结束，不能再发消息"}
        text = str(text).strip()
        if not text:
            return {"ok": False, "error": "消息不能为空"}
        if len(text) > MAX_MESSAGE_CHARS:
            text = text[:MAX_MESSAGE_CHARS]
        if self.messages_sent >= MAX_MESSAGES_PER_GAME:
            return {
                "ok": False,
                "error": "本局消息已用完（最多 %d 条）" % MAX_MESSAGES_PER_GAME,
            }
        self.messages_sent += 1
        self.outbox.append(text)
        return {
            "ok": True,
            "delivered": True,
            "text": text,
            "note": "消息已发送，对手下一回合会看到。",
        }

    def _t_get_status(self):
        game = self.game
        key = game.board.key(game.turn)
        return {
            "ok": True,
            "turn": game.turn,
            "your_color": self.side,
            "status": game.status,
            "result": game.result,
            "check": game.in_check(),
            "ply": len(game.history),
            "halfmove_clock": game.halfmove_clock,
            "repetitions": game.positions.get(key, 0),
            "material": game.material(),
            "simulation": bool(self.sim),
            "sim_plies": self.sim.plies if self.sim else 0,
        }

    def _t_get_history(self, last=8):
        try:
            last = max(1, min(int(last), 100))
        except (TypeError, ValueError):
            last = 8
        moves = [
            {
                "ply": record.ply,
                "side": record.side,
                "piece_id": record.piece_id,
                "from": numeric_square(*record.frm),
                "to": numeric_square(*record.to),
                "capture": record.capture,
                "notation": record.notation,
                "gave_check": record.gave_check,
                "comment": record.comment,
                "thinking": record.thinking,
            }
            for record in self.game.history[-last:]
        ]
        return {"ok": True, "moves": moves, "count": len(moves)}

    def _t_start_simulation(self):
        if self.game.status != "playing":
            return {"ok": False, "error": "对局已结束，不能推演"}
        if self.sim is not None:
            return {"ok": False, "error": "已经在推演中，继续走子或调用 end_simulation"}
        if self.player is None:
            return {"ok": False, "error": "当前棋手不支持推演"}
        self.player.sim = Simulation(self.game)
        snapshot = self.player.sim.snapshot()
        return {
            "ok": True,
            "simulation": True,
            "plies": 0,
            "limit": self.player.sim.limit,
            "fen": snapshot["fen"],
            "your_color": self.side,
            "note": (
                "已进入推演：move / list_legal_moves / get_status 等作用于虚拟棋盘，"
                "不影响真实对局，最多 8 步后自动退出。推演较多会明显拖长对局时间。"
            ),
        }

    def _t_end_simulation(self):
        if self.sim is None:
            return {"ok": False, "error": "当前没有推演"}
        self.player.sim = None
        return {"ok": True, "simulation": False, "note": "已退出推演，回到真实棋盘。"}

    def _t_sim_move(self, arguments):
        sim = self.sim
        if sim is None:
            return {"ok": False, "error": "当前没有推演"}
        piece_id = arguments.get("piece_id")
        to = arguments.get("to")
        frm = arguments.get("from") or arguments.get("source")
        if piece_id is None and frm:
            fx, fy = parse_coord(frm)
            piece = sim.game.board.piece_at(fx, fy)
            piece_id = piece.id if piece else None
        if not piece_id:
            return {"ok": False, "error": "缺少 piece_id（也可以用 from 指定起点）"}
        if to is None:
            return {"ok": False, "error": "缺少目标格 to"}
        tx, ty = parse_coord(to)
        record, ended = sim.move(piece_id, square_name(tx, ty))
        gives_check = in_check(sim.game.board, other(record.side))
        detail = {
            "ok": True,
            "simulated": True,
            "piece_id": record.piece_id,
            "from": numeric_square(*record.frm),
            "to": numeric_square(*record.to),
            "notation": record.notation,
            "capture": record.capture,
            "check": gives_check,
            "plies": sim.plies,
            "limit": sim.limit,
            "ended": ended,
        }
        if ended:
            self.player.sim = None
            detail["note"] = "推演已达 8 步上限，已自动退出；请回到真实棋盘落子。"
        else:
            detail["note"] = "推演着法，不影响真实对局；可以继续走或调用 end_simulation。"
        return detail

    def _t_offer_draw(self, note=""):
        note = str(note or "").strip()[:80]
        self.draw_offer = note or "和棋"
        return {
            "ok": True,
            "note": note,
            "message": "已向对手提议和棋，等对手回应。",
        }

    def _t_note(self, text=""):
        text = str(text or "").strip()[:120]
        if not text:
            return {"ok": False, "error": "备忘不能为空"}
        self.notes.append(text)
        self.notes = self.notes[-10:]
        return {"ok": True, "notes": list(self.notes)}

    def _t_resign(self, reason=""):
        if self.game.status != "playing":
            return {"ok": False, "error": "对局已经结束"}
        reason = str(reason or "").strip() or "认输"
        self.resign_reason = reason[:120]
        result = self.game.resign(self.side, reason)
        return {"ok": True, "status": self.game.status, "result": result, "reason": reason}
