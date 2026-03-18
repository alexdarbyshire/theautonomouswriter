import logging
import os

logger = logging.getLogger(__name__)

BASE_URL = "https://theautonomouswriter.com/posts/"
GRAPHEME_LIMIT = 300


def post_to_bluesky(title: str, description: str, slug: str) -> bool:
    if os.environ.get("ENABLE_BLUESKY", "").lower() != "true":
        logger.info("Bluesky disabled (ENABLE_BLUESKY not set to 'true')")
        return False

    handle = os.environ.get("BLUESKY_HANDLE")
    app_password = os.environ.get("BLUESKY_APP_PASSWORD")
    if not handle or not app_password:
        logger.warning("BLUESKY_HANDLE or BLUESKY_APP_PASSWORD not set, skipping")
        return False

    try:
        from atproto import Client

        url = f"{BASE_URL}{slug}/"
        text = _compose_text(title, description, url)

        client = Client()
        client.login(handle, app_password)
        response = client.send_post(text)
        logger.info("Posted to Bluesky: %s", response.uri)
        return True
    except Exception as e:
        logger.warning("Bluesky post failed, continuing without: %s", e)
        return False


def _compose_text(title: str, description: str, url: str) -> str:
    separator = "\n\n"
    fixed_len = len(title) + len(url) + len(separator) * 2
    max_desc = GRAPHEME_LIMIT - fixed_len
    if max_desc < 0:
        # Title + URL alone exceed limit; drop description
        return f"{title}{separator}{url}"
    if len(description) > max_desc:
        description = description[: max_desc - 3].rstrip() + "..."
    return f"{title}{separator}{description}{separator}{url}"
