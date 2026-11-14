"""Board representation, FEN serialisation and ASCII rendering."""
from __future__ import annotations

from .coords import FILES, HEIGHT, WIDTH
from .pieces import (
    ADVISOR, BLACK, CANNON, CHARIOT, ELEPHANT, FEN_LETTER, GENERAL, HORSE,
    LETTER_TYPE, RED, SOLDIER, Piece,
)

_BACK_RANK = (
    (0, CHARIOT), (1, HORSE), (2, ELEPHANT), (3, ADVISOR), (4, GENERAL),
    (5, ADVISOR), (6, ELEPHANT), (7, HORSE), (8, CHARIOT),
)
_SOLDIER_FILES = (0, 2, 4, 6, 8)

START_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"


def initial_pieces():
    """Build the standard starting army for both sides."""
    pieces = {}
    for color, back_y, cannon_y, soldier_y in (
        (RED, 0, 2, 3),
        (BLACK, 9, 7, 6),
    ):
        counters = {}

        def add(piece_type, x, y):
            count = counters.get(piece_type, 0) + 1
            counters[piece_type] = count
            if piece_type == GENERAL:
                piece_id = "%s_%s" % (color, piece_type)
            else:
                piece_id = "%s_%s_%d" % (color, piece_type, count)
            pieces[piece_id] = Piece(piece_id, color, piece_type, x, y)

        for x, piece_type in _BACK_RANK:
            add(piece_type, x, back_y)
        for x in (1, 7):
            add(CANNON, x, cannon_y)
        for x in _SOLDIER_FILES:
            add(SOLDIER, x, soldier_y)
    return pieces


class Board:
    """A Xiangqi position: pieces by id plus an occupancy index."""

    __slots__ = ("pieces", "occ")

    def __init__(self, pieces=None):
        self.pieces = {}
        self.occ = {}
        if pieces:
            values = pieces.values() if isinstance(pieces, dict) else pieces
            for piece in values:
                self._place(piece)

    # ------------------------------------------------------------------ setup
    @classmethod
    def initial(cls):
        return cls(initial_pieces())

    def _place(self, piece):
        self.pieces[piece.id] = piece
        self.occ[(piece.x, piece.y)] = piece.id

    def clone(self):
        return Board(self.pieces)

    # --------------------------------------------------------------- accessors
    def piece_at(self, x, y):
        piece_id = self.occ.get((x, y))
        return self.pieces[piece_id] if piece_id else None

    def general(self, color):
        for piece in self.pieces.values():
            if piece.type == GENERAL and piece.color == color:
                return piece
        return None

    def side_pieces(self, color):
        return [p for p in self.pieces.values() if p.color == color]

    # ------------------------------------------------------------- make/unmake
    def make(self, move):
        """Apply move and return an undo token."""
        piece = self.pieces[move.piece_id]
        frm = (piece.x, piece.y)
        captured_id = self.occ.get(move.to)
        captured = self.pieces.pop(captured_id) if captured_id else None
        if captured_id:
            del self.occ[move.to]
        del self.occ[frm]
        moved = Piece(piece.id, piece.color, piece.type, move.to[0], move.to[1])
        self.pieces[piece.id] = moved
        self.occ[move.to] = piece.id
        return (piece.id, frm, move.to, captured)

    def unmake(self, undo):
        piece_id, frm, to, captured = undo
        piece = self.pieces[piece_id]
        del self.occ[to]
        self.pieces[piece_id] = Piece(
            piece.id, piece.color, piece.type, frm[0], frm[1]
        )
        self.occ[frm] = piece_id
        if captured is not None:
            self.pieces[captured.id] = captured
            self.occ[to] = captured.id

    # ------------------------------------------------------------------ FEN
    def to_fen(self, turn=RED, halfmove=0, fullmove=1):
        ranks = []
        for y in range(HEIGHT - 1, -1, -1):
            parts = []
            empty = 0
            for x in range(WIDTH):
                piece = self.piece_at(x, y)
                if piece is None:
                    empty += 1
                    continue
                if empty:
                    parts.append(str(empty))
                    empty = 0
                letter = FEN_LETTER[piece.type]
                parts.append(letter.upper() if piece.color == RED else letter)
            if empty:
                parts.append(str(empty))
            ranks.append("".join(parts))
        side = "w" if turn == RED else "b"
        return "%s %s - - %d %d" % ("/".join(ranks), side, halfmove, fullmove)

    @classmethod
    def from_fen(cls, fen):
        fields = str(fen).strip().split()
        if len(fields) < 2:
            raise ValueError("FEN needs at least a board and a side to move")
        ranks = fields[0].split("/")
        if len(ranks) != HEIGHT:
            raise ValueError("FEN board must have %d ranks" % HEIGHT)
        counters = {}
        pieces = {}
        for row, rank in enumerate(ranks):
            y = HEIGHT - 1 - row
            x = 0
            for ch in rank:
                if ch.isdigit():
                    x += int(ch)
                    continue
                lower = ch.lower()
                if lower not in LETTER_TYPE:
                    raise ValueError("unknown FEN piece %r" % ch)
                color = RED if ch.isupper() else BLACK
                piece_type = LETTER_TYPE[lower]
                counters[(color, piece_type)] = counters.get((color, piece_type), 0) + 1
                count = counters[(color, piece_type)]
                if piece_type == GENERAL:
                    piece_id = "%s_%s" % (color, piece_type)
                else:
                    piece_id = "%s_%s_%d" % (color, piece_type, count)
                pieces[piece_id] = Piece(piece_id, color, piece_type, x, y)
                x += 1
            if x != WIDTH:
                raise ValueError("FEN rank %r does not have 9 files" % rank)
        turn = RED if fields[1].lower() in ("w", "r", "red") else BLACK
        halfmove = int(fields[4]) if len(fields) > 4 and fields[4].isdigit() else 0
        fullmove = int(fields[5]) if len(fields) > 5 and fields[5].isdigit() else 1
        return cls(pieces), turn, halfmove, fullmove

    def key(self, turn):
        """Position key for repetition detection (board + side to move)."""
        return self.to_fen(turn).split(" - - ")[0]

    # ---------------------------------------------------------------- display
    def ascii(self, unicode=False):
        lines = ["   " + " ".join(FILES)]
        for y in range(HEIGHT - 1, -1, -1):
            row = []
            for x in range(WIDTH):
                piece = self.piece_at(x, y)
                if piece is None:
                    row.append(".")
                elif unicode:
                    row.append(piece.glyph)
                else:
                    letter = FEN_LETTER[piece.type]
                    row.append(letter.upper() if piece.color == RED else letter)
            lines.append("%d  %s" % (y, " ".join(row)))
        return "\n".join(lines)
