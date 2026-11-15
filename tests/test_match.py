import time
import unittest

from xiangqi_duel.arena import Match, PlayerSpec


def wait_for(predicate, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class MatchTest(unittest.TestCase):
    def test_engine_vs_engine(self):
        match = Match(
            PlayerSpec(kind="engine", depth=1),
            PlayerSpec(kind="engine", depth=1),
            max_plies=12,
        )
        match.start(block=True)
        self.assertEqual(match.game.status, "finished")
        self.assertGreater(len(match.game.history), 0)
        self.assertTrue(match.trace)
        self.assertEqual(match.mode, "aivai")
        snapshot = match.snapshot()
        self.assertEqual(snapshot["mode"], "aivai")
        self.assertTrue(snapshot["trace"])

    def test_human_mode_hides_trace(self):
        match = Match(
            PlayerSpec(kind="human"),
            PlayerSpec(kind="engine", depth=1),
            human_side="red",
            max_plies=20,
        )
        try:
            match.start()
            self.assertTrue(
                wait_for(lambda: match.snapshot()["turn"] == "red"
                         and match.snapshot()["status"] == "playing")
            )
            snapshot = match.snapshot()
            self.assertEqual(snapshot["mode"], "human")
            self.assertEqual(snapshot["trace"], [])
            self.assertTrue(snapshot["trace_hidden"])
            self.assertIn("red_horse_1", snapshot["legal"])

            match.say("你好，请多指教")
            self.assertTrue(match.chat)
            self.assertEqual(match.players["black"].inbox.qsize(), 1)

            match.submit_human_move("red_horse_1", "c2")
            self.assertTrue(wait_for(lambda: len(match.game.history) >= 2))
            self.assertEqual(match.game.history[0].notation, "马八进七")
            self.assertEqual(match.game.history[0].side, "red")
        finally:
            match.stop()
        self.assertEqual(match.snapshot()["status"], "finished")

    def test_rejects_move_out_of_turn(self):
        from xiangqi_duel.game import IllegalMove

        match = Match(
            PlayerSpec(kind="human"),
            PlayerSpec(kind="engine", depth=1),
            human_side="red",
            max_plies=10,
        )
        match.game.turn = "black"
        with self.assertRaises(IllegalMove):
            match.submit_human_move("red_horse_1", "c2")
        match.game.turn = "red"
        match.submit_human_move("red_horse_1", "c2")
        self.assertEqual(match.human_queue.qsize(), 1)

    def test_aivai_has_no_human_moves(self):
        from xiangqi_duel.game import IllegalMove

        match = Match(
            PlayerSpec(kind="engine", depth=1),
            PlayerSpec(kind="engine", depth=1),
            max_plies=4,
        )
        with self.assertRaises(IllegalMove):
            match.submit_human_move("red_horse_1", "c2")

    def test_chat_has_ply(self):
        match = Match(
            PlayerSpec(kind="human"),
            PlayerSpec(kind="engine", depth=1),
            human_side="red",
            max_plies=10,
        )
        try:
            match.start()
            wait_for(lambda: match.game.status == "playing")
            match.say("你好")
            self.assertEqual(match.chat[-1]["ply"], 1)
        finally:
            match.stop()

    def test_human_resign_reason(self):
        match = Match(
            PlayerSpec(kind="human"),
            PlayerSpec(kind="engine", depth=1),
            human_side="red",
            max_plies=10,
        )
        try:
            match.start()
            wait_for(lambda: match.game.status == "playing")
            match.resign("red", "实在下不动了")
            self.assertEqual(match.game.result["code"], "resign")
            self.assertIn("实在下不动了", match.game.result["reason"])
        finally:
            match.stop()

    def test_free_mode_moves_both_sides(self):
        match = Match(
            PlayerSpec(kind="human"),
            PlayerSpec(kind="human"),
            free=True,
            max_plies=300,
        )
        match.start()
        snap = match.snapshot()
        self.assertEqual(snap["mode"], "free")
        self.assertIn("red_horse_1", snap["legal"])
        self.assertIn("black_horse_1", snap["legal"])
        match.free_move("red_horse_1", "c2")
        match.free_move("black_horse_1", "c7")
        self.assertEqual(len(match.game.history), 2)
        self.assertEqual(match.game.status, "playing")
        match.stop()

    def test_free_mode_checkmate_ends(self):
        fen = "4k4/9/2N3N2/9/9/9/9/9/9/KR7 w - - 0 1"
        match = Match(
            PlayerSpec(kind="human"),
            PlayerSpec(kind="human"),
            free=True,
            fen=fen,
        )
        match.start()
        match.free_move("red_chariot_1", "b9")
        self.assertEqual(match.game.result["code"], "checkmate")
        self.assertEqual(match.snapshot()["status"], "finished")
        match.stop()

    def test_aivai_allows_spectator_chat(self):
        match = Match(
            PlayerSpec(kind="engine", depth=1),
            PlayerSpec(kind="engine", depth=1),
            max_plies=4,
        )
        match.start(block=True)
        match.say("观众提醒：可以考虑兑子")
        self.assertEqual(match.chat[-1]["text"], "观众提醒：可以考虑兑子")
        self.assertEqual(match.chat[-1]["side"], "user")
