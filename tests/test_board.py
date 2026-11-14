import unittest

from xiangqi_duel.board import START_FEN, Board
from xiangqi_duel.coords import parse_square, square
from xiangqi_duel.pieces import BLACK, RED, normalize_piece_id


class BoardTest(unittest.TestCase):
    def test_initial_fen(self):
        board = Board.initial()
        self.assertEqual(board.to_fen(), START_FEN)
        self.assertEqual(len(board.pieces), 32)

    def test_piece_ids(self):
        board = Board.initial()
        self.assertEqual(board.piece_at(0, 0).id, "red_chariot_1")
        self.assertEqual(board.piece_at(8, 0).id, "red_chariot_2")
        self.assertEqual(board.piece_at(1, 9).id, "black_horse_1")
        self.assertEqual(board.piece_at(7, 9).id, "black_horse_2")
        self.assertEqual(board.piece_at(4, 0).id, "red_general")
        self.assertEqual(board.piece_at(0, 3).id, "red_soldier_1")
        self.assertEqual(board.piece_at(8, 6).id, "black_soldier_5")

    def test_fen_roundtrip(self):
        board = Board.initial()
        again, turn, halfmove, fullmove = Board.from_fen(board.to_fen())
        self.assertEqual(again.to_fen(), board.to_fen())
        self.assertEqual(turn, RED)
        self.assertEqual((halfmove, fullmove), (0, 1))

    def test_ascii_has_all_files(self):
        text = Board.initial().ascii()
        for letter in "abcdefghi":
            self.assertIn(letter, text)
        self.assertEqual(len(text.splitlines()), 11)

    def test_square_helpers(self):
        self.assertEqual(square(7, 2), "h2")
        self.assertEqual(parse_square("h2"), (7, 2))
        self.assertEqual(parse_square("H2"), (7, 2))
        self.assertEqual(square(*parse_square("a0")), "a0")
        with self.assertRaises(ValueError):
            parse_square("z9")

    def test_normalize_piece_id(self):
        cases = {
            "red_horse_1": "red_horse_1",
            "redhorse1": "red_horse_1",
            "红马1": "red_horse_1",
            "red-horse-1": "red_horse_1",
            "blackcannon2": "black_cannon_2",
            "黑炮二": "black_cannon_2",
            "红帅": "red_general",
            "black_general": "black_general",
        }
        for raw, expected in cases.items():
            self.assertEqual(normalize_piece_id(raw), expected, raw)
        self.assertEqual(normalize_piece_id("horse_1", "red"), "red_horse_1")
        with self.assertRaises(ValueError):
            normalize_piece_id("dragon_1")

    def test_clone_is_independent(self):
        board = Board.initial()
        copy = board.clone()
        copy.occ[(4, 1)] = "red_general"
        self.assertNotIn((4, 1), board.occ)


class CoordsTest(unittest.TestCase):
    def test_crossed_river(self):
        self.assertFalse(__import__("xiangqi_duel.coords", fromlist=["crossed_river"]).crossed_river(RED, 4))
        self.assertTrue(__import__("xiangqi_duel.coords", fromlist=["crossed_river"]).crossed_river(RED, 5))
        self.assertTrue(__import__("xiangqi_duel.coords", fromlist=["crossed_river"]).crossed_river(BLACK, 4))
        self.assertFalse(__import__("xiangqi_duel.coords", fromlist=["crossed_river"]).crossed_river(BLACK, 5))
