from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken

if TYPE_CHECKING:
    from agent.llm import OpenRouterClient
    from agent.types import SuggestionEntry, SuggestionsData

logger = logging.getLogger(__name__)

SUGGESTIONS_PATH = Path(__file__).resolve().parent.parent / "system" / "suggestions.json"

MAX_SCREEN_PER_RUN = 10
MAX_SAFE_FOR_PROMPT = 5
EXPIRE_SAFE_DAYS = 90
REMOVE_UNSAFE_DAYS = 7
REMOVE_USED_DAYS = 30

DEFAULT_STRUCTURE = {
    "suggestions": [],
    "processed_issues": [],
    "processed_reply_ids": [],
    "last_cleanup": None,
}


def load_suggestions(path: Path = SUGGESTIONS_PATH) -> SuggestionsData:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read suggestions, starting fresh")
    return json.loads(json.dumps(DEFAULT_STRUCTURE))


def save_suggestions(data: SuggestionsData, path: Path = SUGGESTIONS_PATH) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
        f.write("\n")
    os.replace(tmp, path)


def encrypt_identifier(identifier: str, key: str) -> str:
    f = Fernet(key.encode())
    return f.encrypt(identifier.encode()).decode()


def decrypt_identifier(token: str, key: str) -> str:
    f = Fernet(key.encode())
    return f.decrypt(token.encode()).decode()


def check_rate_limit(
    suggestions: SuggestionsData,
    identifier: str,
    key: str,
    source: str,
    max_count: int = 3,
    window_days: int = 30,
) -> bool:
    """Return True if the user is within the rate limit, False if over."""
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    count = 0
    for s in suggestions.get("suggestions", []):
        if s.get("source") != source:
            continue
        submitted = s.get("submitted_at", "")
        try:
            ts = datetime.fromisoformat(submitted)
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        encrypted = s.get("submitter_encrypted")
        if not encrypted:
            continue
        try:
            if decrypt_identifier(encrypted, key) == identifier:
                count += 1
        except InvalidToken:
            continue
    return count < max_count


def screen_pending(suggestions: SuggestionsData, llm: OpenRouterClient) -> None:
    pending = [s for s in suggestions.get("suggestions", []) if s.get("status") == "pending"]
    for entry in pending[:MAX_SCREEN_PER_RUN]:
        try:
            is_safe, reason, _usage = llm.check_safety(entry["text"])
            if is_safe:
                entry["status"] = "screened_safe"
            else:
                entry["status"] = "screened_unsafe"
                entry["safety_reason"] = reason
            logger.info("Screened suggestion %s: %s", entry["id"], entry["status"])
        except Exception as e:
            logger.warning("Failed to screen suggestion %s: %s", entry["id"], e)


def get_safe_suggestions(suggestions: SuggestionsData) -> list[SuggestionEntry]:
    safe = [s for s in suggestions.get("suggestions", []) if s.get("status") == "screened_safe"]
    return safe[:MAX_SAFE_FOR_PROMPT]


def mark_used(suggestions: SuggestionsData, suggestion_id: str, slug: str) -> None:
    for s in suggestions.get("suggestions", []):
        if s["id"] == suggestion_id:
            s["status"] = "used"
            s["used_in_slug"] = slug
            return


def cleanup(suggestions: SuggestionsData) -> None:
    now = datetime.now(UTC)
    remaining = []
    for s in suggestions.get("suggestions", []):
        submitted = s.get("submitted_at", "")
        try:
            ts = datetime.fromisoformat(submitted)
        except (ValueError, TypeError):
            remaining.append(s)
            continue

        age = now - ts
        status = s.get("status", "")

        if status == "screened_safe" and age > timedelta(days=EXPIRE_SAFE_DAYS):
            s["status"] = "expired"
            remaining.append(s)
        elif (status == "screened_unsafe" and age > timedelta(days=REMOVE_UNSAFE_DAYS)) or (
            status in ("used", "expired") and age > timedelta(days=REMOVE_USED_DAYS)
        ):
            continue  # drop it
        else:
            remaining.append(s)

    suggestions["suggestions"] = remaining
    suggestions["last_cleanup"] = now.isoformat()


def format_suggestions_for_prompt(safe: list[SuggestionEntry]) -> str:
    lines = [
        "Some of your readers have shared ideas they'd love to see you explore.",
        "Read through them \u2014 if one sparks something, let it pull you in.",
        "If nothing resonates, follow your own curiosity as always.",
        "",
    ]
    for s in safe:
        lines.append(f'- "{s["text"]}"')
    return "\n".join(lines)


def match_suggestion(topic: str, safe: list[SuggestionEntry], threshold: float = 0.5) -> str | None:
    """Find the best-matching suggestion for a chosen topic by word overlap.

    Returns the suggestion ID if a match is found, None otherwise.
    """
    if not safe:
        return None
    topic_words = set(topic.lower().split())
    best_id = None
    best_score = 0.0
    for s in safe:
        suggestion_words = set(s["text"].lower().split())
        if not suggestion_words:
            continue
        overlap = len(topic_words & suggestion_words)
        score = overlap / len(suggestion_words)
        if score > best_score:
            best_score = score
            best_id = s["id"]
    return best_id if best_score >= threshold else None
