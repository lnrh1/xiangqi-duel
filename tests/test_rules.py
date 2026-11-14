import unittest

from xiangqi_duel.game import Game, IllegalMove
from xiangqi_duel.pieces import BLACK, RED

CHECKMATE = "R3k4/9/9/9/9/9/9/9/9/3KR4 b - - 0 1"
STALEMATE = "4k4/3R1R3/9/9/9/9/9/9/9/3K5 b - - 0 1"
SHUFFLE = "4k4/1r7/9/9/9/9/9/9/9/3K1R3 w - - 0 1"


class CheckmateTest(unittest.TestCase):
    def test_checkmate(self):
        game = Game(CHECKMATE)
        self.assertEqual(game.status, "finished")
        self.assertEqual(game.result["winner"], RED)
        self.assertEqual(game.result["reason"], "checkmate")

    def test_stalemate_loses(self):
        game = Game(STALEMATE)
        self.assertEqual(game.status, "finished")
        self.assertEqual(game.result["winner"], RED)
        self.assertEqual(game.result["reason"], "stalemate")

    def test_resign(self):
        game = Game()
        game.resign(BLACK, "认输")
        self.assertEqual(game.result["winner"], RED)
        self.assertIn("认输", game.result["reason"])


class RepetitionTest(unittest.TestCase):
    def test_threefold_repetition_is_draw(self):
        game = Game(SHUFFLE)
        script = [
            ("red_chariot_1", "f1"), ("black_chariot_1", "b7"),
            ("red_chariot_1", "f0"), ("black_chariot_1", "b8"),
            ("red_chariot_1", "f1"), ("black_chariot_1", "b7"),
            ("red_chariot_1", "f0"), ("black_chariot_1", "b8"),
        ]
        for piece_id, to in script:
            if game.status != "playing":
                break
            game.play(piece_id, to)
        self.assertEqual(game.status, "finished")
        self.assertEqual(game.result["winner"], None)
        self.assertEqual(game.result["reason"], "threefold repetition")

    def test_sixty_move_rule(self):
        game = Game("4k4/1r7/9/9/9/9/9/9/9/3K1R3 w - - 119 60")
        game.play("red_chariot_1", "f1")
        self.assertEqual(game.status, "finished")
        self.assertEqual(game.result["reason"], "sixty-move rule")

    def test_insufficient_material(self):
        game = Game("3ka4/9/9/9/9/9/9/9/9/3KA4 w - - 0 1")
        self.assertEqual(game.status, "finished")
        self.assertEqual(game.result["winner"], None)
        self.assertEqual(game.result["reason"], "insufficient material")


class PlayTest(unittest.TestCase):
    def test_opening_move_and_history(self):
        game = Game()
        record = game.play("red_cannon_1", "e2")
        self.assertEqual(record.notation, "炮八平五")
        self.assertEqual(record.ucci, "b2e2")
        self.assertEqual(game.turn, BLACK)
        self.assertEqual(len(game.history), 1)
        self.assertEqual(record.ply, 1)

    def test_illegal_moves(self):
        game = Game()
        with self.assertRaises(IllegalMove):
            game.play("red_horse_1", "e2")
        with self.assertRaises(IllegalMove):
            game.play("black_horse_1", "c7")
        with self.assertRaises(IllegalMove):
            game.play("red_dragon_1", "e2")

    def test_snapshot_shape(self):
        game = Game()
        game.play("red_horse_1", "c2")
        snap = game.snapshot()
        self.assertEqual(snap["turn"], BLACK)
        self.assertEqual(snap["status"], "playing")
        self.assertEqual(len(snap["pieces"]), 32)
        self.assertEqual(snap["ply"], 1)
        self.assertIn("black_soldier_1", snap["legal"])
        self.assertTrue(snap["board"].startswith("   a b c d e f g h i"))

    def test_clone_is_independent(self):
        game = Game()
        copy = game.clone()
        copy.play("red_horse_1", "c2")
        self.assertEqual(len(copy.history), 1)
        self.assertEqual(len(game.history), 0)
        self.assertEqual(game.turn, RED)
