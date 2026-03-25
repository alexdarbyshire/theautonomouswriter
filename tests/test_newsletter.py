import json
from unittest.mock import MagicMock, patch

from agent.newsletter import notify_new_post, maybe_send_recap, _get_recent_posts


def test_notify_disabled_when_flag_off(monkeypatch):
    monkeypatch.delenv("ENABLE_NEWSLETTER", raising=False)
    assert notify_new_post("Title", "Desc", "slug") is False


def test_notify_disabled_when_key_missing(monkeypatch):
    monkeypatch.setenv("ENABLE_NEWSLETTER", "true")
    monkeypatch.delenv("BUTTONDOWN_API_KEY", raising=False)
    assert notify_new_post("Title", "Desc", "slug") is False


def test_notify_sends_email(monkeypatch):
    monkeypatch.setenv("ENABLE_NEWSLETTER", "true")
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "test-key")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("agent.newsletter.urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = notify_new_post("My Title", "My description", "my-slug")

    assert result is True
    call_args = mock_urlopen.call_args
    req = call_args[0][0]
    assert req.get_header("Authorization") == "Token test-key"
    body = json.loads(req.data)
    assert body["subject"] == "My Title"
    assert "my-slug" in body["body"]
    assert body["status"] == "about_to_send"


def test_notify_handles_failure(monkeypatch):
    monkeypatch.setenv("ENABLE_NEWSLETTER", "true")
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "test-key")

    with patch("agent.newsletter.urllib.request.urlopen", side_effect=Exception("fail")):
        assert notify_new_post("Title", "Desc", "slug") is False


def test_recap_skips_when_not_enough_posts(monkeypatch):
    monkeypatch.setenv("ENABLE_NEWSLETTER", "true")
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "test-key")

    memory = {"total_posts_written": 2, "last_newsletter_at_post_count": 0}
    assert maybe_send_recap(memory, MagicMock(), "system prompt") is False


def test_recap_sends_when_threshold_reached(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_NEWSLETTER", "true")
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "test-key")

    # Create fake post files
    for i in range(3):
        post_dir = tmp_path / f"2026-03-{20+i:02d}-post-{i}"
        post_dir.mkdir()
        fm = {
            "title": f"Post {i}",
            "slug": f"post-{i}",
            "description": f"Description {i}",
            "date": f"2026-03-{20+i:02d}",
            "tags": ["test"],
            "draft": False,
        }
        fm_yaml = "---\n"
        for key, value in fm.items():
            fm_yaml += f"{key}: {json.dumps(value)}\n"
        fm_yaml += "---\n\nBody text here."
        (post_dir / "index.md").write_text(fm_yaml)

    memory = {
        "total_posts_written": 6,
        "last_newsletter_at_post_count": 3,
        "current_persona_mood": "curious",
    }

    mock_llm = MagicMock()
    mock_llm.compose_newsletter.return_value = json.dumps({
        "subject": "Recap: Recent Musings",
        "body": "Here are my recent posts...",
    })

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("agent.newsletter.POSTS_DIR", tmp_path), \
         patch("agent.newsletter.urllib.request.urlopen", return_value=mock_resp):
        result = maybe_send_recap(memory, mock_llm, "You are a writer...")

    assert result is True
    assert memory["last_newsletter_at_post_count"] == 6
    mock_llm.compose_newsletter.assert_called_once()
    # Verify system prompt was passed
    call_args = mock_llm.compose_newsletter.call_args
    assert call_args[0][0] == "You are a writer..."


def test_recap_handles_failure(monkeypatch):
    monkeypatch.setenv("ENABLE_NEWSLETTER", "true")
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "test-key")

    memory = {
        "total_posts_written": 6,
        "last_newsletter_at_post_count": 3,
        "current_persona_mood": "curious",
    }

    with patch("agent.newsletter._get_recent_posts", return_value=[]):
        result = maybe_send_recap(memory, MagicMock(), "system prompt")

    assert result is False
    # Memory should not be updated on failure
    assert memory["last_newsletter_at_post_count"] == 3
