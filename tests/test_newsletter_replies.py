import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet

from agent.newsletter_replies import (
    _find_count_key,
    _handle_single_comment,
    _load_state,
    _process_comments,
    ingest_comment_suggestions,
    respond_to_comments,
)

TEST_KEY = Fernet.generate_key().decode()
ENC_KEY = Fernet.generate_key().decode()


def _make_comment(id="c1", subscriber_id="sub-1", email_id="email-1", body="Great post!", parent_id=None):
    return {
        "id": id,
        "subscriber_id": subscriber_id,
        "email_id": email_id,
        "body": body,
        "parent_id": parent_id,
        "creation_date": datetime.now(timezone.utc).isoformat(),
    }


def test_disabled_when_flag_off(monkeypatch):
    monkeypatch.delenv("ENABLE_NEWSLETTER_REPLIES", raising=False)
    stats = respond_to_comments(MagicMock(), {}, "curious")
    assert stats["replies_sent"] == 0


def test_disabled_when_api_key_missing(monkeypatch):
    monkeypatch.setenv("ENABLE_NEWSLETTER_REPLIES", "true")
    monkeypatch.delenv("BUTTONDOWN_API_KEY", raising=False)
    stats = respond_to_comments(MagicMock(), {}, "curious")
    assert stats["replies_sent"] == 0


def test_disabled_when_encryption_key_missing(monkeypatch):
    monkeypatch.setenv("ENABLE_NEWSLETTER_REPLIES", "true")
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "fake-key")
    monkeypatch.delenv("SUGGESTION_ENCRYPTION_KEY", raising=False)
    stats = respond_to_comments(MagicMock(), {}, "curious")
    assert stats["replies_sent"] == 0


def test_safety_check_blocks_unsafe():
    llm = MagicMock()
    llm.check_safety.return_value = (False, "unsafe\nS1", {"prompt_tokens": 10, "completion_tokens": 5})

    comment = _make_comment()
    stats = {"replies_sent": 0, "tokens_used": 0, "skipped_unsafe": 0}
    replied_ids = []
    replied_set = set()
    reply_counts = {}

    _handle_single_comment(
        "fake-key", llm, comment, "curious", "writer identity",
        reply_counts, replied_ids, replied_set, stats, ENC_KEY,
    )

    assert stats["skipped_unsafe"] == 1
    assert stats["replies_sent"] == 0
    assert comment["id"] in replied_set


@patch("agent.newsletter_replies._send_reply_email", return_value=True)
def test_successful_reply(mock_send):
    llm = MagicMock()
    llm.check_safety.return_value = (True, "", {"prompt_tokens": 10, "completion_tokens": 5})
    llm.compose_email_reply.return_value = ("Thank you for writing.", {"prompt_tokens": 50, "completion_tokens": 30})

    comment = _make_comment()
    stats = {"replies_sent": 0, "tokens_used": 0, "skipped_unsafe": 0}
    replied_ids = []
    replied_set = set()
    reply_counts = {}

    _handle_single_comment(
        "fake-key", llm, comment, "curious", "writer identity",
        reply_counts, replied_ids, replied_set, stats, ENC_KEY,
    )

    assert stats["replies_sent"] == 1
    # Count key should contain encrypted subscriber ID, not plaintext
    assert len(reply_counts) == 1
    key = next(iter(reply_counts))
    assert key.startswith("email-1:")
    assert "sub-1" not in key  # subscriber ID must not appear in plaintext
    assert reply_counts[key] == 1
    mock_send.assert_called_once()
    llm.compose_email_reply.assert_called_once()


def test_per_subscriber_rate_limit():
    llm = MagicMock()
    comment = _make_comment()
    stats = {"replies_sent": 0, "tokens_used": 0, "skipped_unsafe": 0}
    replied_ids = []
    replied_set = set()
    # Pre-populate with encrypted subscriber ID at limit
    from agent.newsletter_replies import _encrypt_subscriber_id
    encrypted_sub = _encrypt_subscriber_id("sub-1", ENC_KEY)
    reply_counts = {f"email-1:{encrypted_sub}": 2}  # already at limit

    _handle_single_comment(
        "fake-key", llm, comment, "curious", "writer identity",
        reply_counts, replied_ids, replied_set, stats, ENC_KEY,
    )

    assert stats["replies_sent"] == 0
    assert comment["id"] in replied_set
    llm.check_safety.assert_not_called()


