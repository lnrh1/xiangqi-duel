"""Legal move generation and attack detection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .coords import crossed_river, in_board, in_palace, square
from .pieces import (
    ADVISOR, BLACK, CANNON, CHARIOT, ELEPHANT, GENERAL, HORSE, RED, SOLDIER,
)

DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAGONALS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
_HORSE_STEPS = (
    (1, 2), (2, 1), (2, -1), (1, -2),
    (-1, -2), (-2, -1), (-2, 1), (-1, 2),
)


def other(color):
    return BLACK if color == RED else RED


@dataclass(frozen=True)
class Move:
    piece_id: str
    frm: tuple
    to: tuple
    capture_id: Optional[str] = None

    @property
    def ucci(self):
        return square(*self.frm) + square(*self.to)

    @property
    def from_square(self):
        return square(*self.frm)

    @property
    def to_square(self):
        return square(*self.to)

    @property
    def to_str(self):
        return square(*self.to)


# ---------------------------------------------------------------- generation
def _chariot_targets(board, piece):
    targets = []
    for dx, dy in DIRS:
        x, y = piece.x + dx, piece.y + dy
        while in_board(x, y):
            target = board.piece_at(x, y)
            if target is None:
                targets.append((x, y))
            else:
                if target.color != piece.color:
                    targets.append((x, y))
                break
            x += dx
            y += dy
    return targets


def _cannon_targets(board, piece):
    targets = []
    for dx, dy in DIRS:
        x, y = piece.x + dx, piece.y + dy
        screened = False
        while in_board(x, y):
            target = board.piece_at(x, y)
            if not screened:
                if target is None:
                    targets.append((x, y))
                else:
                    screened = True
            elif target is not None:
                if target.color != piece.color:
                    targets.append((x, y))
                break
            x += dx
            y += dy
    return targets


def _horse_targets(board, piece):
    targets = []
    for dx, dy in _HORSE_STEPS:
        x, y = piece.x + dx, piece.y + dy
        if not in_board(x, y):
            continue
        if abs(dx) == 2:
            leg = (piece.x + dx // 2, piece.y)
        else:
            leg = (piece.x, piece.y + dy // 2)
        if leg in board.occ:
            continue
        target = board.piece_at(x, y)
        if target is None or target.color != piece.color:
            targets.append((x, y))
    return targets


def _elephant_targets(board, piece):
    targets = []
    for dx, dy in DIAGONALS:
        x, y = piece.x + 2 * dx, piece.y + 2 * dy
        if not in_board(x, y):
            continue
        if crossed_river(piece.color, y):
            continue  # elephants may never cross the river
        if (piece.x + dx, piece.y + dy) in board.occ:
            continue  # blocked eye
        target = board.piece_at(x, y)
        if target is None or target.color != piece.color:
            targets.append((x, y))
    return targets


def _advisor_targets(board, piece):
    targets = []
    for dx, dy in DIAGONALS:
        x, y = piece.x + dx, piece.y + dy
        if not in_palace(piece.color, x, y):
            continue
        target = board.piece_at(x, y)
        if target is None or target.color != piece.color:
            targets.append((x, y))
    return targets


def _general_targets(board, piece):
    targets = []
    for dx, dy in DIRS:
        x, y = piece.x + dx, piece.y + dy
        if not in_palace(piece.color, x, y):
            continue
        target = board.piece_at(x, y)
        if target is None or target.color != piece.color:
            targets.append((x, y))
    return targets


def _soldier_targets(board, piece):
    targets = []
    forward = 1 if piece.color == RED else -1
    y = piece.y + forward
    if in_board(piece.x, y):
        target = board.piece_at(piece.x, y)
        if target is None or target.color != piece.color:
            targets.append((piece.x, y))
    if crossed_river(piece.color, piece.y):
        for dx in (-1, 1):
            x = piece.x + dx
            if not in_board(x, piece.y):
                continue
            target = board.piece_at(x, piece.y)
            if target is None or target.color != piece.color:
                targets.append((x, piece.y))
    return targets


_TARGET_FUNCS = {
    CHARIOT: _chariot_targets,
    CANNON: _cannon_targets,
    HORSE: _horse_targets,
    ELEPHANT: _elephant_targets,
    ADVISOR: _advisor_targets,
    GENERAL: _general_targets,
    SOLDIER: _soldier_targets,
}


def pseudo_targets(board, piece):
    """Squares the piece could reach ignoring king safety."""
    return _TARGET_FUNCS[piece.type](board, piece)


# ------------------------------------------------------------------- attacks
def is_attacked(board, x, y, color):
    """True when 'color' attacks the square (x, y)."""
    occ = board.occ
    pieces = board.pieces

    # soldiers: forward attack, plus sideways attacks across the river
    forward = 1 if color == RED else -1
    soldier_at = occ.get((x, y - forward))
    if soldier_at:
        piece = pieces[soldier_at]
        if piece.color == color and piece.type == SOLDIER:
            return True
    if crossed_river(color, y):
        for dx in (-1, 1):
            soldier_at = occ.get((x + dx, y))
            if soldier_at:
                piece = pieces[soldier_at]
                if piece.color == color and piece.type == SOLDIER:
                    return True

    # horses (with the leg rule)
    for dx, dy in _HORSE_STEPS:
        hx, hy = x - dx, y - dy
        if not in_board(hx, hy):
            continue
        piece_id = occ.get((hx, hy))
        if not piece_id:
            continue
        piece = pieces[piece_id]
        if piece.color != color or piece.type != HORSE:
            continue
        if abs(dx) == 2:
            leg = (hx + dx // 2, hy)
        else:
            leg = (hx, hy + dy // 2)
        if leg not in occ:
            return True

    # generals (adjacent squares only)
    for dx, dy in DIRS:
        piece_id = occ.get((x + dx, y + dy))
        if piece_id:
            piece = pieces[piece_id]
            if piece.color == color and piece.type == GENERAL:
                return True

    # chariots and cannons along the four rays
    for dx, dy in DIRS:
        sx, sy = x + dx, y + dy
        screened = False
        while in_board(sx, sy):
            piece_id = occ.get((sx, sy))
            if piece_id:
                piece = pieces[piece_id]
                if not screened:
                    if piece.color == color and piece.type == CHARIOT:
                        return True
                    screened = True
                else:
                    if piece.color == color and piece.type == CANNON:
                        return True
                    break
            sx += dx
            sy += dy
    return False


def generals_face(board):
    """True when the two generals see each other down an open file."""
    red = board.general(RED)
    black = board.general(BLACK)
    if red is None or black is None or red.x != black.x:
        return False
    for y in range(min(red.y, black.y) + 1, max(red.y, black.y)):
        if (red.x, y) in board.occ:
            return False
    return True


def in_check(board, color):
    general = board.pieces.get(color + "_general") or board.general(color)
    if general is None:
        return False
    if generals_face(board):
        return True
    return is_attacked(board, general.x, general.y, other(color))


# ------------------------------------------------------------------ legality
def legal_moves(board, color, piece_id=None):
    """All legal moves for 'color' (optionally only one piece)."""
    if piece_id is not None:
        piece = board.pieces.get(piece_id)
        if piece is None or piece.color != color:
            return []
        pieces = [piece]
    else:
        pieces = [p for p in board.pieces.values() if p.color == color]

    moves = []
    for piece in pieces:
        for tx, ty in pseudo_targets(board, piece):
            move = Move(piece.id, (piece.x, piece.y), (tx, ty), board.occ.get((tx, ty)))
            undo = board.make(move)
            if not in_check(board, color):
                moves.append(move)
            board.unmake(undo)
    return moves


def has_legal_move(board, color):
    for piece in [p for p in board.pieces.values() if p.color == color]:
        for tx, ty in pseudo_targets(board, piece):
            move = Move(piece.id, (piece.x, piece.y), (tx, ty), board.occ.get((tx, ty)))
            undo = board.make(move)
            legal = not in_check(board, color)
            board.unmake(undo)
            if legal:
                return True
    return False


def perft(board, color, depth):
    """Count leaf nodes of the legal move tree (a rules regression test)."""
    if depth == 0:
        return 1
    total = 0
    for move in legal_moves(board, color):
        undo = board.make(move)
        total += perft(board, other(color), depth - 1)
        board.unmake(undo)
    return total
