import json
import logging
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent import evolve
from agent.llm import LLMUnavailableError, OpenRouterClient


@pytest.mark.parametrize(
    "response",
    [
        {"prompt_evolution": "Expanded identity", "note": "An extra thought"},
        {"mood": "", "reflection": "", "prompt_evolution": "Expanded identity"},
        {"mood": "thoughtful", "reflection": "A thought", "prompt_evolution": "Expanded identity\n" * 150},
    ],
)
def test_identity_change_preserves_optional_response_fields(monkeypatch, tmp_path, caplog, response):
    prompt_path = tmp_path / "system.md"
    prompt_path.write_text("Original identity\n")
    monkeypatch.setattr(evolve, "SYSTEM_PROMPT_PATH", prompt_path)
    memory = {"current_persona_mood": "curious", "past_reflections": ["Earlier thought"]}
    before = deepcopy(memory)
    llm = MagicMock()
    llm.reflect.return_value = json.dumps(response)

    with caplog.at_level(logging.INFO):
        result = evolve.reflect_and_evolve("Article body", memory, llm)

    assert result == response
    assert prompt_path.read_text() == response["prompt_evolution"].strip() + "\n"
    assert memory == before
    assert "Reflection outcome: identity changed" in caplog.text
    sent_body, sent_prompt = llm.reflect.call_args.args
    assert sent_body == "Article body"
    assert "Earlier thought" in sent_prompt
    assert "Original identity" in sent_prompt
    assert "most runs should be null" in sent_prompt


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"mood": "curious", "reflection": "A new thought"},
        {"prompt_evolution": None},
        {"prompt_evolution": "Original identity\n"},
        {"prompt_evolution": 42},
    ],
)
def test_retained_identity_returns_original_response(monkeypatch, tmp_path, caplog, response):
    prompt_path = tmp_path / "system.md"
    prompt_path.write_text("Original identity\n")
    monkeypatch.setattr(evolve, "SYSTEM_PROMPT_PATH", prompt_path)
    llm = MagicMock()
    llm.reflect.return_value = "```json\n" + json.dumps(response) + "\n```"

    with caplog.at_level(logging.INFO):
        result = evolve.reflect_and_evolve("Article body", {}, llm)

    assert result == response
    assert prompt_path.read_text() == "Original identity\n"
    assert "Reflection outcome: identity retained" in caplog.text


@pytest.mark.parametrize("failure", ["malformed", "unavailable"])
def test_reflection_failure_is_noncritical(monkeypatch, tmp_path, caplog, failure):
    prompt_path = tmp_path / "system.md"
    prompt_path.write_text("Original identity\n")
    monkeypatch.setattr(evolve, "SYSTEM_PROMPT_PATH", prompt_path)
    memory = {"current_persona_mood": "curious", "past_reflections": ["Earlier thought"]}
    before = deepcopy(memory)
    llm = MagicMock()
    if failure == "unavailable":
        llm.reflect.side_effect = LLMUnavailableError("Service unavailable")
    else:
        llm.reflect.return_value = '{"mood": "thoughtful", "reflection":'

    assert evolve.reflect_and_evolve("Article body", memory, llm) == {}
    assert prompt_path.read_text() == "Original identity\n"
    assert memory == before
    assert "Reflection outcome: failed" in caplog.text


def test_reflection_has_separate_output_allowance(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    sdk = MagicMock()
    sdk.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="response"))]
    )
    monkeypatch.setattr("agent.llm.OpenAI", lambda **kwargs: sdk)
    client = OpenRouterClient()

    assert client.reflect("Article body", "Reflection instructions") == "response"
    reflection_request = sdk.chat.completions.create.call_args.kwargs
    assert reflection_request["max_tokens"] == 4096
    assert reflection_request["temperature"] == 0.1
    assert reflection_request["extra_body"] == {"reasoning": {"effort": "low"}}
    assert reflection_request["messages"] == [
        {"role": "system", "content": "Reflection instructions"},
        {"role": "user", "content": "Article body"},
    ]

    client.extract_frontmatter("Article body", "Frontmatter instructions")
    assert sdk.chat.completions.create.call_args.kwargs["max_tokens"] == 400


def test_failed_reflection_does_not_stop_publication(monkeypatch, tmp_path, caplog):
    from agent import main, memory

    for flag in (
        "ENABLE_BLUESKY_REPLIES",
        "ENABLE_NEWSLETTER_REPLIES",
        "ENABLE_SUGGESTIONS",
        "ENABLE_RESEARCH",
        "ENABLE_IMAGES",
        "ENABLE_BLUESKY",
        "ENABLE_NEWSLETTER",
    ):
        monkeypatch.delenv(flag, raising=False)
    monkeypatch.setenv("FORCE_POST", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    identity = prompts / "system.md"
    identity.write_text("Original identity\n")
    (prompts / "frontmatter.md").write_text("Frontmatter instructions")
    monkeypatch.setattr(main, "PROMPTS_DIR", prompts)
    monkeypatch.setattr(main, "POSTS_DIR", tmp_path / "posts")
    monkeypatch.setattr(evolve, "SYSTEM_PROMPT_PATH", identity)
    memory_path = tmp_path / "memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "past_topics": [],
                "past_slugs": [],
                "current_persona_mood": "curious",
                "past_reflections": ["Earlier thought"],
                "total_posts_written": 0,
            }
        )
    )
    monkeypatch.setattr(memory.load_memory, "__defaults__", (memory_path,))
    monkeypatch.setattr(memory.save_memory, "__defaults__", (memory_path,))
    sdk = MagicMock()
    responses = [
        "A new topic",
        "## A new topic\n\n" + "Thoughtful article content. " * 150,
        json.dumps(
            {
                "title": "A thoughtful new topic",
                "date": "2026-11-17",
                "slug": "a-new-topic",
                "description": "An article exploring a thoughtful new topic.",
                "tags": ["philosophy"],
                "draft": False,
            }
        ),
        '{"mood": "thoughtful", "reflection":',
    ]
    sdk.chat.completions.create.side_effect = [
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))]) for raw in responses
    ]
    monkeypatch.setattr("agent.llm.OpenAI", lambda **kwargs: sdk)
    monkeypatch.setattr("agent.hugo.subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    with caplog.at_level(logging.INFO):
        main.main()

    saved = json.loads(memory_path.read_text())
    assert saved["total_posts_written"] == 1
    assert saved["past_topics"] == ["A new topic"]
    assert saved["current_persona_mood"] == "curious"
    assert saved["past_reflections"] == ["Earlier thought"]
    assert len(list((tmp_path / "posts").glob("*.md"))) == 1
    assert identity.read_text() == "Original identity\n"
    assert "Reflection outcome: failed" in caplog.text
