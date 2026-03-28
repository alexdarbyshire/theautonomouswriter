"""Append a pre-screened suggestion to system/suggestions.json.

Called by the ingest-suggestion workflow after Llama Guard screening.
Enforces durable rate limit (3 per user per 30 days) by decrypting
existing entries.
"""
import os
import secrets
import sys
from datetime import datetime, timezone

from agent.suggestions import (
    check_rate_limit,
    load_suggestions,
    save_suggestions,
)

MAX_PER_USER = 3
WINDOW_DAYS = 30


def main() -> None:
    if len(sys.argv) != 5:
        print(
            "Usage: append_suggestion.py <source> <text> <submitted_at> <submitter_encrypted>",
            file=sys.stderr,
        )
        sys.exit(2)

    source = sys.argv[1]
    text = sys.argv[2]
    submitted_at = sys.argv[3]
    submitter_encrypted = sys.argv[4]

    key = os.environ.get("SUGGESTION_ENCRYPTION_KEY", "")
    if not key:
        print("SUGGESTION_ENCRYPTION_KEY not set", file=sys.stderr)
        sys.exit(1)

    suggestions = load_suggestions()

    # Durable rate limit: decrypt existing entries to count by this user
    # We need the plaintext identifier to compare, so decrypt the incoming token
    from agent.suggestions import decrypt_identifier
    try:
        identifier = decrypt_identifier(submitter_encrypted, key)
    except Exception as e:
        print(f"Failed to decrypt submitter identifier: {e}", file=sys.stderr)
        sys.exit(1)

    if not check_rate_limit(suggestions, identifier, key, source, MAX_PER_USER, WINDOW_DAYS):
        print(f"Rate limit exceeded for user (max {MAX_PER_USER} per {WINDOW_DAYS} days)", file=sys.stderr)
        sys.exit(1)

    ts = int(datetime.fromisoformat(submitted_at).timestamp())
    suggestion_id = f"{source}-{ts}-{secrets.token_hex(3)}"

    entry = {
        "id": suggestion_id,
        "source": source,
        "text": text,
        "submitter_encrypted": submitter_encrypted,
        "submitted_at": submitted_at,
        "status": "screened_safe",
        "safety_reason": None,
        "used_in_slug": None,
    }

    suggestions["suggestions"].append(entry)
    save_suggestions(suggestions)
    print(f"Appended suggestion {suggestion_id}")


if __name__ == "__main__":
    main()
