import json
import logging
import re
import subprocess
from pathlib import Path

from agent.llm import OpenRouterClient

logger = logging.getLogger(__name__)


def validate_and_fix(post_path: Path, site_dir: Path, llm: OpenRouterClient, max_attempts: int = 3) -> bool:
    """Run Hugo build, use LLM to fix frontmatter on failure.

    Returns True if the build succeeds (possibly after fixes), False otherwise.
    """
    for attempt in range(1, max_attempts + 1):
        logger.info("Hugo build attempt %d/%d", attempt, max_attempts)
        try:
            result = subprocess.run(
                ["hugo", "--gc", "--minify"],
                cwd=site_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            logger.warning("Hugo not found, skipping build validation")
            return True

        if result.returncode == 0:
            logger.info("Hugo build validation passed")
            return True

        stderr = result.stderr
        logger.warning("Hugo build failed (attempt %d):\n%s", attempt, stderr)

        if attempt == max_attempts:
            logger.error("Hugo validation failed after %d attempts", max_attempts)
            return False

        # Try LLM-based fix
        content = post_path.read_text()
        parts = _split_post(content)
        if parts is None:
            logger.error("Could not find frontmatter delimiters in %s", post_path)
            return False

        fm_str, body = parts
        try:
            fixed_json = llm.fix_frontmatter(fm_str, stderr)
            fm_dict = json.loads(fixed_json)
        except Exception as e:
            logger.error("LLM frontmatter fix failed: %s", e)
            return False

        post_path.write_text(_rebuild_post(fm_dict, body))
        logger.info("Frontmatter rewritten by LLM for %s", post_path.name)

    return False


def _split_post(content: str) -> tuple[str, str] | None:
    """Split a post into (frontmatter_str, body_str).

    Returns None if no frontmatter delimiters found.
    """
    match = re.match(r"^---\n(.*?\n)---\n(.*)", content, re.DOTALL)
    if not match:
        return None
    return match.group(1), match.group(2)


def _rebuild_post(fm_dict: dict, body: str) -> str:
    """Serialize a frontmatter dict + body into a full post string."""
    frontmatter_yaml = "---\n"
    for key, value in fm_dict.items():
        frontmatter_yaml += f"{key}: {json.dumps(value, ensure_ascii=False)}\n"
    frontmatter_yaml += "---\n"
    # Ensure there's a blank line between frontmatter and body
    if not body.startswith("\n"):
        frontmatter_yaml += "\n"
    return frontmatter_yaml + body
