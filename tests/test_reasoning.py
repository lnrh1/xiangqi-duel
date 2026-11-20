import unittest

from xiangqi_duel.llm import (
    ProviderConfig,
    apply_anthropic_options,
    apply_openai_options,
    normalise_effort,
)


def payload(max_tokens=1200):
    return {
        "model": "test",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.6,
        "max_tokens": max_tokens,
        "stream": False,
    }


class ReasoningAdapterTest(unittest.TestCase):
    def test_effort_normalisation(self):
        self.assertEqual(normalise_effort("off"), "off")
        self.assertEqual(normalise_effort("none"), "off")
        self.assertEqual(normalise_effort("xhigh"), "max")
        self.assertEqual(normalise_effort("auto"), "")
        self.assertEqual(normalise_effort("bogus"), "")

    def test_deepseek(self):
        cfg = ProviderConfig(provider="deepseek", model="deepseek-flash", reasoning_effort="high")
        out = apply_openai_options(payload(), cfg)
        self.assertEqual(out["thinking"], {"type": "enabled"})
        self.assertEqual(out["reasoning_effort"], "high")
        self.assertNotIn("temperature", out)

    def test_deepseek_off(self):
        cfg = ProviderConfig(provider="deepseek", model="deepseek-chat", reasoning_effort="off")
        out = apply_openai_options(payload(), cfg)
        self.assertEqual(out["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", out)

    def test_openai_reasoning_uses_completion_tokens(self):
        cfg = ProviderConfig(provider="openai", model="gpt-5", reasoning_effort="medium")
        out = apply_openai_options(payload(3000), cfg)
        self.assertEqual(out["reasoning_effort"], "medium")
        self.assertEqual(out["max_completion_tokens"], 3000)
        self.assertNotIn("max_tokens", out)
        self.assertNotIn("temperature", out)

    def test_qwen(self):
        cfg = ProviderConfig(provider="dashscope", model="qwen3-max", reasoning_effort="high", thinking_budget=2048)
        out = apply_openai_options(payload(), cfg)
        self.assertTrue(out["enable_thinking"])
        self.assertEqual(out["thinking_budget"], 2048)

    def test_qwen4_effort(self):
        cfg = ProviderConfig(provider="dashscope", model="qwen4-max", reasoning_effort="high")
        out = apply_openai_options(payload(), cfg)
        self.assertEqual(out["reasoning_effort"], "xhigh")

    def test_zhipu_forced_reasoning(self):
        cfg = ProviderConfig(provider="zhipu", model="glm-5.3", reasoning_effort="off")
        out = apply_openai_options(payload(), cfg)
        self.assertEqual(out["thinking"], {"type": "enabled"})
        self.assertEqual(out["reasoning_effort"], "low")

    def test_kimi_k3(self):
        cfg = ProviderConfig(provider="moonshot", model="kimi-k3.1-pro", reasoning_effort="high")
        out = apply_openai_options(payload(), cfg)
        self.assertEqual(out["reasoning_effort"], "high")
        self.assertNotIn("thinking", out)

    def test_aggregator_untouched(self):
        cfg = ProviderConfig(provider="siliconflow", model="Qwen/Qwen3", reasoning_effort="high")
        out = apply_openai_options(payload(), cfg)
        self.assertNotIn("reasoning_effort", out)
        self.assertNotIn("enable_thinking", out)

    def test_extra_body_wins(self):
        cfg = ProviderConfig(provider="deepseek", model="deepseek-chat", reasoning_effort="high", extra_body={"temperature": 0.2, "custom": {"a": 1}})
        out = apply_openai_options(payload(), cfg)
        self.assertEqual(out["temperature"], 0.2)
        self.assertEqual(out["custom"], {"a": 1})

    def test_anthropic_thinking_budget(self):
        cfg = ProviderConfig(provider="anthropic", model="claude-sonnet-4-5", reasoning_effort="high")
        out = apply_anthropic_options(payload(1200), cfg)
        self.assertEqual(out["thinking"]["type"], "enabled")
        self.assertEqual(out["thinking"]["budget_tokens"], 8192)
        self.assertGreater(out["max_tokens"], 8192)
        self.assertNotIn("temperature", out)

    def test_anthropic_explicit_budget(self):
        cfg = ProviderConfig(provider="anthropic", model="claude-sonnet-4-5", thinking_budget=5000, extra_body={"metadata": {"user_id": "u"}})
        out = apply_anthropic_options(payload(1200), cfg)
        self.assertEqual(out["thinking"]["budget_tokens"], 5000)
        self.assertEqual(out["metadata"], {"user_id": "u"})


if __name__ == "__main__":
    unittest.main()
