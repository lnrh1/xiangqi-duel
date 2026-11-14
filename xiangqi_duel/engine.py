"""A small alpha-beta engine used as an offline baseline and opponent.

It is deliberately simple: material plus a few positional bonuses, fixed
depth, no quiescence search.  Good enough to finish games and to let the
whole pipeline run without any API key.
"""
from __future__ import annotations

import random
import time

from .coords import crossed_river
from .moves import legal_moves, other
from .pieces import (
    ADVISOR, CANNON, CHARIOT, ELEPHANT, GENERAL, HORSE, SOLDIER,
)

PIECE_VALUE = {
    CHARIOT: 900,
    CANNON: 450,
    HORSE: 400,
    ADVISOR: 200,
    ELEPHANT: 200,
    SOLDIER: 100,
    GENERAL: 100000,
}
CROSSED_SOLDIER_BONUS = 100
MATE = 300000


def evaluate(board, color):
    """Static evaluation from the point of view of color."""
    if board.general(other(color)) is None:
        return MATE
    if board.general(color) is None:
        return -MATE
    score = 0
    for piece in board.pieces.values():
        value = PIECE_VALUE[piece.type]
        if piece.type == SOLDIER and crossed_river(piece.color, piece.y):
            value += CROSSED_SOLDIER_BONUS
        if piece.type in (CHARIOT, CANNON):
            value += (4 - abs(piece.x - 4)) * 2
        score += value if piece.color == color else -value
    return score


def _order(board, moves):
    def score(move):
        target_id = board.occ.get(move.to)
        if not target_id:
            return 0
        target = board.pieces[target_id]
        attacker = board.pieces[move.piece_id]
        return 10 * PIECE_VALUE[target.type] - PIECE_VALUE[attacker.type]

    return sorted(moves, key=score, reverse=True)


def _search(board, color, depth, alpha, beta, deadline):
    if depth <= 0:
        return evaluate(board, color)
    moves = _order(board, legal_moves(board, color))
    if not moves:
        return -MATE + 1000 * (10 - depth)
    best = -MATE * 2
    for move in moves:
        undo = board.make(move)
        score = -_search(board, other(color), depth - 1, -beta, -alpha, deadline)
        board.unmake(undo)
        if score > best:
            best = score
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
        if time.monotonic() > deadline:
            break
    return best


def choose_move(game, depth=3, time_limit=5.0, seed=None):
    """Pick a move for the side to move, or None when there is no move."""
    board = game.board
    color = game.turn
    moves = _order(board, legal_moves(board, color))
    if not moves:
        return None
    deadline = time.monotonic() + max(0.2, time_limit)
    best_score = -MATE * 2
    best = []
    alpha, beta = -MATE * 2, MATE * 2
    for move in moves:
        undo = board.make(move)
        score = -_search(board, other(color), depth - 1, -beta, -alpha, deadline)
        board.unmake(undo)
        if score > best_score:
            best_score = score
            best = [move]
        elif score == best_score:
            best.append(move)
        if best_score > alpha:
            alpha = best_score
        if time.monotonic() > deadline:
            break
    rng = random.Random(seed)
    return rng.choice(best)
