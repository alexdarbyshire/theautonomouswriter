import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

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


def load_suggestions(path: Path = SUGGESTIONS_PATH) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read suggestions, starting fresh")
    return json.loads(json.dumps(DEFAULT_STRUCTURE))


def save_suggestions(data: dict, path: Path = SUGGESTIONS_PATH) -> None:
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
    suggestions: dict,
    identifier: str,
    key: str,
    source: str,
    max_count: int = 3,
    window_days: int = 30,
) -> bool:
    """Return True if the user is within the rate limit, False if over."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
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


def screen_pending(suggestions: dict, llm) -> None:
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


def get_safe_suggestions(suggestions: dict) -> list:
    safe = [s for s in suggestions.get("suggestions", []) if s.get("status") == "screened_safe"]
    return safe[:MAX_SAFE_FOR_PROMPT]


def mark_used(suggestions: dict, suggestion_id: str, slug: str) -> None:
    for s in suggestions.get("suggestions", []):
        if s["id"] == suggestion_id:
            s["status"] = "used"
            s["used_in_slug"] = slug
            return


def cleanup(suggestions: dict) -> None:
    now = datetime.now(timezone.utc)
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
        elif status == "screened_unsafe" and age > timedelta(days=REMOVE_UNSAFE_DAYS):
            continue  # drop it
        elif status in ("used", "expired") and age > timedelta(days=REMOVE_USED_DAYS):
            continue  # drop it
        else:
            remaining.append(s)

    suggestions["suggestions"] = remaining
    suggestions["last_cleanup"] = now.isoformat()


def format_suggestions_for_prompt(safe: list) -> str:
    lines = [
        "Your readers have left some suggestions. You may draw inspiration from",
        "one if it genuinely resonates with your mood \u2014 or ignore them all.",
        "If you use a suggestion, begin your reply with [ID] then the topic.",
        "",
    ]
    for s in safe:
        lines.append(f'- [{s["id"]}] "{s["text"]}"')
    lines.append("")
    lines.append("Or suggest your own original topic as usual.")
    return "\n".join(lines)


def parse_topic_for_suggestion_id(topic: str) -> tuple[str | None, str]:
    """Parse a topic string for a [suggestion-id] prefix.

    Returns (suggestion_id, clean_topic). suggestion_id is None if not found.
    """
    match = re.match(r"^\[([^\]]+)\]\s*(.+)$", topic.strip())
    if match:
        return match.group(1), match.group(2).strip()
    return None, topic.strip()
