import unittest

from xiangqi_duel import llm


class AnthropicClientTest(unittest.TestCase):
    def test_messages_payload_and_parsing(self):
        captured = {}

        def fake_request(url, payload, headers, timeout, attempts=3):
            captured["url"] = url
            captured["payload"] = payload
            captured["headers"] = headers
            return {
                "content": [
                    {"type": "text", "text": "好的"},
                    {"type": "tool_use", "id": "t1", "name": "get_board", "input": {}},
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }

        original = llm._request_json
        llm._request_json = fake_request
        try:
            config = llm.ProviderConfig(
                provider="anthropic", model="claude-x", api_key="secret"
            ).resolved()
            client = llm.make_client(config)
            result = client.chat(
                "系统提示",
                [
                    {"role": "user", "content": "你好"},
                    {
                        "role": "assistant",
                        "content": "我看看",
                        "tool_calls": [
                            {"id": "a1", "name": "move", "arguments": {"piece_id": "red_horse_1", "to": "c2"}}
                        ],
                    },
                    {"role": "tool", "tool_call_id": "a1", "name": "move", "content": "{\"ok\": true}"},
                ],
                tools=[{"type": "function", "function": {"name": "get_board", "description": "d", "parameters": {"type": "object"}}}],
            )
        finally:
            llm._request_json = original

        self.assertTrue(captured["url"].endswith("/v1/messages"))
        self.assertEqual(captured["headers"]["x-api-key"], "secret")
        self.assertEqual(captured["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(captured["payload"]["system"], "系统提示")
        self.assertEqual(captured["payload"]["tools"][0]["name"], "get_board")
        self.assertEqual(result.text, "好的")
        self.assertEqual(result.tool_calls[0].name, "get_board")
        self.assertEqual(result.usage["input"], 10)

        messages = captured["payload"]["messages"]
        self.assertEqual(messages[0]["role"], "user")
        blocks = [block for message in messages for block in message["content"]]
        self.assertTrue(any(block.get("type") == "tool_use" for block in blocks))
        self.assertTrue(any(block.get("type") == "tool_result" for block in blocks))

    def test_model_discovery_uses_v1_models(self):
        captured = {}

        def fake_get(url, headers, timeout, attempts=2):
            captured["url"] = url
            captured["headers"] = headers
            return {"data": [{"id": "claude-a"}, {"id": "claude-b"}]}

        original = llm._get_json
        llm._get_json = fake_get
        try:
            models = llm.list_models("anthropic", "", "secret")
        finally:
            llm._get_json = original
        self.assertEqual(models, ["claude-a", "claude-b"])
        self.assertTrue(captured["url"].endswith("/v1/models"))
        self.assertEqual(captured["headers"]["x-api-key"], "secret")


class ProviderConfigTest(unittest.TestCase):
    def test_openai_compatible_defaults(self):
        config = llm.ProviderConfig(provider="deepseek", api_key="k").resolved()
        self.assertEqual(config.base_url, "https://api.deepseek.com/v1")
        self.assertEqual(config.model, "deepseek-chat")

    def test_unknown_provider_requires_base_url(self):
        with self.assertRaises(llm.LLMError):
            llm.ProviderConfig(provider="nope").resolved()
        config = llm.ProviderConfig(provider="nope", base_url="http://localhost:1234/v1").resolved()
        self.assertEqual(config.base_url, "http://localhost:1234/v1")
