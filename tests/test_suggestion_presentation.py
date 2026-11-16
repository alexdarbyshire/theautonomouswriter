import json
from datetime import UTC, datetime
from functools import partial
from types import SimpleNamespace

import pytest

from agent import evolve, hugo, llm, main
from agent.llm import LLMUnavailableError
from agent.memory import load_memory, save_memory
from agent.suggestions import get_safe_suggestions, load_suggestions, save_suggestions


@pytest.fixture
def writer_run(tmp_path, monkeypatch):
    memory_path = tmp_path / "memory.json"
    suggestion_path = tmp_path / "suggestions.json"
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "system.md").write_text("A curious writer.")
    (prompt_dir / "frontmatter.md").write_text("Extract frontmatter.")
    save_memory({"past_topics": [], "past_slugs": [], "past_reflections": []}, memory_path)
    suggestion = {
        "id": "web-dreams",
        "text": "I would like to hear your thoughts on conscious dreaming and Robert Moss.",
        "status": "screened_safe",
        "submitted_at": datetime.now(UTC).isoformat(),
    }
    save_suggestions({"suggestions": [suggestion]}, suggestion_path)
    for flag in (
        "ENABLE_BLUESKY",
        "ENABLE_BLUESKY_REPLIES",
        "ENABLE_NEWSLETTER",
        "ENABLE_NEWSLETTER_REPLIES",
        "ENABLE_RESEARCH",
        "ENABLE_IMAGES",
    ):
        monkeypatch.setenv(flag, "false")
    monkeypatch.setenv("ENABLE_SUGGESTIONS", "true")
    monkeypatch.setenv("FORCE_POST", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-not-a-key")
    monkeypatch.setattr(main, "PROMPTS_DIR", prompt_dir)
    monkeypatch.setattr(main, "POSTS_DIR", tmp_path / "posts")
    monkeypatch.setattr(main, "load_memory", partial(load_memory, memory_path))
    monkeypatch.setattr(main, "save_memory", partial(save_memory, path=memory_path))
    monkeypatch.setattr(main, "load_suggestions", partial(load_suggestions, suggestion_path))
    monkeypatch.setattr(main, "save_suggestions", partial(save_suggestions, path=suggestion_path))
    monkeypatch.setattr(evolve, "SYSTEM_PROMPT_PATH", prompt_dir / "system.md")
    state = SimpleNamespace(
        selection="Ancient maps",
        body="Thoughtful words " * 220,
        failure=None,
        build_ok=True,
        build_statuses=[],
        build_results=[],
        repair_frontmatter=None,
        prompts=[],
        drafts=[],
        suggestion_path=suggestion_path,
        memory_path=memory_path,
    )

    def create(**kwargs):
        messages = kwargs["messages"]
        if "What do you want to write about next?" in messages[1]["content"]:
            state.prompts.append(messages[1]["content"])
            if state.failure == "selection":
                raise LLMUnavailableError("selection unavailable")
            content = state.selection
        elif messages[0]["content"] == "Extract frontmatter.":
            content = json.dumps(
                {
                    "title": "Dream incubation and curiosity",
                    "date": "2026-11-17",
                    "slug": f"dream-incubation-{len(state.drafts)}",
                    "description": "A thoughtful exploration of conscious dreaming.",
                    "tags": ["philosophy"],
                    "draft": False,
                }
            )
        elif "Hugo error:" in messages[1]["content"]:
            content = json.dumps(state.repair_frontmatter)
        elif "reflective AI writer" in messages[0]["content"]:
            content = '{"mood":"curious","reflection":"More to explore.","prompt_evolution":null}'
        else:
            if state.failure == "draft":
                raise LLMUnavailableError("draft unavailable")
            state.drafts.append(messages[1]["content"])
            content = state.body
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(
        llm,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )

    def build(*args, **kwargs):
        state.build_statuses.append(load_suggestions(suggestion_path)["suggestions"][0]["status"])
        returncode = state.build_results.pop(0) if state.build_results else (0 if state.build_ok else 1)
        return SimpleNamespace(returncode=returncode, stderr="build failed")

    monkeypatch.setattr(hugo.subprocess, "run", build)
    return state


def test_presented_suggestion_is_retired_even_for_an_unrelated_topic(writer_run):
    main.main()
    saved = load_suggestions(writer_run.suggestion_path)
    assert saved["suggestions"][0]["status"] == "presented"
    assert get_safe_suggestions(saved) == []
    assert "conscious dreaming and Robert Moss" in writer_run.prompts[0]
    assert "web-dreams" not in writer_run.prompts[0]
    assert "suggestion_id" not in writer_run.prompts[0]
    assert "Write a blog post about: Ancient maps\n" in writer_run.drafts[0]
    assert "If this topic was sparked by a reader suggestion" in writer_run.drafts[0]
    assert "conscious dreaming and Robert Moss" in writer_run.drafts[0]
    assert load_memory(writer_run.memory_path)["past_topics"] == ["Ancient maps"]
    assert writer_run.build_statuses == ["screened_safe"]
    writer_run.selection = "The history of pottery"
    main.main()
    assert "conscious dreaming and Robert Moss" not in writer_run.prompts[1]
    assert "conscious dreaming and Robert Moss" not in writer_run.drafts[1]
    assert "acknowledge" not in writer_run.drafts[1]


def test_only_the_suggestions_shown_are_presented(writer_run):
    data = load_suggestions(writer_run.suggestion_path)
    first = data["suggestions"][0]
    data["suggestions"] = [dict(first, id=f"web-{n}", text=f"Reader idea number {n}") for n in range(6)]
    save_suggestions(data, writer_run.suggestion_path)
    main.main()
    saved = load_suggestions(writer_run.suggestion_path)["suggestions"]
    assert [s["status"] for s in saved] == ["presented"] * 5 + ["screened_safe"]
    for n in range(5):
        assert f"Reader idea number {n}" in writer_run.prompts[0]
    assert "Reader idea number 5" not in writer_run.prompts[0]
    assert "Reader idea number 5" not in writer_run.drafts[0]


@pytest.mark.parametrize("failure", ["selection", "draft", "validation", "hugo"])
def test_failed_post_keeps_suggestions_available(writer_run, failure):
    if failure == "validation":
        writer_run.body = "Too short."
    elif failure == "hugo":
        writer_run.build_ok = False
        writer_run.repair_frontmatter = {"title": "Repair attempt"}
    else:
        writer_run.failure = failure
    with pytest.raises(SystemExit) as error:
        main.main()
    assert error.value.code == 1
    assert load_suggestions(writer_run.suggestion_path)["suggestions"][0]["status"] == "screened_safe"
    assert load_memory(writer_run.memory_path)["past_topics"] == []


def test_disabled_suggestions_do_not_offer_or_present(writer_run, monkeypatch):
    monkeypatch.setenv("ENABLE_SUGGESTIONS", "false")
    original = writer_run.suggestion_path.read_text()
    main.main()
    assert writer_run.suggestion_path.read_text() == original
    assert "conscious dreaming" not in writer_run.prompts[0]


def test_no_safe_suggestions_allows_independent_topic(writer_run):
    data = load_suggestions(writer_run.suggestion_path)
    data["suggestions"][0]["status"] = "screened_unsafe"
    save_suggestions(data, writer_run.suggestion_path)
    main.main()
    assert "conscious dreaming" not in writer_run.prompts[0]
    assert load_suggestions(writer_run.suggestion_path)["suggestions"][0]["status"] == "screened_unsafe"
