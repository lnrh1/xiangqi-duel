"""Xiangqi Duel - Chinese chess for AI agents and humans."""
from __future__ import annotations

from .board import START_FEN, Board, initial_pieces
from .coords import (
    FILES, HEIGHT, WIDTH, crossed_river, home_side, in_board, in_palace,
    parse_square, square,
)
from .pieces import (
    ADVISOR, BLACK, CANNON, CHARIOT, COLORS, ELEPHANT, GENERAL, HORSE, RED,
    SOLDIER, Piece, normalize_piece_id,
)

__version__ = "0.1.0"

__all__ = [
    "START_FEN", "Board", "initial_pieces", "FILES", "HEIGHT", "WIDTH",
    "crossed_river", "home_side", "in_board", "in_palace", "parse_square",
    "square", "ADVISOR", "BLACK", "CANNON", "CHARIOT", "COLORS", "ELEPHANT",
    "GENERAL", "HORSE", "RED", "SOLDIER", "Piece", "normalize_piece_id",
    "__version__",
]
