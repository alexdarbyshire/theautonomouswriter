import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx2
import pytest

from agent.llm import LLMUnavailableError, OpenRouterClient


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


@pytest.mark.parametrize("status_code", [200, 429])
def test_sdk_transport_preserves_openrouter_requests_and_errors(monkeypatch, status_code):
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/model")
    monkeypatch.setattr("agent.llm.time.sleep", lambda seconds: None)
    requests = []

    def respond(request):
        requests.append(request)
        if status_code == 429:
            return httpx2.Response(429, json={"error": {"message": "Rate limited", "type": "rate_limit"}})
        return httpx2.Response(
            200,
            json={
                "id": "offline-completion",
                "object": "chat.completion",
                "created": 0,
                "model": "test/model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "A topic"}}],
            },
        )

    writer = OpenRouterClient()
    # Exercise SDK serialization and response parsing while keeping all traffic offline.
    with writer.client.with_options(
        http_client=httpx2.Client(transport=httpx2.MockTransport(respond)), max_retries=0
    ) as sdk:
        writer.client.close()
        writer.client = sdk
        if status_code == 429:
            with pytest.raises(LLMUnavailableError, match="after 3 attempts"):
                writer.select_topic("Writer identity", "Choose a topic")
        else:
            assert writer.select_topic("Writer identity", "Choose a topic") == "A topic"

    assert len(requests) == (3 if status_code == 429 else 1)
    request = requests[0]
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer offline-test"
    assert json.loads(request.content) == {
        "model": "test/model",
        "messages": [
            {"role": "system", "content": "Writer identity"},
            {"role": "user", "content": "Choose a topic"},
        ],
        "temperature": 0.8,
        "max_tokens": 300,
        "reasoning": {"effort": "low"},
    }
