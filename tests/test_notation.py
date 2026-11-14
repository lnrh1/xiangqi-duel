import unittest

from xiangqi_duel.board import Board
from xiangqi_duel.game import Game
from xiangqi_duel.moves import Move
from xiangqi_duel.notation import move_text


class NotationTest(unittest.TestCase):
    def test_red_opening_moves(self):
        game = Game()
        record = game.play("red_cannon_1", "e2")
        self.assertEqual(record.notation, "炮八平五")
        record = game.play("black_horse_1", "c7")
        self.assertEqual(record.notation, "马二进三")

    def test_horse_and_chariot(self):
        game = Game()
        record = game.play("red_horse_1", "c2")
        self.assertEqual(record.notation, "马八进七")
        game2 = Game()
        game2.play("red_horse_2", "i2")
        game2.play("black_horse_1", "c7")
        record = game2.play("red_chariot_2", "h0")
        self.assertEqual(record.notation, "车一平二")

    def test_front_and_back_disambiguation(self):
        board, _, _, _ = Board.from_fen("4k4/9/9/9/9/9/9/9/R8/R3K4 w - - 0 1")
        front = Move("red_chariot_1", (0, 1), (1, 1))
        back = Move("red_chariot_2", (0, 0), (1, 0))
        self.assertEqual(move_text(board, front, "red"), "前车平八")
        self.assertEqual(move_text(board, back, "red"), "后车平八")

    def test_target_file_numbering(self):
        game = Game()
        game.play("red_soldier_1", "a4")
        record = game.play("black_soldier_1", "a5")
        self.assertEqual(record.side, "black")
        self.assertIn("进", record.notation)
