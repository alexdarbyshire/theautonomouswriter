"""One-shot script to backpopulate existing flat-file posts with cover images.

Converts each .md post to a page bundle (directory/index.md + images/cover.png).
Uses the same image generation pipeline as the main agent.

Usage: ENABLE_IMAGES=true uv run python scripts/backpopulate_images.py
"""

import json
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

POSTS_DIR = Path(__file__).resolve().parent.parent / "site" / "content" / "posts"


def extract_frontmatter_field(content: str, field: str) -> str:
    """Extract a field value from YAML frontmatter."""
    match = re.search(rf'^{field}:\s*"?(.*?)"?\s*$', content, re.MULTILINE)
    return match.group(1) if match else ""


def main():
    # Force enable images
    import os
    os.environ["ENABLE_IMAGES"] = "true"

    from agent.images import generate_cover_image
    from agent.llm import OpenRouterClient

    llm = OpenRouterClient()

    # Find all flat .md files (not already page bundles)
    posts = sorted(POSTS_DIR.glob("*.md"))
    logger.info("Found %d flat-file posts to backpopulate", len(posts))

    for post_path in posts:
        content = post_path.read_text()
        title = extract_frontmatter_field(content, "title")
        description = extract_frontmatter_field(content, "description")
        slug = extract_frontmatter_field(content, "slug")

        # Clean escaped quotes from title/description
        title = title.replace('\\"', '"')
        description = description.replace('\\"', '"')

        logger.info("Processing: %s", title)

        cover_bytes = generate_cover_image(llm, title, description, "contemplative")
        if not cover_bytes:
            logger.warning("No image generated for %s, skipping", post_path.name)
            continue

        # Create page bundle directory
        bundle_dir = post_path.with_suffix("")  # removes .md
        bundle_dir.mkdir(exist_ok=True)
        img_dir = bundle_dir / "images"
        img_dir.mkdir(exist_ok=True)

        # Save image
        (img_dir / "cover.png").write_bytes(cover_bytes)
        logger.info("Cover image saved for %s (%d bytes)", slug, len(cover_bytes))

        # Add cover field to frontmatter and move content
        cover_yaml = f'cover: {json.dumps({"image": "images/cover.png", "alt": description}, ensure_ascii=False)}'

        # Insert cover field before the closing ---
        parts = content.split("---", 2)  # ['', frontmatter, body]
        if len(parts) >= 3:
            new_content = f"---{parts[1]}{cover_yaml}\n---{parts[2]}"
        else:
            new_content = content

        # Write as index.md in the bundle
        (bundle_dir / "index.md").write_text(new_content)

        # Remove the old flat file
        post_path.unlink()
        logger.info("Converted %s to page bundle", post_path.name)

    logger.info("Done! Backpopulated %d posts", len(posts))


if __name__ == "__main__":
    main()
