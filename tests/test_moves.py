import unittest

from xiangqi_duel.board import Board
from xiangqi_duel.moves import (
    generals_face, in_check, legal_moves, perft, pseudo_targets,
)
from xiangqi_duel.pieces import BLACK, RED


def board_from(fen):
    board, turn, _, _ = Board.from_fen(fen)
    return board


def targets(board, piece_id):
    piece = board.pieces[piece_id]
    return {("%s%d" % ("abcdefghi"[x], y)) for x, y in pseudo_targets(board, piece)}


class PerftTest(unittest.TestCase):
    def test_initial_move_count(self):
        self.assertEqual(len(legal_moves(Board.initial(), RED)), 44)

    def test_perft_depth_2(self):
        self.assertEqual(perft(Board.initial(), RED, 2), 1920)

    def test_perft_depth_3(self):
        self.assertEqual(perft(Board.initial(), RED, 3), 79666)


class PieceRuleTest(unittest.TestCase):
    def test_cannon_needs_one_screen(self):
        board = board_from("4k4/9/4n4/9/4p4/9/9/4C4/9/4K4 w - - 0 1")
        moves = targets(board, "red_cannon_1")
        self.assertIn("e7", moves)
        self.assertIn("e3", moves)
        self.assertNotIn("e5", moves)
        self.assertNotIn("e9", moves)

    def test_horse_leg_blocked(self):
        blocked = board_from("4k4/9/9/9/9/9/9/9/1p7/1N2K4 w - - 0 1")
        self.assertEqual(targets(blocked, "red_horse_1"), {"d1"})

    def test_horse_open(self):
        board = Board.initial()
        self.assertEqual(targets(board, "red_horse_1"), {"a2", "c2"})

    def test_elephant_stays_home(self):
        board = board_from("4k4/9/9/9/9/2B6/9/9/9/3K5 w - - 0 1")
        self.assertEqual(targets(board, "red_elephant_1"), {"a2", "e2"})

    def test_advisor_in_palace(self):
        board = board_from("4k4/9/9/9/9/9/9/9/9/3KA4 w - - 0 1")
        self.assertEqual(targets(board, "red_advisor_1"), {"d1", "f1"})

    def test_soldier_before_and_after_river(self):
        before = Board.initial()
        self.assertEqual(targets(before, "red_soldier_1"), {"a4"})
        after = board_from("4k4/9/9/9/P8/9/9/9/9/3K5 w - - 0 1")
        self.assertEqual(targets(after, "red_soldier_1"), {"a6", "b5"})

    def test_generals_cannot_face(self):
        board = board_from("4k4/9/9/9/9/9/9/9/4R4/4K4 w - - 0 1")
        self.assertFalse(generals_face(board))
        self.assertTrue(in_check(board, BLACK))
        chariot_moves = {m.to_str for m in legal_moves(board, RED, "red_chariot_1")}
        self.assertIn("e2", chariot_moves)
        self.assertNotIn("a1", chariot_moves)

    def test_flying_general_is_check(self):
        board = board_from("4k4/9/9/9/9/9/9/9/9/4K4 w - - 0 1")
        self.assertTrue(generals_face(board))
        self.assertTrue(in_check(board, RED))
        self.assertTrue(in_check(board, BLACK))


class LegalMoveTest(unittest.TestCase):
    def test_pinned_piece_cannot_move(self):
        # red chariot on e1 shields the general from the black chariot on e9
        board = board_from("4r4/9/9/9/9/9/9/9/4R4/4K4 w - - 0 1")
        moves = {m.to_str for m in legal_moves(board, RED, "red_chariot_1")}
        self.assertNotIn("a1", moves)
        self.assertIn("e2", moves)

    def test_opponent_piece_has_no_moves(self):
        board = Board.initial()
        self.assertEqual(legal_moves(board, RED, "black_horse_1"), [])
