from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from cryptography.fernet import Fernet

from agent.suggestions import (
    check_rate_limit,
    cleanup,
    decrypt_identifier,
    encrypt_identifier,
    format_suggestions_for_prompt,
    get_safe_suggestions,
    load_suggestions,
    mark_used,
    match_suggestion,
    save_suggestions,
    screen_pending,
)

TEST_KEY = Fernet.generate_key().decode()


def _now_iso():
    return datetime.now(UTC).isoformat()


def _ago(days):
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _make_suggestion(id="web-1-abc", status="pending", source="web", text="Test topic", days_ago=0, submitter=None):
    entry = {
        "id": id,
        "source": source,
        "text": text,
        "submitter_encrypted": submitter or encrypt_identifier("user1", TEST_KEY),
        "submitted_at": _ago(days_ago),
        "status": status,
        "safety_reason": None,
        "used_in_slug": None,
    }
    return entry


def test_load_empty_suggestions(tmp_path):
    path = tmp_path / "suggestions.json"
    data = load_suggestions(path)
    assert data["suggestions"] == []
    assert data["processed_issues"] == []
    assert data["processed_reply_ids"] == []
    assert data["last_cleanup"] is None


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "suggestions.json"
    data = {
        "suggestions": [_make_suggestion()],
        "processed_issues": [],
        "processed_reply_ids": [],
        "last_cleanup": None,
    }
    save_suggestions(data, path)
    loaded = load_suggestions(path)
    assert len(loaded["suggestions"]) == 1
    assert loaded["suggestions"][0]["id"] == "web-1-abc"


def test_screen_pending_safe():
    llm = MagicMock()
    llm.check_safety.return_value = (True, "", {})
    data = {"suggestions": [_make_suggestion(status="pending")]}
    screen_pending(data, llm)
    assert data["suggestions"][0]["status"] == "screened_safe"
    llm.check_safety.assert_called_once()


def test_screen_pending_unsafe():
    llm = MagicMock()
    llm.check_safety.return_value = (False, "unsafe\nS1", {})
    data = {"suggestions": [_make_suggestion(status="pending")]}
    screen_pending(data, llm)
    assert data["suggestions"][0]["status"] == "screened_unsafe"
    assert data["suggestions"][0]["safety_reason"] == "unsafe\nS1"


def test_screen_pending_caps_at_10():
    llm = MagicMock()
    llm.check_safety.return_value = (True, "", {})
    entries = [_make_suggestion(id=f"web-{i}-abc", status="pending") for i in range(15)]
    data = {"suggestions": entries}
    screen_pending(data, llm)
    assert llm.check_safety.call_count == 10
    # First 10 screened, last 5 still pending
    assert sum(1 for s in data["suggestions"] if s["status"] == "screened_safe") == 10
    assert sum(1 for s in data["suggestions"] if s["status"] == "pending") == 5


def test_get_safe_suggestions():
    entries = [_make_suggestion(id=f"web-{i}-abc", status="screened_safe") for i in range(8)]
    entries.append(_make_suggestion(id="unsafe-1", status="screened_unsafe"))
    entries.append(_make_suggestion(id="pending-1", status="pending"))
    data = {"suggestions": entries}
    safe = get_safe_suggestions(data)
    assert len(safe) == 5  # capped at MAX_SAFE_FOR_PROMPT
    assert all(s["status"] == "screened_safe" for s in safe)


def test_mark_used():
    data = {"suggestions": [_make_suggestion(id="web-1-abc", status="screened_safe")]}
    mark_used(data, "web-1-abc", "my-post-slug")
    assert data["suggestions"][0]["status"] == "used"
    assert data["suggestions"][0]["used_in_slug"] == "my-post-slug"


def test_cleanup_expires_old_safe():
    data = {"suggestions": [_make_suggestion(status="screened_safe", days_ago=91)]}
    cleanup(data)
    assert data["suggestions"][0]["status"] == "expired"


def test_cleanup_removes_old_unsafe():
    data = {"suggestions": [_make_suggestion(status="screened_unsafe", days_ago=8)]}
    cleanup(data)
    assert len(data["suggestions"]) == 0


def test_cleanup_removes_old_used():
    entry = _make_suggestion(status="used", days_ago=31)
    entry["used_in_slug"] = "some-slug"
    data = {"suggestions": [entry]}
    cleanup(data)
    assert len(data["suggestions"]) == 0