@patch("agent.newsletter_replies._send_reply_email", return_value=True)
def test_final_reply_signals_closing(mock_send):
    llm = MagicMock()
    llm.check_safety.return_value = (True, "", {"prompt_tokens": 10, "completion_tokens": 5})
    llm.compose_email_reply.return_value = ("Farewell for now.", {"prompt_tokens": 50, "completion_tokens": 30})

    comment = _make_comment()
    stats = {"replies_sent": 0, "tokens_used": 0, "skipped_unsafe": 0}
    # Pre-populate with encrypted subscriber ID one away from limit
    from agent.newsletter_replies import _encrypt_subscriber_id
    encrypted_sub = _encrypt_subscriber_id("sub-1", ENC_KEY)
    reply_counts = {f"email-1:{encrypted_sub}": 1}  # one away from limit

    _handle_single_comment(
        "fake-key", llm, comment, "curious", "writer identity",
        reply_counts, [], set(), stats, ENC_KEY,
    )

    # Should have passed is_final=True
    call_args = llm.compose_email_reply.call_args
    assert call_args[1].get("is_final") or call_args[0][3] is True


@patch("agent.newsletter_replies._api_get")
def test_token_budget_stops_processing(mock_get):
    mock_get.return_value = {
        "results": [_make_comment(id=f"c{i}") for i in range(5)],
    }

    llm = MagicMock()
    llm.check_safety.return_value = (True, "", {"prompt_tokens": 20000, "completion_tokens": 10001})

    state = {"replied_ids": [], "subscriber_reply_counts": {}}
    stats = {"replies_sent": 0, "tokens_used": 0, "skipped_unsafe": 0}

    _process_comments("fake-key", llm, state, "curious", "writer identity", stats, ENC_KEY)

    # Should stop after first comment exceeds budget
    assert llm.check_safety.call_count == 1


def test_load_state_returns_default(tmp_path):
    with patch("agent.newsletter_replies.STATE_PATH", tmp_path / "nonexistent.json"):
        state = _load_state()
    assert state == {"replied_ids": [], "subscriber_reply_counts": {}}


@patch("agent.newsletter_replies._api_get")
def test_ingest_short_comments_as_suggestions(mock_get):
    mock_get.return_value = {
        "results": [
            _make_comment(id="c1", body="Write about the philosophy of waiting rooms"),
            _make_comment(id="c2", body="Great post, loved it!", parent_id="c0"),  # threaded — skip
            _make_comment(id="c3", body="x" * 301),  # too long — skip
        ],
    }

    llm = MagicMock()
    llm.check_safety.return_value = (True, "", {})

    suggestions_data = {
        "suggestions": [],
        "processed_issues": [],
        "processed_reply_ids": [],
        "last_cleanup": None,
    }

    count = ingest_comment_suggestions("fake-key", llm, suggestions_data, TEST_KEY)

    assert count == 1
    assert suggestions_data["suggestions"][0]["source"] == "newsletter"
    assert suggestions_data["suggestions"][0]["text"] == "Write about the philosophy of waiting rooms"
    assert "c1" in suggestions_data["processed_reply_ids"]
    assert "c2" in suggestions_data["processed_reply_ids"]
    assert "c3" in suggestions_data["processed_reply_ids"]


@patch("agent.newsletter_replies._api_get")
def test_ingest_skips_already_processed(mock_get):
    mock_get.return_value = {
        "results": [_make_comment(id="c1", body="Write about AI dreams")],
    }

    llm = MagicMock()
    suggestions_data = {
        "suggestions": [],
        "processed_issues": [],
        "processed_reply_ids": ["c1"],
        "last_cleanup": None,
    }

    count = ingest_comment_suggestions("fake-key", llm, suggestions_data, TEST_KEY)
    assert count == 0
    llm.check_safety.assert_not_called()


@patch("agent.newsletter_replies._api_get")
def test_ingest_blocks_unsafe_comments(mock_get):
    mock_get.return_value = {
        "results": [_make_comment(id="c1", body="Something unsafe")],
    }

    llm = MagicMock()
    llm.check_safety.return_value = (False, "unsafe", {})

    suggestions_data = {
        "suggestions": [],
        "processed_issues": [],
        "processed_reply_ids": [],
        "last_cleanup": None,
    }

    count = ingest_comment_suggestions("fake-key", llm, suggestions_data, TEST_KEY)
    assert count == 0
    assert len(suggestions_data["suggestions"]) == 0


def test_find_count_key_creates_encrypted_key():
    key, count = _find_count_key({}, "email-1", "sub-1", ENC_KEY)
    assert key.startswith("email-1:")
    assert "sub-1" not in key  # subscriber ID must be encrypted
    assert count == 0


def test_find_count_key_matches_existing_encrypted():
    from agent.newsletter_replies import _encrypt_subscriber_id
    encrypted_sub = _encrypt_subscriber_id("sub-1", ENC_KEY)
    existing_counts = {f"email-1:{encrypted_sub}": 3}

    key, count = _find_count_key(existing_counts, "email-1", "sub-1", ENC_KEY)
    assert count == 3
    assert key == f"email-1:{encrypted_sub}"
