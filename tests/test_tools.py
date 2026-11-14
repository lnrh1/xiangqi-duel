import json
import unittest

from xiangqi_duel.game import Game, IllegalMove
from xiangqi_duel.tools import ToolBox, tool_specs


class ToolSpecTest(unittest.TestCase):
    def test_names(self):
        names = [spec["function"]["name"] for spec in tool_specs()]
        for name in (
            "list_pieces", "get_piece", "list_legal_moves", "move", "get_status",
            "get_history", "send_message", "offer_draw", "note", "resign",
            "list_pieces_in_area", "describe_square",
            "start_simulation", "end_simulation",
        ):
            self.assertIn(name, names)


class ToolBoxTest(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.box = ToolBox(self.game, "red")

    def test_list_legal_moves_for_piece(self):
        result = self.box.call("list_legal_moves", {"piece_id": "red_horse_1"})
        self.assertTrue(result["ok"])
        moves = result["moves"]["red_horse_1"]
        self.assertEqual({m["to"] for m in moves}, {"a2", "c2"})
        self.assertIn("马八进七", [m["notation"] for m in moves])

    def test_list_all_legal_moves(self):
        result = self.box.call("list_legal_moves")
        self.assertTrue(result["ok"])
        self.assertEqual(result["move_count"], 44)

    def test_piece_id_aliases(self):
        result = self.box.call("list_legal_moves", {"piece_id": "红马1"})
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["moves"]), 1)

    def test_move_pending(self):
        result = self.box.call("move", {"piece_id": "red_horse_1", "to": "c2"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["notation"], "马八进七")
        self.assertEqual(self.box.pending, ("red_horse_1", "c2"))
        self.assertEqual(self.game.turn, "red")  # not applied yet

    def test_move_by_from_square(self):
        result = self.box.call("move", {"from": "b0", "to": "c2"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["piece_id"], "red_horse_1")

    def test_illegal_move(self):
        result = self.box.call("move", {"piece_id": "red_horse_1", "to": "e2"})
        self.assertFalse(result["ok"])
        self.assertIn("legal targets", result["error"])

    def test_cannot_move_opponent_piece(self):
        result = self.box.call("move", {"piece_id": "black_horse_1", "to": "c7"})
        self.assertFalse(result["ok"])

    def test_send_message(self):
        result = self.box.call("send_message", {"text": "承让"})
        self.assertTrue(result["ok"])
        self.assertEqual(self.box.outbox, ["承让"])

    def test_send_message_limit(self):
        for index in range(6):
            self.assertTrue(self.box.call("send_message", {"text": "第%d条" % index})["ok"])
        self.assertFalse(self.box.call("send_message", {"text": "超了"})["ok"])

    def test_resign(self):
        result = self.box.call("resign", {"reason": "无路可走"})
        self.assertTrue(result["ok"])
        self.assertEqual(self.game.status, "finished")

    def test_string_arguments(self):
        result = self.box.call("list_legal_moves", json.dumps({"piece_id": "red_horse_1"}))
        self.assertTrue(result["ok"])

    def test_bad_arguments(self):
        self.assertFalse(self.box.call("move", "not json")["ok"])
        self.assertFalse(self.box.call("nope")["ok"])
        self.assertFalse(self.box.call("get_piece", {})["ok"])

    def test_get_history(self):
        self.game.play("red_horse_1", "c2")
        result = self.box.call("get_history", {"last": 5})
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["moves"][0]["notation"], "马八进七")


class CoordinateToolsTest(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.box = ToolBox(self.game, "red")

    def test_list_pieces_has_coordinates(self):
        result = self.box.call("list_pieces", {"color": "red"})
        self.assertTrue(result["ok"])
        horse = [p for p in result["pieces"] if p["id"] == "red_horse_1"][0]
        self.assertEqual(horse["x"], 1)
        self.assertEqual(horse["y"], 0)
        self.assertEqual(horse["square"], "b0")
        self.assertEqual(horse["file"], "b")

    def test_list_pieces_in_area(self):
        result = self.box.call(
            "list_pieces_in_area",
            {"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 3},
        )
        self.assertTrue(result["ok"])
        ids = {p["id"] for p in result["pieces"]}
        self.assertIn("red_chariot_1", ids)
        self.assertIn("red_horse_1", ids)
        self.assertIn("red_cannon_1", ids)
        self.assertIn("red_soldier_1", ids)
        self.assertNotIn("red_cannon_2", ids)
        self.assertNotIn("red_soldier_5", ids)

    def test_list_pieces_in_area_validation(self):
        self.assertFalse(self.box.call("list_pieces_in_area", {"x_min": 5, "x_max": 2})["ok"])
        self.assertFalse(self.box.call("list_pieces_in_area", {"x_min": -1})["ok"])

    def test_describe_square(self):
        result = self.box.call("describe_square", {"square": "h2"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["square"], "h2")
        self.assertEqual(result["piece"]["id"], "red_cannon_2")
        self.assertEqual(result["x"], 7)
        self.assertEqual(result["y"], 2)

    def test_describe_empty_square(self):
        result = self.box.call("describe_square", {"square": "e5"})
        self.assertTrue(result["ok"])
        self.assertIsNone(result["piece"])
        self.assertFalse(result["in_red_palace"])


class SimulationToolTest(unittest.TestCase):
    class Holder:
        sim = None

    def test_simulation_redirect_and_limit(self):
        holder = self.Holder()
        game = Game()
        box = ToolBox(game, "red", player=holder)
        self.assertTrue(box.call("start_simulation")["ok"])
        detail = box.call("list_legal_moves", {"piece_id": "red_horse_1"})["moves"]["red_horse_1"][0]
        self.assertIn("gives_check", detail)
        self.assertIn("capture", detail)
        for index in range(8):
            side = "red" if index % 2 == 0 else "black"
            piece = side + "_horse_1"
            targets = box.call("list_legal_moves", {"piece_id": piece})["moves"][piece]
            result = box.call("move", {"piece_id": piece, "to": targets[0]["to"]})
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["simulated"])
            if index < 7:
                self.assertFalse(result["ended"])
        self.assertIsNone(holder.sim)
        self.assertEqual(game.history, [])

    def test_end_simulation(self):
        holder = self.Holder()
        game = Game()
        box = ToolBox(game, "red", player=holder)
        box.call("start_simulation")
        self.assertTrue(box.call("end_simulation")["ok"])
        self.assertIsNone(holder.sim)
