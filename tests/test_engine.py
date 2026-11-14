import unittest

from xiangqi_duel.engine import choose_move, evaluate
from xiangqi_duel.game import Game
from xiangqi_duel.pieces import RED


class EngineTest(unittest.TestCase):
    def test_returns_legal_move(self):
        game = Game()
        move = choose_move(game, depth=1, time_limit=5)
        self.assertIsNotNone(move)
        legal = {(m.piece_id, m.to_str) for m in game.legal_moves()}
        self.assertIn((move.piece_id, move.to_str), legal)

    def test_captures_free_horse(self):
        game = Game("4k4/9/9/9/9/9/9/R8/9/n2K5 w - - 0 1")
        move = choose_move(game, depth=2, time_limit=10, seed=1)
        self.assertEqual(move.to_str, "a0")
        self.assertEqual(move.piece_id, "red_chariot_1")

    def test_evaluation_is_symmetric(self):
        game = Game()
        self.assertEqual(evaluate(game.board, RED), -evaluate(game.board, "black"))

    def test_no_move_when_finished(self):
        game = Game("R3k4/9/9/9/9/9/9/9/9/3KR4 b - - 0 1")
        self.assertIsNone(choose_move(game, depth=1))
