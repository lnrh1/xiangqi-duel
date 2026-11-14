"""Virtual analysis board used by the simulation tool and human UI."""

from __future__ import annotations

from .coords import square as square_name
from .game import IllegalMove
from .moves import in_check


class Simulation:
    limit = 8

    def __init__(self, game):
        self.game = game.clone()
        self.plies = 0
        self.last = None

    def legal_moves_for(self, piece_id):
        piece = self.game.piece(piece_id)
        if piece is None:
            return []
        saved = self.game.turn
        self.game.turn = piece.color
        try:
            return self.game.legal_moves(piece_id)
        finally:
            self.game.turn = saved

    def move(self, piece_id, to):
        piece = self.game.piece(piece_id)
        if piece is None:
            raise IllegalMove("推演棋盘上没有 %s" % (piece_id,))
        if self.plies >= self.limit:
            raise IllegalMove("推演已达 %d 步上限" % self.limit)
        saved = self.game.turn
        self.game.turn = piece.color
        try:
            record = self.game.play(piece_id, to, adjudicate=False)
        except Exception:
            self.game.turn = saved
            raise
        self.plies += 1
        self.last = record
        return record, self.plies >= self.limit

    def snapshot(self):
        game = self.game
        pieces = [
            {
                "id": piece.id,
                "color": piece.color,
                "type": piece.type,
                "x": piece.x,
                "y": piece.y,
                "square": square_name(piece.x, piece.y),
                "glyph": piece.glyph,
                "name": piece.name_zh,
            }
            for piece in sorted(game.board.pieces.values(), key=lambda item: item.id)
        ]
        legal = {}
        for piece in list(game.board.pieces.values()):
            targets = [move.to_str for move in self.legal_moves_for(piece.id)]
            if targets:
                legal[piece.id] = targets
        last = None
        if self.last is not None:
            last = {
                "from": self.last.from_square,
                "to": self.last.to_square,
                "side": self.last.side,
            }
        return {
            "fen": game.board.to_fen(game.turn, game.halfmove_clock, game.fullmove),
            "turn": game.turn,
            "plies": self.plies,
            "limit": self.limit,
            "pieces": pieces,
            "legal": legal,
            "last": last,
            "check": in_check(game.board, game.turn),
        }
