from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.llm import OpenRouterClient

logger = logging.getLogger(__name__)

BASE_URL = "https://theautonomouswriter.com/posts/"
GRAPHEME_LIMIT = 300


def post_to_bluesky(
    title: str,
    description: str,
    slug: str,
    llm: OpenRouterClient | None = None,
    mood: str = "",
) -> bool:
    if os.environ.get("ENABLE_BLUESKY", "").lower() != "true":
        logger.info("Bluesky disabled (ENABLE_BLUESKY not set to 'true')")
        return False

    handle = os.environ.get("BLUESKY_HANDLE")
    app_password = os.environ.get("BLUESKY_APP_PASSWORD")
    if not handle or not app_password:
        logger.warning("BLUESKY_HANDLE or BLUESKY_APP_PASSWORD not set, skipping")
        return False

    try:
        from atproto import Client, client_utils

        url = f"{BASE_URL}{slug}/"
        announcement = _generate_announcement(title, description, mood, llm)
        announcement = _truncate_announcement(announcement, url)
        text = client_utils.TextBuilder().text(announcement + "\n\n").link(url, url)

        client = Client()
        client.login(handle, app_password)
        response = client.send_post(text)
        logger.info("Posted to Bluesky: %s", response.uri)
        return True
    except Exception as e:
        logger.warning("Bluesky post failed, continuing without: %s", e)
        return False


def _generate_announcement(
    title: str,
    description: str,
    mood: str,
    llm: OpenRouterClient | None,
) -> str:
    if llm:
        try:
            text = llm.compose_bluesky_post(title, description, mood)
            if text:
                logger.info("LLM-generated Bluesky announcement: %s", text)
                return text
        except Exception as e:
            logger.warning("LLM announcement failed, using fallback: %s", e)
    return f"{title}\n\n{description}"


def _truncate_announcement(announcement: str, url: str) -> str:
    separator = "\n\n"
    max_announcement = GRAPHEME_LIMIT - len(url) - len(separator)
    if len(announcement) > max_announcement:
        announcement = announcement[: max_announcement - 3].rstrip() + "..."
    return announcement
