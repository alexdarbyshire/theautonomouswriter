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
from agent.bluesky_replies import respond_to_mentions
from agent.newsletter import notify_new_post, maybe_send_recap
from agent.newsletter_replies import respond_to_comments, ingest_comment_suggestions
from agent.researcher import research_topic
from agent.scheduler import next_post_time, should_post
from agent.suggestions import (
    cleanup as cleanup_suggestions,
    format_suggestions_for_prompt,
    get_safe_suggestions,
    load_suggestions,
    mark_used,
    match_suggestion,
    save_suggestions,
    screen_pending,
)
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
    # 1. Load memory and context
    memory = load_memory()
    mood = memory.get("current_persona_mood", "curious")

    # 2. Bluesky replies — runs every cron invocation, independent of posting schedule
    try:
        llm = OpenRouterClient()
        reply_stats = respond_to_mentions(llm, memory, mood)
        if reply_stats["replies_sent"] > 0:
            logger.info(
                "Bluesky replies: %d sent, %d tokens, %d skipped unsafe",
                reply_stats["replies_sent"], reply_stats["tokens_used"], reply_stats["skipped_unsafe"],
            )
    except LLMUnavailableError:
        logger.warning("LLM unavailable for Bluesky replies, continuing")
        llm = None

    # 2b. Newsletter replies — runs every cron, before schedule gate
    try:
        if llm is None:
            llm = OpenRouterClient()
        comment_stats = respond_to_comments(llm, memory, mood)
        if comment_stats["replies_sent"] > 0:
            logger.info(
                "Newsletter replies: %d sent, %d tokens, %d skipped unsafe",
                comment_stats["replies_sent"], comment_stats["tokens_used"], comment_stats["skipped_unsafe"],
            )
    except LLMUnavailableError:
        logger.warning("LLM unavailable for newsletter replies, continuing")

    # 3. Schedule check
    force = os.environ.get("FORCE_POST", "").lower() == "true"
    if force:
        logger.info("FORCE_POST set — skipping schedule check")
    elif not should_post(memory):
        logger.info("Not time to post yet. Next scheduled: %s", memory.get("next_scheduled_post"))
        sys.exit(0)

    logger.info("Schedule check passed — proceeding to write")

    # 4. Context assembly
    system_prompt = (PROMPTS_DIR / "system.md").read_text()
    frontmatter_prompt = (PROMPTS_DIR / "frontmatter.md").read_text()

    past_topics = memory.get("past_topics", [])
    past_slugs = memory.get("past_slugs", [])

    # Ensure LLM client is available for the rest of the pipeline
    if llm is None:
        llm = OpenRouterClient()

    # 4b. Suggestion screening (feature-flagged, non-critical)
    suggestions_data = None
    suggestions_context = ""
    if os.environ.get("ENABLE_SUGGESTIONS", "").lower() == "true":
        try:
            suggestions_data = load_suggestions()

            # Ingest newsletter comments as suggestions
            api_key = os.environ.get("BUTTONDOWN_API_KEY", "")
            enc_key = os.environ.get("SUGGESTION_ENCRYPTION_KEY", "")
            if api_key and enc_key and os.environ.get("ENABLE_NEWSLETTER_REPLIES", "").lower() == "true":
                ingested = ingest_comment_suggestions(api_key, llm, suggestions_data, enc_key)
                if ingested:
                    logger.info("Ingested %d newsletter comments as suggestions", ingested)

            screen_pending(suggestions_data, llm)
            safe = get_safe_suggestions(suggestions_data)
            if safe:
                suggestions_context = "\n\n" + format_suggestions_for_prompt(safe)
                logger.info("Loaded %d safe suggestions for topic prompt", len(safe))
        except Exception as e:
            logger.warning("Suggestion processing failed (non-critical): %s", e)

    topic_prompt = (
        f"Your current mood is: {mood}\n\n"
        f"Topics you've already written about (do NOT repeat these):\n"
        + ("\n".join(f"- {t}" for t in past_topics) if past_topics else "- (none yet, this is your first post)")
        + "\n\nWhat do you want to write about next? Reply with ONLY the topic as a short phrase, nothing else."
        + suggestions_context
    )

    try:
        topic = llm.select_topic(system_prompt, topic_prompt).strip().strip('"')
        logger.info("Selected topic: %s", topic)
    except LLMUnavailableError as e:
        logger.error("Failed to select topic: %s", e)
        sys.exit(1)

    # 5b. Check if a reader suggestion inspired the topic (semantic match)
    safe_suggestions = get_safe_suggestions(suggestions_data) if suggestions_data else []
    suggestion_id = match_suggestion(topic, safe_suggestions)
    reader_inspired = False
    if suggestion_id and suggestions_data:
        mark_used(suggestions_data, suggestion_id, "")  # slug filled in after frontmatter
        reader_inspired = True
        logger.info("Topic inspired by suggestion: %s", suggestion_id)

    # 3. Research (now that we have a topic)
    research_context = research_topic(topic)

    # 5. Draft article
    draft_prompt = f"Write a blog post about: {topic}\n\n"
    if reader_inspired:
        draft_prompt += (
            "This topic was sparked by a reader suggestion. If it feels natural, "
            "you might acknowledge that a reader put this idea in your head \u2014 "
            "but only if it serves the piece. Don't force it.\n\n"
        )
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

    # Fill in the slug on the used suggestion now that we have it
    slug = frontmatter_data.get("slug", "")
    if suggestion_id and suggestions_data:
        mark_used(suggestions_data, suggestion_id, slug)

    # 7. Validation
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

    # 10b. Suggestion cleanup
    if suggestions_data is not None:
        try:
            cleanup_suggestions(suggestions_data)
            save_suggestions(suggestions_data)
            logger.info("Suggestions cleaned up and saved")
        except Exception as e:
            logger.warning("Suggestion cleanup failed (non-critical): %s", e)

    # 11. Newsletter (feature-flagged, non-critical)
    notify_new_post(
        title=frontmatter_data["title"],
        description=frontmatter_data["description"],
        slug=slug,
    )
    if maybe_send_recap(memory, llm, system_prompt):
        save_memory(memory)  # persist last_newsletter_at_post_count


if __name__ == "__main__":
    main()
