from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.llm import OpenRouterClient
    from agent.types import PostMetadata, WriterMemory

logger = logging.getLogger(__name__)

POSTS_DIR = Path(__file__).resolve().parent.parent / "site" / "content" / "posts"
BASE_URL = "https://theautonomouswriter.com/posts/"
BUTTONDOWN_API = "https://api.buttondown.com/v1/emails"
RECAP_EVERY_N_POSTS = 3


def _get_api_config() -> tuple[str, str] | None:
    """Return (api_key, username) if newsletter is fully configured, else None."""
    if os.environ.get("ENABLE_NEWSLETTER", "").lower() != "true":
        logger.info("Newsletter disabled (ENABLE_NEWSLETTER not set to 'true')")
        return None
    api_key = os.environ.get("BUTTONDOWN_API_KEY")
    if not api_key:
        logger.warning("BUTTONDOWN_API_KEY not set, skipping newsletter")
        return None
    username = os.environ.get("BUTTONDOWN_USERNAME", "")
    return api_key, username


def _send_email(api_key: str, subject: str, body: str) -> None:
    """Send an email via Buttondown API. Raises on failure."""
    payload = json.dumps(
        {
            "subject": subject,
            "body": body,
            "status": "about_to_send",
        }
    ).encode()
    req = urllib.request.Request(
        BUTTONDOWN_API,
        data=payload,
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
            "X-Buttondown-Live-Dangerously": "true",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status >= 300:
            raise urllib.error.HTTPError(BUTTONDOWN_API, resp.status, resp.read().decode(), resp.headers, None)
    logger.info("Buttondown email sent: %s", subject)


def notify_new_post(title: str, description: str, slug: str) -> bool:
    """Send a short per-post notification email. Non-critical."""
    config = _get_api_config()
    if not config:
        return False

    api_key, _ = config
    url = f"{BASE_URL}{slug}/"
    subject = title
    body = (
        f"{description}\n\n[Read the full post]({url})"
        "\n\n---\n*Have a topic you'd like me to explore? Just reply to this email.*"
    )

    try:
        _send_email(api_key, subject, body)
        return True
    except Exception as e:
        logger.warning("Post notification email failed (non-critical): %s", e)
        return False


def _get_recent_posts(n: int) -> list[PostMetadata]:
    """Read the N most recent posts from the filesystem."""
    if not POSTS_DIR.exists():
        return []

    # Collect all post entries (dirs with index.md or standalone .md files)
    entries = []
    for item in sorted(POSTS_DIR.iterdir(), reverse=True):
        if item.is_dir() and (item / "index.md").exists():
            entries.append(item / "index.md")
        elif item.is_file() and item.suffix == ".md":
            entries.append(item)
        if len(entries) >= n:
            break

    posts = []
    for path in entries:
        text = path.read_text()
        # Quick frontmatter parse — extract between --- delimiters
        if not text.startswith("---"):
            continue
        end = text.index("---", 3)
        fm_text = text[3:end]
        # Extract fields via simple line parsing (values are JSON-encoded)
        post = {}
        for line in fm_text.strip().splitlines():
            if ": " in line:
                key, val = line.split(": ", 1)
                try:
                    post[key.strip()] = json.loads(val.strip())
                except json.JSONDecodeError:
                    post[key.strip()] = val.strip()
        if "title" in post and "slug" in post:
            post["url"] = f"{BASE_URL}{post['slug']}/"
            posts.append(post)

    return posts


def maybe_send_recap(memory: WriterMemory, llm: OpenRouterClient, system_prompt: str) -> bool:
    """Send a recap newsletter if enough posts have accumulated. Non-critical."""
    config = _get_api_config()
    if not config:
        return False

    api_key, _ = config
    total = memory.get("total_posts_written", 0)
    last_sent_at = memory.get("last_newsletter_at_post_count", 0)

    if total - last_sent_at < RECAP_EVERY_N_POSTS:
        logger.info(
            "Not enough posts for recap (%d since last newsletter)",
            total - last_sent_at,
        )
        return False

    try:
        recent = _get_recent_posts(RECAP_EVERY_N_POSTS)
        if not recent:
            logger.warning("No recent posts found for recap")
            return False

        mood = memory.get("current_persona_mood", "curious")
        post_list = "\n".join(f"- [{p['title']}]({p['url']}): {p.get('description', '')}" for p in recent)
        # Pass recent reflections so the writer can draw on its inner thoughts
        all_reflections = memory.get("past_reflections", [])
        recent_reflections = all_reflections[-RECAP_EVERY_N_POSTS:] if all_reflections else None

        newsletter_json = llm.compose_newsletter(
            system_prompt,
            post_list,
            mood,
            recent_reflections,
        )
        # Parse JSON response
        newsletter_json = newsletter_json.strip()
        if newsletter_json.startswith("```"):
            newsletter_json = newsletter_json.split("\n", 1)[1]
            if newsletter_json.endswith("```"):
                newsletter_json = newsletter_json[:-3]
        data = json.loads(newsletter_json)
        subject = data["subject"]
        body = data["body"]

        _send_email(api_key, subject, body)
        memory["last_newsletter_at_post_count"] = total
        logger.info("Recap newsletter sent: %s", subject)
        return True
    except Exception as e:
        logger.warning("Recap newsletter failed (non-critical): %s", e)
        return False
