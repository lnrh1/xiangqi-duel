path = "xiangqi_duel/tools.py"
src = open(path, encoding="utf-8").read()

# imports + constants
src = src.replace("from .pieces import COLOR_ZH, normalize_piece_id",
                  "from .pieces import COLOR_ZH, normalize_piece_id\nfrom .simulation import Simulation", 1)
src = src.replace("MAX_MESSAGES_PER_GAME = 6", '''SIM_TOOLS = {
    "list_pieces",
    "get_piece",
    "list_legal_moves",
    "get_status",
    "get_history",
    "list_pieces_in_area",
    "describe_square",
}

MAX_MESSAGES_PER_GAME = 6''', 1)

# specs: insert before offer_draw
anchor = '''        {
            "type": "function",
            "function": {
                "name": "offer_draw",'''
addition = '''        {
            "type": "function",
            "function": {
                "name": "start_simulation",
                "description": (
                    "进入推演棋盘：在虚拟棋盘上可以控制双方棋子试走，最多 8 步；"
                    "推演中的 move / list_legal_moves 等自动作用于虚拟棋盘，不影响真实对局。"
                    "注意：频繁推演会明显拖长一局的时间，只在关键局面使用。"
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
                "name": "end_simulation",
                "description": "退出推演棋盘，回到真实对局。",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        },
'''
if anchor not in src:
    raise SystemExit("offer spec anchor missing")
src = src.replace(anchor, addition + anchor, 1)

# ToolBox init player + sim property
old = '''    def __init__(self, game, side, allowed=None):
        self.game = game
        self.side = side'''
new = '''    def __init__(self, game, side, allowed=None, player=None):
        self.game = game
        self.side = side
        self.player = player'''
if old not in src:
    raise SystemExit("toolbox init anchor missing")
src = src.replace(old, new, 1)
src = src.replace('''        self.allowed = set(allowed) if allowed else None''',
'''        self.allowed = set(allowed) if allowed else None

    @property
    def sim(self):
        return getattr(self.player, "sim", None) if self.player is not None else None''', 1)

# dispatch refactor
old = '''        handler = getattr(self, "_t_" + name, None)
        if handler is None:
            return {"ok": False, "error": "未知工具 %r" % (name,)}
        try:
            return handler(**arguments)
        except IllegalMove as exc:
            return {"ok": False, "error": str(exc)}
        except (TypeError, ValueError, KeyError) as exc:
            return {"ok": False, "error": "参数错误：%s" % (exc,)}'''
new = '''        if name == "start_simulation":
            return self._t_start_simulation()
        if name == "end_simulation":
            return self._t_end_simulation()
        if self.sim is not None and name == "move":
            return self._t_sim_move(arguments)
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
            return {"ok": False, "error": "参数错误：%s" % (exc,)}'''
if old not in src:
    raise SystemExit("dispatch anchor missing")
src = src.replace(old, new, 1)

# get_piece sim-aware
old = '''    def _t_get_piece(self, piece_id):
        piece = self._require_own_piece(piece_id)
        moves = self.game.legal_moves(piece.id)
        return {
            "ok": True,
            "piece": self._piece_summary(piece),
            "legal_moves": [m.to_str for m in moves],
            "move_details": [
                {
                    "to": m.to_str,
                    "ucci": m.ucci,
                    "notation": move_text(self.game.board, m, piece.color),
                    "capture": m.capture_id,
                }
                for m in moves
            ],
            "in_check": self.game.in_check(),
        }'''
new = '''    def _t_get_piece(self, piece_id):
        piece = self._require_own_piece(piece_id)
        moves = self.sim.legal_moves_for(piece.id) if self.sim else self.game.legal_moves(piece.id)
        return {
            "ok": True,
            "piece": self._piece_summary(piece),
            "legal_moves": [m.to_str for m in moves],
            "move_details": [self._move_detail(m, piece.color) for m in moves],
            "in_check": in_check(self.game.board, self.game.turn),
            "simulation": bool(self.sim),
        }'''
if old not in src:
    raise SystemExit("get_piece anchor missing")
src = src.replace(old, new, 1)

# move details helper + list rewrite
start = src.find("    def _t_list_legal_moves(self, piece_id=None):")
end = src.find("    def _t_list_pieces_in_area", start)
if start == -1 or end == -1:
    raise SystemExit("list legal block anchors missing")
block = '''    def _move_detail(self, move, color):
        board = self.game.board
        captured = board.pieces.get(move.capture_id) if move.capture_id else None
        preview = board.clone()
        preview.make(move)
        return {
            "to": move.to_str,
            "ucci": move.ucci,
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
            pieces = sorted(board.pieces.values(), key=lambda p: p.id)
        else:
            pieces = sorted(board.side_pieces(self.side), key=lambda p: p.id)
        result = {}
        total = 0
        for piece in pieces:
            moves = self.sim.legal_moves_for(piece.id) if self.sim else self.game.legal_moves(piece.id)
            if not moves:
                continue
            result[piece.id] = [move.to_str for move in moves]
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

'''
src = src[:start] + block + src[end:]

# simulation handlers before _t_offer_draw
anchor2 = "    def _t_offer_draw(self, note=""):"
handlers = '''    def _t_start_simulation(self):
        if self.game.status != "playing":
            return {"ok": False, "error": "对局已结束，不能推演"}
        if self.sim is not None:
            return {
                "ok": False,
                "error": "已经在推演中，继续在虚拟棋盘走子或调用 end_simulation",
            }
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
                "已进入推演：move / list_legal_moves / get_status 等会作用于虚拟棋盘，"
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
            piece = sim.game.board.piece_at(*parse_square(frm))
            piece_id = piece.id if piece else None
        if not piece_id:
            return {"ok": False, "error": "缺少 piece_id（也可以用 from 指定起点）"}
        if to is None:
            return {"ok": False, "error": "缺少目标格 to"}
        record, ended = sim.move(piece_id, to)
        gives_check = in_check(sim.game.board, other(record.side))
        detail = {
            "ok": True,
            "simulated": True,
            "piece_id": record.piece_id,
            "from": record.from_square,
            "to": record.to_square,
            "ucci": record.ucci,
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

'''
if "def _t_start_simulation" not in src:
    if anchor2 not in src:
        raise SystemExit("offer handler anchor missing")
    src = src.replace(anchor2, handlers + anchor2, 1)

# get_status simulation fields
old = '''            "material": game.material(),
        }'''
new = '''            "material": game.material(),
            "simulation": bool(self.sim),
            "sim_plies": self.sim.plies if self.sim else 0,
        }'''
if old not in src:
    raise SystemExit("get_status anchor missing")
src = src.replace(old, new, 1)

open(path, "w", encoding="utf-8").write(src)
print("tools simulation")
