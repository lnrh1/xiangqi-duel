"""Game state: turns, history, win/draw rules and snapshots."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .board import Board
from .coords import parse_square, square
from .moves import legal_moves, in_check, other
from .notation import move_text
from .pieces import (
    ADVISOR, BLACK, CANNON, CHARIOT, COLOR_ZH, ELEPHANT, HORSE, RED,
    SOLDIER,
)

DRAW_HALFMOVES = 120  # 60 full moves without a capture -> draw
ATTACKERS = (CHARIOT, CANNON, HORSE, SOLDIER)
VALUES = {
    CHARIOT: 900, CANNON: 450, HORSE: 400,
    ADVISOR: 200, ELEPHANT: 200, SOLDIER: 100, "general": 0,
}


@dataclass
class MoveRecord:
    ply: int
    side: str
    piece_id: str
    frm: tuple
    to: tuple
    capture: Optional[str]
    notation: str
    gave_check: bool
    fen: str
    ucci: str
    comment: str = ""
    thinking: str = ""
    usage: dict = field(default_factory=dict)

    @property
    def from_square(self):
        return square(*self.frm)

    @property
    def to_square(self):
        return square(*self.to)

    def to_dict(self):
        return {
            "ply": self.ply,
            "side": self.side,
            "piece_id": self.piece_id,
            "from": square(*self.frm),
            "to": square(*self.to),
            "capture": self.capture,
            "notation": self.notation,
            "ucci": self.ucci,
            "gave_check": self.gave_check,
            "fen": self.fen,
            "comment": self.comment,
            "thinking": self.thinking,
        }


class IllegalMove(ValueError):
    """Raised when a move cannot be played in the current position."""


class Game:
    """A full Xiangqi game with rules, history and repetition detection."""

    def __init__(self, fen=None, max_plies=400):
        if fen:
            board, turn, halfmove, fullmove = Board.from_fen(fen)
        else:
            board, turn, halfmove, fullmove = Board.initial(), RED, 0, 1
        self.board = board
        self.turn = turn
        self.halfmove_clock = halfmove
        self.fullmove = fullmove
        self.max_plies = max_plies
        self.start_fen = self.board.to_fen(turn, halfmove, fullmove)
        self.history = []
        self.position_log = [self.board.key(self.turn)]
        self.positions = Counter(self.position_log)
        self.status = "playing"
        self.result = None
        self._check_state()

    # ------------------------------------------------------------------ state
    @property
    def over(self):
        return self.status != "playing"

    def legal_moves(self, piece_id=None):
        return legal_moves(self.board, self.turn, piece_id)

    def all_legal_moves(self):
        return legal_moves(self.board, self.turn)

    def in_check(self):
        return in_check(self.board, self.turn)

    def piece(self, piece_id):
        return self.board.pieces.get(piece_id)

    def material(self):
        totals = {RED: 0, BLACK: 0}
        for piece in self.board.pieces.values():
            totals[piece.color] += VALUES[piece.type]
        return totals

    # ------------------------------------------------------------------- moves
    def find_move(self, piece_id, to):
        try:
            x, y = parse_square(to)
        except ValueError:
            return None
        for move in self.legal_moves(piece_id):
            if move.to == (x, y):
                return move
        return None

    def illegal_reason(self, piece_id, to):
        piece = self.piece(piece_id)
        if piece is None:
            return "there is no piece with id %r" % (piece_id,)
        if piece.color != self.turn:
            return "%s belongs to %s, but it is %s's turn" % (
                piece_id, COLOR_ZH[piece.color], COLOR_ZH[self.turn],
            )
        targets = self.legal_moves(piece_id)
        if not targets:
            return "%s has no legal move right now" % (piece_id,)
        return "%s cannot move to %s; legal targets: %s" % (
            piece_id, to, ", ".join(m.to_str for m in targets),
        )

    def play(self, piece_id, to, *, comment="", thinking="", usage=None):
        """Play a move by piece id and destination square."""
        if self.status != "playing":
            raise IllegalMove("the game is already over: %s" % (self.result,))
        piece = self.piece(piece_id)
        if piece is None:
            raise IllegalMove("there is no piece with id %r" % (piece_id,))
        if piece.color != self.turn:
            raise IllegalMove(
                "%s belongs to %s, but it is %s's turn" % (
                    piece_id, COLOR_ZH[piece.color], COLOR_ZH[self.turn],
                )
            )
        move = self.find_move(piece_id, to)
        if move is None:
            raise IllegalMove(self.illegal_reason(piece_id, to))

        notation = move_text(self.board, move, self.turn)
        side = self.turn
        captured = self.board.occ.get(move.to)
        self.board.make(move)
        self.turn = other(side)
        gave_check = in_check(self.board, self.turn)
        self.halfmove_clock = 0 if captured else self.halfmove_clock + 1
        if side == BLACK:
            self.fullmove += 1
        fen = self.board.to_fen(self.turn, self.halfmove_clock, self.fullmove)
        record = MoveRecord(
            ply=len(self.history) + 1,
            side=side,
            piece_id=piece_id,
            frm=move.frm,
            to=move.to,
            capture=captured,
            notation=notation,
            gave_check=gave_check,
            fen=fen,
            ucci=move.ucci,
            comment=comment,
            thinking=thinking,
            usage=usage or {},
        )
        self.history.append(record)
        key = self.board.key(self.turn)
        self.position_log.append(key)
        self.positions[key] += 1
        self._check_state()
        return record

    def abort(self, reason="aborted"):
        """End the game without a winner (timeout, stopped by the user)."""
        if self.status != "playing":
            return self.result
        self._finish(None, reason, "aborted")
        return self.result

    def resign(self, side, reason="resignation"):
        if self.status != "playing":
            return self.result
        self._finish(other(side), reason, "resign")
        return self.result

    # ------------------------------------------------------------------- rules
    def _finish(self, winner, reason, code=None):
        self.status = "finished"
        self.result = {
            "winner": winner,
            "winner_label": COLOR_ZH.get(winner) if winner else None,
            "reason": reason,
            "code": code or reason,
        }

    def _check_state(self):
        if self.status != "playing":
            return
        if not self.all_legal_moves():
            if self.in_check():
                self._finish(other(self.turn), "checkmate", "checkmate")
            else:
                self._finish(other(self.turn), "stalemate", "stalemate")
            return
        if self.halfmove_clock >= DRAW_HALFMOVES:
            self._finish(None, "sixty-move rule", "sixty-move")
            return
        red_attack = any(p.type in ATTACKERS for p in self.board.side_pieces(RED))
        black_attack = any(p.type in ATTACKERS for p in self.board.side_pieces(BLACK))
        if not red_attack and not black_attack:
            self._finish(None, "insufficient material", "insufficient")
            return
        key = self.board.key(self.turn)
        if self.positions[key] >= 3:
            outcome = self._repetition_outcome(key)
            if outcome is not None:
                self._finish(*outcome)

    def _repetition_outcome(self, key):
        indices = [i for i, k in enumerate(self.position_log) if k == key]
        if len(indices) < 3:
            return None
        start = indices[-3]
        cycle = self.history[start:]
        for side in (RED, BLACK):
            side_moves = [m for m in cycle if m.side == side]
            if side_moves and all(m.gave_check for m in side_moves):
                return other(side), "perpetual check", "perpetual"
        return None, "threefold repetition", "threefold"

    # ---------------------------------------------------------------- copying
    def clone(self):
        """Independent copy of the position for a worker thread."""
        copy = Game.__new__(Game)
        copy.board = self.board.clone()
        copy.turn = self.turn
        copy.halfmove_clock = self.halfmove_clock
        copy.fullmove = self.fullmove
        copy.max_plies = self.max_plies
        copy.start_fen = self.start_fen
        copy.history = list(self.history)
        copy.position_log = list(self.position_log)
        copy.positions = Counter(self.positions)
        copy.status = self.status
        copy.result = dict(self.result) if self.result else None
        return copy

    # ---------------------------------------------------------------- display
    def ascii(self, unicode=False):
        return self.board.ascii(unicode=unicode)

    def snapshot(self):
        legal = {}
        if self.status == "playing":
            for piece in self.board.side_pieces(self.turn):
                targets = self.legal_moves(piece.id)
                if targets:
                    legal[piece.id] = [m.to_str for m in targets]
        pieces = sorted(
            self.board.pieces.values(),
            key=lambda p: (p.color, p.type, p.x, p.y),
        )
        material = self.material()
        return {
            "start_fen": self.start_fen,
            "fen": self.board.to_fen(
                self.turn, self.halfmove_clock, self.fullmove
            ),
            "turn": self.turn,
            "status": self.status,
            "result": self.result,
            "check": self.in_check() if self.status == "playing" else False,
            "ply": len(self.history),
            "halfmove_clock": self.halfmove_clock,
            "pieces": [p.to_dict() for p in pieces],
            "legal": legal,
            "board": self.board.ascii(),
            "moves": [m.to_dict() for m in self.history],
            "material": material,
        }

    def to_dict(self):
        return {
            "start_fen": self.start_fen,
            "result": self.result,
            "status": self.status,
            "moves": [m.to_dict() for m in self.history],
        }
