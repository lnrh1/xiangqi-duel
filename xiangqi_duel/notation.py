"""Chinese move notation (炮二平五, 马八进七, ...)."""
from __future__ import annotations

from .pieces import (
    ADVISOR, CHARIOT, ELEPHANT, HORSE, NAME_ZH, RED, SOLDIER,
)

CN_NUM = "一二三四五六七八九"
MOVE_NUMERALS = ("前", "二", "三", "四", "后")


def file_number(color, x):
    """File number in that side's counting (red counts 1 from file i)."""
    return 9 - x if color == RED else x + 1


def move_text(board, move, color):
    """Chinese notation for a move played by 'color'.

    'board' must be the position before the move.
    """
    piece = board.pieces[move.piece_id]
    name = NAME_ZH[color][piece.type]
    fx, fy = move.frm
    tx, ty = move.to

    same_file = [
        p for p in board.pieces.values()
        if p.color == color and p.type == piece.type and p.x == fx
    ]
    if len(same_file) > 1:
        ordered = sorted(same_file, key=lambda p: p.y, reverse=(color == RED))
        ids = [p.id for p in ordered]
        index = ids.index(piece.id)
        if len(ids) == 2:
            prefix = "前" if index == 0 else "后"
        elif len(ids) == 3:
            prefix = ("前", "中", "后")[index]
        else:
            prefix = MOVE_NUMERALS[min(index, len(MOVE_NUMERALS) - 1)]
        head = prefix + name
    else:
        head = name + CN_NUM[file_number(color, fx) - 1]

    if ty == fy:
        return head + "平" + CN_NUM[file_number(color, tx) - 1]

    forward = (ty > fy) if color == RED else (ty < fy)
    action = "进" if forward else "退"
    if piece.type in (HORSE, ELEPHANT, ADVISOR):
        return head + action + CN_NUM[file_number(color, tx) - 1]
    return head + action + CN_NUM[abs(ty - fy) - 1]
