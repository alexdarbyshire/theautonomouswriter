import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent.evolve import reflect_and_evolve
from agent.hugo import validate_and_fix
from agent.images import generate_cover_image
from agent.llm import LLMUnavailableError, OpenRouterClient
from agent.memory import load_memory, save_memory
from agent.bluesky import post_to_bluesky
from agent.researcher import research_topic
from agent.scheduler import next_post_time, should_post
from agent.validator import run_all_checks

SITE_DIR = Path(__file__).resolve().parent.parent / "site"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "system" / "prompts"
POSTS_DIR = Path(__file__).resolve().parent.parent / "site" / "content" / "posts"


def main() -> None:
    # 1. Schedule check
    memory = load_memory()
    force = os.environ.get("FORCE_POST", "").lower() == "true"
    if force:
        logger.info("FORCE_POST set — skipping schedule check")
    elif not should_post(memory):
        logger.info("Not time to post yet. Next scheduled: %s", memory.get("next_scheduled_post"))
        sys.exit(0)

    logger.info("Schedule check passed — proceeding to write")

    # 2. Context assembly
    system_prompt = (PROMPTS_DIR / "system.md").read_text()
    frontmatter_prompt = (PROMPTS_DIR / "frontmatter.md").read_text()

    past_topics = memory.get("past_topics", [])
    past_slugs = memory.get("past_slugs", [])
    mood = memory.get("current_persona_mood", "curious")

    # 3. Research (feature-flagged)
    # Research happens after topic selection — we need a topic first

    # 4. Topic selection
    llm = OpenRouterClient()

    topic_prompt = (
        f"You are a blog topic selector. Your current mood is: {mood}\n\n"
        f"Previously written topics (do NOT repeat these):\n"
        + ("\n".join(f"- {t}" for t in past_topics) if past_topics else "- (none yet, this is the first post)")
        + "\n\nSuggest ONE new blog topic. Reply with ONLY the topic as a short phrase, nothing else."
    )

    try:
        topic = llm.select_topic(system_prompt, topic_prompt).strip().strip('"')
        logger.info("Selected topic: %s", topic)
    except LLMUnavailableError as e:
        logger.error("Failed to select topic: %s", e)
        sys.exit(1)

    # 3. Research (now that we have a topic)
    research_context = research_topic(topic)

    # 5. Draft article
    draft_prompt = f"Write a blog post about: {topic}\n\n"
    if research_context:
        draft_prompt += "Here is some current research context to inform your writing (use these sources where relevant):\n"
        for i, src in enumerate(research_context, 1):
            draft_prompt += f"{i}. [{src['title']}]({src['url']}): {src['content']}\n"
        draft_prompt += (
            "\nIf you draw on any of these sources, include a '## References' section "
            "at the end of your post with markdown links to the sources you actually used. "
            "Only cite sources you genuinely referenced in your writing.\n\n"
        )
    draft_prompt += (
        f"Your current mood/style: {mood}\n"
        f"Remember: minimum 400 words, use ## headings, no placeholders, no empty sections."
    )

    try:
        body = llm.draft_article(system_prompt, draft_prompt)
        logger.info("Article drafted (%d words)", len(body.split()))
    except LLMUnavailableError as e:
        logger.error("Failed to draft article: %s", e)
        sys.exit(1)

    # 6. Frontmatter extraction (separate LLM call)
    try:
        frontmatter_raw = llm.extract_frontmatter(body, frontmatter_prompt)
        # Strip markdown fences if the model included them despite instructions
        frontmatter_raw = frontmatter_raw.strip()
        if frontmatter_raw.startswith("```"):
            frontmatter_raw = frontmatter_raw.split("\n", 1)[1]
            if frontmatter_raw.endswith("```"):
                frontmatter_raw = frontmatter_raw[:-3]
        frontmatter_data = json.loads(frontmatter_raw)
        logger.info("Frontmatter extracted: %s", frontmatter_data.get("title"))
    except LLMUnavailableError as e:
        logger.error("Failed to extract frontmatter: %s", e)
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse frontmatter JSON: %s\nRaw: %s", e, frontmatter_raw)
        sys.exit(1)

    # Override date with actual system date — LLM can hallucinate the date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    frontmatter_data["date"] = today

    # 7. Validation
    slug = frontmatter_data.get("slug", "")
    passed, reason = run_all_checks(slug, body, frontmatter_data, past_slugs)
    if not passed:
        logger.error("Validation failed: %s", reason)
        sys.exit(1)
    logger.info("All validation checks passed")

    # 7b. Cover image generation (feature-flagged, non-critical)
    cover_image_bytes = generate_cover_image(
        llm, frontmatter_data["title"], frontmatter_data["description"], mood,
    )

    # 8. Filesystem write
    date_str = frontmatter_data["date"]
    POSTS_DIR.mkdir(parents=True, exist_ok=True)

    if cover_image_bytes:
        # Page bundle: directory with index.md + images/cover.png
        post_dir = POSTS_DIR / f"{date_str}-{slug}"
        post_dir.mkdir(parents=True, exist_ok=True)
        post_path = post_dir / "index.md"
        img_dir = post_dir / "images"
        img_dir.mkdir(exist_ok=True)
        (img_dir / "cover.png").write_bytes(cover_image_bytes)
        logger.info("Cover image saved (%d bytes)", len(cover_image_bytes))
    else:
        # Flat file (existing behavior)
        post_path = POSTS_DIR / f"{date_str}-{slug}.md"

    # Compose the full markdown file with YAML frontmatter
    # Use JSON-style values for title/description to avoid YAML quoting issues
    fm = {
        "title": frontmatter_data["title"],
        "date": str(frontmatter_data["date"]),
        "slug": slug,
        "description": frontmatter_data["description"],
        "tags": frontmatter_data["tags"],
        "draft": False,
    }
    if cover_image_bytes:
        fm["cover"] = {
            "image": "images/cover.png",
            "alt": frontmatter_data["description"],
        }
    # json.dumps handles all escaping; YAML is a superset of JSON
    frontmatter_yaml = "---\n"
    for key, value in fm.items():
        frontmatter_yaml += f"{key}: {json.dumps(value, ensure_ascii=False)}\n"
    frontmatter_yaml += "---\n\n"

    post_content = frontmatter_yaml + body
    post_path.write_text(post_content)
    logger.info("Post written to %s", post_path)

    # 8b. Hugo build validation with fix loop
    if not validate_and_fix(post_path, SITE_DIR, llm):
        logger.error("Hugo validation failed after fix attempts")
        sys.exit(1)

    # 8c. Social posting (feature-flagged, non-critical)
    post_to_bluesky(
        title=frontmatter_data["title"],
        description=frontmatter_data["description"],
        slug=slug,
        llm=llm,
        mood=mood,
    )

    # 9. Reflection — the writer evolves its mood and records a reflection
    evolution = reflect_and_evolve(body, memory, llm)
    if evolution.get("mood"):
        memory["current_persona_mood"] = evolution["mood"]
    if evolution.get("reflection"):
        reflections = memory.get("past_reflections", [])
        reflections.append(evolution["reflection"])
        memory["past_reflections"] = reflections

    # 10. Memory update
    now = datetime.now(timezone.utc)
    memory["past_topics"].append(topic)
    memory["past_slugs"].append(slug)
    memory["last_run_timestamp"] = now.isoformat()
    memory["last_post_timestamp"] = now.isoformat()
    memory["next_scheduled_post"] = next_post_time().isoformat()
    memory["total_posts_written"] = memory.get("total_posts_written", 0) + 1
    memory["consecutive_skip_count"] = 0
    save_memory(memory)
    logger.info("Memory updated. Mood: %s. Next post: %s", memory["current_persona_mood"], memory["next_scheduled_post"])


if __name__ == "__main__":
    main()
