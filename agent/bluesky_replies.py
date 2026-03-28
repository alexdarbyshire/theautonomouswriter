from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import types

    from agent.llm import OpenRouterClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent / "system" / "prompts" / "system.md"
STATE_PATH = Path(__file__).resolve().parent.parent / "system" / "bluesky_state.json"
MAX_REPLIES_PER_THREAD = 3
MAX_TOKENS_PER_RUN = 50_000
MAX_TRACKED_URIS = 200
GRAPHEME_LIMIT = 300


def _load_state() -> dict:
    """Load Bluesky reply state from its own file."""
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read bluesky state, starting fresh")
    return {"replied_uris": [], "thread_reply_counts": {}}


def _save_state(state: dict) -> None:
    """Atomic write of Bluesky reply state."""
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, STATE_PATH)


def respond_to_mentions(llm: OpenRouterClient, memory: dict, mood: str) -> dict:
    """Process Bluesky replies on own posts and respond where safe.

    Runs every cron invocation (independent of posting schedule).
    Non-critical: logs warnings on failure, never raises.
    Returns stats dict.
    """
    stats = {"replies_sent": 0, "tokens_used": 0, "skipped_unsafe": 0}

    if os.environ.get("ENABLE_BLUESKY_REPLIES", "").lower() != "true":
        logger.info("Bluesky replies disabled (ENABLE_BLUESKY_REPLIES not set to 'true')")
        return stats

    handle = os.environ.get("BLUESKY_HANDLE")
    app_password = os.environ.get("BLUESKY_APP_PASSWORD")
    if not handle or not app_password:
        logger.warning("Bluesky credentials not set, skipping replies")
        return stats

    try:
        from atproto import Client
        from atproto import models as atmodels

        client = Client()
        profile = client.login(handle, app_password)
        my_did = profile.did

        writer_identity = SYSTEM_PROMPT_PATH.read_text()
        state = _load_state()
        result = _process_notifications(
            client,
            my_did,
            llm,
            state,
            mood,
            writer_identity,
            atmodels,
            stats,
        )
        _save_state(state)
        return result
    except Exception as e:
        logger.warning("Bluesky replies failed (non-critical): %s", e)
        return stats


def _process_notifications(
    client: Any,
    my_did: str,
    llm: OpenRouterClient,
    state: dict,
    mood: str,
    writer_identity: str,
    atmodels: types.ModuleType,
    stats: dict,
) -> dict:
    """Fetch and process reply notifications."""
    replied_uris = state["replied_uris"]
    thread_counts = state["thread_reply_counts"]
    replied_set = set(replied_uris)

    try:
        response = client.app.bsky.notification.list_notifications({"limit": 50})
    except Exception as e:
        logger.warning("Failed to fetch notifications: %s", e)
        return stats

    notifications = response.notifications or []
    reply_notifications = [n for n in notifications if n.reason == "reply" and n.uri not in replied_set]

    if not reply_notifications:
        logger.info("No new reply notifications to process")
        return stats

    logger.info("Processing %d reply notifications", len(reply_notifications))

    for notification in reply_notifications:
        if stats["tokens_used"] >= MAX_TOKENS_PER_RUN:
            logger.info("Token budget exhausted (%d tokens), stopping", stats["tokens_used"])
            break

        try:
            _handle_single_reply(
                client,
                my_did,
                llm,
                notification,
                mood,
                writer_identity,
                atmodels,
                thread_counts,
                replied_uris,
                replied_set,
                stats,
            )
        except Exception as e:
            logger.warning("Failed to process notification %s: %s", notification.uri, e)
            continue

    # Trim replied URIs to prevent unbounded growth
    if len(replied_uris) > MAX_TRACKED_URIS:
        state["replied_uris"] = replied_uris[-MAX_TRACKED_URIS:]
    else:
        state["replied_uris"] = replied_uris
    state["thread_reply_counts"] = thread_counts

    return stats


