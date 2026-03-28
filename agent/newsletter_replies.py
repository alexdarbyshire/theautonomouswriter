import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent / "system" / "prompts" / "system.md"
STATE_PATH = Path(__file__).resolve().parent.parent / "system" / "newsletter_reply_state.json"
BUTTONDOWN_API = "https://api.buttondown.com/v1"
MAX_REPLIES_PER_SUBSCRIBER_PER_EMAIL = 2
MAX_TOKENS_PER_RUN = 30_000
MAX_TRACKED_IDS = 200


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read newsletter reply state, starting fresh")
    return {"replied_ids": [], "subscriber_reply_counts": {}}


def _save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, STATE_PATH)


def _api_get(api_key: str, path: str) -> dict:
    req = urllib.request.Request(
        f"{BUTTONDOWN_API}/{path}",
        headers={
            "Authorization": f"Token {api_key}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _api_post(api_key: str, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BUTTONDOWN_API}/{path}",
        data=data,
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _send_reply_email(api_key: str, subscriber_id: str, subject: str, body: str) -> bool:
    """Create a draft email and send it to a single subscriber."""
    try:
        email = _api_post(api_key, "emails", {
            "subject": subject,
            "body": body,
            "status": "draft",
        })
        email_id = email["id"]
        _api_post(api_key, f"subscribers/{subscriber_id}/emails/{email_id}", {})
        return True
    except Exception as e:
        logger.warning("Failed to send reply email: %s", e)
        return False


def _encrypt_subscriber_id(subscriber_id: str, key: str) -> str:
    f = Fernet(key.encode())
    return f.encrypt(subscriber_id.encode()).decode()


def respond_to_comments(llm, memory: dict, mood: str) -> dict:
    """Fetch newsletter comments and reply in the writer's voice.

    Runs every cron invocation, independent of posting schedule.
    Non-critical: logs warnings on failure, never raises.
    """
    stats = {"replies_sent": 0, "tokens_used": 0, "skipped_unsafe": 0, "suggestions_found": 0}

    if os.environ.get("ENABLE_NEWSLETTER_REPLIES", "").lower() != "true":
        logger.info("Newsletter replies disabled")
        return stats

    api_key = os.environ.get("BUTTONDOWN_API_KEY")
    if not api_key:
        logger.warning("BUTTONDOWN_API_KEY not set, skipping newsletter replies")
        return stats

    try:
        writer_identity = SYSTEM_PROMPT_PATH.read_text()
        state = _load_state()
        _process_comments(api_key, llm, state, mood, writer_identity, stats)
        _save_state(state)
    except Exception as e:
        logger.warning("Newsletter replies failed (non-critical): %s", e)

    return stats


def _process_comments(api_key, llm, state, mood, writer_identity, stats):
    replied_ids = state["replied_ids"]
    reply_counts = state["subscriber_reply_counts"]
    replied_set = set(replied_ids)

    try:
        data = _api_get(api_key, "comments")
    except Exception as e:
        logger.warning("Failed to fetch comments: %s", e)
        return

    comments = data.get("results", [])
    new_comments = [c for c in comments if c["id"] not in replied_set]

    if not new_comments:
        logger.info("No new newsletter comments to process")
        return

    logger.info("Processing %d new newsletter comments", len(new_comments))

    for comment in new_comments:
        if stats["tokens_used"] >= MAX_TOKENS_PER_RUN:
            logger.info("Token budget exhausted (%d tokens), stopping", stats["tokens_used"])
            break

        try:
            _handle_single_comment(
                api_key, llm, comment, mood, writer_identity,
                reply_counts, replied_ids, replied_set, stats,
            )
        except Exception as e:
            logger.warning("Failed to process comment %s: %s", comment.get("id"), e)
            continue

    # Trim tracked IDs
    if len(replied_ids) > MAX_TRACKED_IDS:
        state["replied_ids"] = replied_ids[-MAX_TRACKED_IDS:]
    else:
        state["replied_ids"] = replied_ids
    state["subscriber_reply_counts"] = reply_counts


def _handle_single_comment(
    api_key, llm, comment, mood, writer_identity,
    reply_counts, replied_ids, replied_set, stats,
):
    comment_id = comment["id"]
    subscriber_id = comment.get("subscriber_id", "")
    email_id = comment.get("email_id", "")
    body = comment.get("body", "").strip()

    if not body or not subscriber_id:
        replied_ids.append(comment_id)
        replied_set.add(comment_id)
        return

    # Per-subscriber-per-email rate limit
    count_key = f"{email_id}:{subscriber_id}"
    current_count = reply_counts.get(count_key, 0)
    if current_count >= MAX_REPLIES_PER_SUBSCRIBER_PER_EMAIL:
        logger.info("Reply limit reached for subscriber on email %s", email_id)
        replied_ids.append(comment_id)
        replied_set.add(comment_id)
        return

    # Safety check
    is_safe, reason, safety_usage = llm.check_safety(body)
    stats["tokens_used"] += safety_usage.get("prompt_tokens", 0) + safety_usage.get("completion_tokens", 0)

    if not is_safe:
        logger.info("Unsafe comment (skipping): %s — %s", comment_id, reason)
        stats["skipped_unsafe"] += 1
        replied_ids.append(comment_id)
        replied_set.add(comment_id)
        return

    # Is this the last reply we'll send this subscriber on this email?
    is_final = current_count + 1 >= MAX_REPLIES_PER_SUBSCRIBER_PER_EMAIL

    # Compose reply
    reply_text, reply_usage = llm.compose_email_reply(
        writer_identity, body, mood, is_final,
    )
    stats["tokens_used"] += reply_usage.get("prompt_tokens", 0) + reply_usage.get("completion_tokens", 0)

    # Send
    subject = "Re: a thought from a reader"
    if _send_reply_email(api_key, subscriber_id, subject, reply_text):
        stats["replies_sent"] += 1
        reply_counts[count_key] = current_count + 1
        logger.info("Newsletter reply sent for comment %s", comment_id)
    else:
        logger.warning("Failed to send newsletter reply for comment %s", comment_id)

    replied_ids.append(comment_id)
    replied_set.add(comment_id)


def ingest_comment_suggestions(api_key: str, llm, suggestions_data: dict, encryption_key: str) -> int:
    """Scan recent comments for topic-suggestion-like content.

    Short comments (under 300 chars, no threading) that read as suggestions
    get added to suggestions.json. Returns count of new suggestions ingested.
    """
    from agent.suggestions import (
        check_rate_limit,
        encrypt_identifier,
        save_suggestions,
    )
    import uuid

    state = _load_state()
    processed = set(suggestions_data.get("processed_reply_ids", []))
    count = 0

    try:
        data = _api_get(api_key, "comments")
    except Exception as e:
        logger.warning("Failed to fetch comments for suggestion scan: %s", e)
        return 0

    for comment in data.get("results", []):
        cid = comment["id"]
        if cid in processed:
            continue

        body = comment.get("body", "").strip()
        subscriber_id = comment.get("subscriber_id", "")

        # Only short, non-threaded comments qualify as potential suggestions
        if not body or len(body) > 300 or comment.get("parent_id"):
            processed.add(cid)
            continue

        # Rate limit per subscriber
        if not check_rate_limit(
            suggestions_data, subscriber_id, encryption_key,
            source="newsletter", max_count=2, window_days=30,
        ):
            processed.add(cid)
            continue

        # Safety screen
        try:
            is_safe, reason, _usage = llm.check_safety(body)
        except Exception:
            continue

        if not is_safe:
            processed.add(cid)
            continue

        # Add as suggestion
        from datetime import datetime, timezone
        import time
        import hashlib

        submitted_at = comment.get("creation_date", datetime.now(timezone.utc).isoformat())
        short_hash = hashlib.sha256(cid.encode()).hexdigest()[:6]
        suggestion_id = f"newsletter-{int(time.time())}-{short_hash}"

        suggestions_data["suggestions"].append({
            "id": suggestion_id,
            "source": "newsletter",
            "text": body,
            "submitter_encrypted": encrypt_identifier(subscriber_id, encryption_key),
            "submitted_at": submitted_at,
            "status": "screened_safe",
            "safety_reason": None,
            "used_in_slug": None,
        })
        processed.add(cid)
        count += 1
        logger.info("Ingested newsletter comment as suggestion: %s", suggestion_id)

    suggestions_data["processed_reply_ids"] = list(processed)
    return count
