from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.llm import OpenRouterClient


def test_safety_screening_limits_reasoning_only_for_main_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-5.5")
    sdk = MagicMock()
    sdk.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="SAFE"))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2),
    )
    monkeypatch.setattr("agent.llm.OpenAI", lambda **kwargs: sdk)

    safe, reason, usage = OpenRouterClient().check_safety("Write about lucid dreaming.")

    assert safe
    assert reason == ""
    assert usage == {"prompt_tokens": 20, "completion_tokens": 4}
    guard, main = [call.kwargs for call in sdk.chat.completions.create.call_args_list]
    assert guard["model"] == "meta-llama/llama-guard-4-12b"
    assert guard["extra_body"] is None
    assert main["model"] == "anthropic/claude-sonnet-5.5"
    assert main["extra_body"] == {"reasoning": {"effort": "low"}}
