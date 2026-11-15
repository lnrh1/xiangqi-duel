import unittest

from xiangqi_duel.agent import LLMPlayer
from xiangqi_duel.game import Game
from xiangqi_duel.llm import ChatResult, ProviderConfig, ToolCall


class FakeClient:
    kind = "fake"

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def chat(self, system, messages, tools=None):
        self.calls.append(
            {
                "system": system,
                "messages": [dict(message) for message in messages],
                "tools": tools,
            }
        )
        if not self.results:
            return ChatResult(text="没有更多脚本了")
        return self.results.pop(0)


def config():
    return ProviderConfig(provider="deepseek", model="fake-model")


class LLMPlayerTest(unittest.TestCase):
    def test_full_turn(self):
        client = FakeClient(
            [
                ChatResult(text="先看看红马的走法。"),
                ChatResult(
                    tool_calls=[ToolCall("c1", "list_legal_moves", {"piece_id": "red_horse_1"})]
                ),
                ChatResult(
                    text="走马八进七。",
                    tool_calls=[ToolCall("c2", "move", {"piece_id": "red_horse_1", "to": "c2"})],
                ),
            ]
        )
        player = LLMPlayer("red", client, config())
        decision = player.choose(Game())
        self.assertEqual(decision.piece_id, "red_horse_1")
        self.assertEqual(decision.to, "c2")
        self.assertEqual(decision.steps, 3)
        self.assertIn("马八进七", decision.comment)
        tool_messages = [
            message for message in client.calls[-1]["messages"] if message.get("role") == "tool"
        ]
        self.assertTrue(tool_messages)
        self.assertTrue(any("red_horse_1" in m["content"] for m in tool_messages))

    def test_invalid_then_valid(self):
        client = FakeClient(
            [
                ChatResult(
                    tool_calls=[ToolCall("c1", "move", {"piece_id": "red_horse_1", "to": "e2"})]
                ),
                ChatResult(
                    text="重来。",
                    tool_calls=[ToolCall("c2", "move", {"piece_id": "red_horse_1", "to": "c2"})],
                ),
            ]
        )
        player = LLMPlayer("red", client, config())
        decision = player.choose(Game())
        self.assertEqual(decision.to, "c2")
        tool_messages = [
            message for message in client.calls[-1]["messages"] if message.get("role") == "tool"
        ]
        self.assertTrue(any('"ok": false' in message["content"] for message in tool_messages))

    def test_send_message_collected(self):
        client = FakeClient(
            [
                ChatResult(
                    tool_calls=[ToolCall("c1", "send_message", {"text": "承让了"})],
                ),
                ChatResult(
                    tool_calls=[ToolCall("c2", "move", {"piece_id": "red_horse_1", "to": "c2"})],
                ),
            ]
        )
        player = LLMPlayer("red", client, config())
        decision = player.choose(Game())
        self.assertEqual(decision.messages, ["承让了"])

    def test_cached_tokens_accumulate(self):
        client = FakeClient(
            [
                ChatResult(
                    text="走马八进七。",
                    tool_calls=[ToolCall("c1", "move", {"piece_id": "red_horse_1", "to": "c2"})],
                    usage={"input": 120, "output": 8, "total": 128, "cached": 90},
                )
            ]
        )
        player = LLMPlayer("red", client, config())
        decision = player.choose(Game())
        self.assertEqual(decision.usage["cached"], 90)
        self.assertEqual(decision.context_tokens, 120)

    def test_no_move_aborts(self):
        client = FakeClient([ChatResult(text="嗯…"), ChatResult(text="嗯…")])
        player = LLMPlayer("red", client, config(), max_steps=2)
        decision = player.choose(Game())
        self.assertTrue(decision.resign)
        self.assertIn("step limit", decision.resign_reason)

    def test_context_persists_between_turns(self):
        client = FakeClient(
            [
                ChatResult(tool_calls=[ToolCall("c1", "move", {"piece_id": "red_horse_1", "to": "c2"})]),
                ChatResult(tool_calls=[ToolCall("c2", "move", {"piece_id": "red_chariot_1", "to": "a1"})]),
            ]
        )
        player = LLMPlayer("red", client, config())
        game = Game()
        first = player.choose(game)
        game.play(first.piece_id, first.to)
        game.play("black_horse_1", "c7")
        second = player.choose(game)
        self.assertEqual(second.piece_id, "red_chariot_1")
        self.assertGreater(len(client.calls[1]["messages"]), len(client.calls[0]["messages"]))
        joined = " ".join(m.get("content") or "" for m in client.calls[1]["messages"])
        self.assertIn("第 1 回合", joined)

    def test_inbox_messages_reach_prompt(self):
        client = FakeClient(
            [ChatResult(tool_calls=[ToolCall("c1", "move", {"piece_id": "red_horse_1", "to": "c2"})])]
        )
        player = LLMPlayer("red", client, config())
        player.inbox.put({"from": "opponent", "text": "你这步棋有点意思"})
        player.choose(Game())
        joined = " ".join(m.get("content") or "" for m in client.calls[0]["messages"])
        self.assertIn("对手给你留言", joined)

    def test_two_players_have_independent_context(self):
        client_red = FakeClient(
            [ChatResult(tool_calls=[ToolCall("r1", "move", {"piece_id": "red_horse_1", "to": "c2"})])]
        )
        client_black = FakeClient(
            [ChatResult(tool_calls=[ToolCall("b1", "move", {"piece_id": "black_horse_1", "to": "c7"})])]
        )
        red = LLMPlayer("red", client_red, config())
        black = LLMPlayer("black", client_black, config())
        game = Game()
        first = red.choose(game)
        game.play(first.piece_id, first.to)
        black.choose(game)
        red_text = " ".join(m.get("content") or "" for m in client_red.calls[0]["messages"])
        black_text = " ".join(m.get("content") or "" for m in client_black.calls[0]["messages"])
        self.assertIn("红方", red_text)
        self.assertIn("黑方", black_text)
        self.assertEqual(len(red.blocks), 1)
        self.assertEqual(len(black.blocks), 1)

class ResignTest(unittest.TestCase):
    def test_resign_reason_kept(self):
        client = FakeClient(
            [
                ChatResult(
                    text="局面太差，投了",
                    tool_calls=[ToolCall("c1", "resign", {"reason": "车马炮全丢，认输"})],
                )
            ]
        )
        player = LLMPlayer("red", client, config())
        decision = player.choose(Game())
        self.assertTrue(decision.resign)
        self.assertIn("车马炮全丢", decision.resign_reason)