def test_cleanup_keeps_recent():
    data = {
        "suggestions": [
            _make_suggestion(id="safe-1", status="screened_safe", days_ago=5),
            _make_suggestion(id="unsafe-1", status="screened_unsafe", days_ago=3),
            _make_suggestion(id="used-1", status="used", days_ago=10),
        ]
    }
    cleanup(data)
    assert len(data["suggestions"]) == 3


def test_encrypt_decrypt_roundtrip():
    original = "google-user-12345"
    encrypted = encrypt_identifier(original, TEST_KEY)
    assert encrypted != original
    decrypted = decrypt_identifier(encrypted, TEST_KEY)
    assert decrypted == original


def test_encrypt_varies_per_call():
    """Fernet produces different ciphertext each time due to timestamp + IV."""
    a = encrypt_identifier("user1", TEST_KEY)
    b = encrypt_identifier("user1", TEST_KEY)
    assert a != b
    # But both decrypt to the same value
    assert decrypt_identifier(a, TEST_KEY) == decrypt_identifier(b, TEST_KEY)


def test_rate_limit_allows_under():
    enc = encrypt_identifier("user1", TEST_KEY)
    data = {
        "suggestions": [
            _make_suggestion(id="web-1-abc", source="web", days_ago=5, submitter=enc),
            _make_suggestion(id="web-2-def", source="web", days_ago=3, submitter=enc),
        ]
    }
    assert check_rate_limit(data, "user1", TEST_KEY, "web", max_count=3, window_days=30) is True


def test_rate_limit_blocks_over():
    enc = encrypt_identifier("user1", TEST_KEY)
    data = {
        "suggestions": [_make_suggestion(id=f"web-{i}-abc", source="web", days_ago=i, submitter=enc) for i in range(3)]
    }
    assert check_rate_limit(data, "user1", TEST_KEY, "web", max_count=3, window_days=30) is False


def test_rate_limit_ignores_other_sources():
    enc = encrypt_identifier("user1", TEST_KEY)
    data = {
        "suggestions": [
            _make_suggestion(id=f"github-{i}-abc", source="github", days_ago=i, submitter=enc) for i in range(5)
        ]
    }
    # All are github, checking web — should be under limit
    assert check_rate_limit(data, "user1", TEST_KEY, "web", max_count=3, window_days=30) is True


def test_rate_limit_ignores_old():
    data = {
        "suggestions": [
            _make_suggestion(
                id=f"web-{i}-abc", source="web", days_ago=35, submitter=encrypt_identifier("user1", TEST_KEY)
            )
            for i in range(5)
        ]
    }
    assert check_rate_limit(data, "user1", TEST_KEY, "web", max_count=3, window_days=30) is True


def test_format_suggestions_for_prompt():
    safe = [
        {"id": "web-1-abc", "text": "The ethics of AI"},
        {"id": "github-2-def", "text": "Ancient maps"},
    ]
    result = format_suggestions_for_prompt(safe)
    assert '"The ethics of AI"' in result
    assert '"Ancient maps"' in result
    # Should not expose internal IDs to the writer
    assert "web-1-abc" not in result
    assert "github-2-def" not in result
    assert "curiosity" in result


def test_match_suggestion_finds_match():
    safe = [
        {"id": "web-1-abc", "text": "The ethics of AI writing"},
        {"id": "github-2-def", "text": "Ancient maps and exploration"},
    ]
    result = match_suggestion("The ethics of AI writing about itself", safe)
    assert result == "web-1-abc"


def test_match_suggestion_no_match():
    safe = [
        {"id": "web-1-abc", "text": "The ethics of AI writing"},
    ]
    result = match_suggestion("The philosophy of waiting rooms", safe)
    assert result is None


def test_match_suggestion_empty_list():
    assert match_suggestion("Any topic", []) is None


def test_disabled_when_flag_off(monkeypatch):
    """When ENABLE_SUGGESTIONS is not set, the feature gate in main.py would skip loading."""
    import os

    monkeypatch.delenv("ENABLE_SUGGESTIONS", raising=False)
    assert os.environ.get("ENABLE_SUGGESTIONS", "").lower() != "true"
    # Module functions still work — the gate is in main.py, not here
    data = load_suggestions(Path("/nonexistent/path"))
    assert data["suggestions"] == []