def _handle_single_reply(
    client: Any,
    my_did: str,
    llm: OpenRouterClient,
    notification: Any,
    mood: str,
    writer_identity: str,
    atmodels: types.ModuleType,
    thread_counts: dict,
    replied_uris: list,
    replied_set: set,
    stats: dict,
) -> None:
    """Process a single reply notification."""
    # Get thread to check if it's rooted at our own post
    try:
        thread_resp = client.app.bsky.feed.get_post_thread({"uri": notification.uri, "depth": 0, "parent_height": 10})
    except Exception as e:
        logger.warning("Failed to get thread for %s: %s", notification.uri, e)
        return

    thread = thread_resp.thread
    if not hasattr(thread, "post"):
        return

    # Walk up to find the root post
    root_uri = _find_root_uri(thread)
    if not root_uri:
        return

    # Only reply to threads rooted at our own posts
    if not root_uri.startswith(f"at://{my_did}/"):
        logger.debug("Skipping reply not on own post: %s", notification.uri)
        replied_uris.append(notification.uri)
        replied_set.add(notification.uri)
        return

    # Check per-thread reply limit
    thread_count = thread_counts.get(root_uri, 0)
    if thread_count >= MAX_REPLIES_PER_THREAD:
        logger.info("Thread reply limit reached for %s", root_uri)
        replied_uris.append(notification.uri)
        replied_set.add(notification.uri)
        return

    # Extract the incoming message text
    incoming_text = _extract_post_text(thread.post)
    if not incoming_text:
        return

    # Safety check via Llama Guard
    is_safe, reason, safety_usage = llm.check_safety(incoming_text)
    stats["tokens_used"] += safety_usage.get("prompt_tokens", 0) + safety_usage.get("completion_tokens", 0)

    if not is_safe:
        logger.info("Unsafe reply detected (skipping): %s — %s", notification.uri, reason)
        stats["skipped_unsafe"] += 1
        replied_uris.append(notification.uri)
        replied_set.add(notification.uri)
        return

    # Build thread context for the writer
    thread_context = _build_thread_context(thread, my_did)

    # If this is the last allowed reply, tell the writer to wrap up warmly
    is_final_reply = thread_count + 1 >= MAX_REPLIES_PER_THREAD
    if is_final_reply:
        thread_context += (
            "\n\n[This is your last reply in this thread. "
            "Close it naturally in your own voice — "
            "you might leave them with something to sit with, or simply say goodbye as you would.]"
        )

    # Compose reply
    reply_text, reply_usage = llm.compose_reply(writer_identity, thread_context, mood)
    stats["tokens_used"] += reply_usage.get("prompt_tokens", 0) + reply_usage.get("completion_tokens", 0)

    # Truncate to Bluesky limit
    if len(reply_text) > GRAPHEME_LIMIT:
        reply_text = reply_text[: GRAPHEME_LIMIT - 3].rstrip() + "..."

    # Build reply reference
    parent_ref = atmodels.ComAtprotoRepoStrongRef.Main(
        uri=notification.uri,
        cid=notification.cid,
    )
    # Root is the top-level post in the thread
    root_ref = _build_root_ref(thread, atmodels) or parent_ref

    reply_ref = atmodels.AppBskyFeedPost.ReplyRef(
        parent=parent_ref,
        root=root_ref,
    )

    # Post the reply
    from atproto import client_utils

    text = client_utils.TextBuilder().text(reply_text)
    post_resp = client.send_post(text, reply_to=reply_ref)
    logger.info("Reply posted: %s", post_resp.uri)

    # Track
    stats["replies_sent"] += 1
    replied_uris.append(notification.uri)
    replied_set.add(notification.uri)
    thread_counts[root_uri] = thread_count + 1


def _find_root_uri(thread: Any) -> str | None:
    """Walk up the thread to find the root post URI."""
    current = thread
    while hasattr(current, "parent") and current.parent and hasattr(current.parent, "post"):
        current = current.parent
    if hasattr(current, "post"):
        return current.post.uri
    return None


def _build_root_ref(thread: Any, atmodels: types.ModuleType) -> Any | None:
    """Build a StrongRef for the root post of the thread."""
    current = thread
    while hasattr(current, "parent") and current.parent and hasattr(current.parent, "post"):
        current = current.parent
    if hasattr(current, "post"):
        return atmodels.ComAtprotoRepoStrongRef.Main(
            uri=current.post.uri,
            cid=current.post.cid,
        )
    return None


def _extract_post_text(post: Any) -> str:
    """Extract text content from a post record."""
    if hasattr(post, "record") and hasattr(post.record, "text"):
        return post.record.text
    return ""


def _build_thread_context(thread: Any, my_did: str) -> str:
    """Build a readable string of the thread conversation."""
    posts: list[tuple[str, str, str]] = []
    _collect_thread_posts(thread, posts)

    lines = []
    for _uri, author, text in posts:
        label = "You" if author == my_did else f"@{author.split(':')[-1][:20]}"
        lines.append(f"[{label}]: {text}")

    return "\n".join(lines) if lines else "(empty thread)"


def _collect_thread_posts(thread: Any, posts: list[tuple[str, str, str]], depth: int = 0) -> None:
    """Recursively collect posts walking up the parent chain for chronological order."""
    if depth > 10:  # safety limit
        return
    if hasattr(thread, "parent") and thread.parent and hasattr(thread.parent, "post"):
        _collect_thread_posts(thread.parent, posts, depth + 1)
    if hasattr(thread, "post"):
        post = thread.post
        author = post.author.did if hasattr(post.author, "did") else ""
        text = _extract_post_text(post)
        if text:
            posts.append((post.uri, author, text))
