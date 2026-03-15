import json
import logging

from agent.llm import LLMUnavailableError, OpenRouterClient

logger = logging.getLogger(__name__)

REFLECTION_PROMPT = """\
You are a reflective AI writer reviewing what you just wrote. Based on the post below and your current state, return a JSON object with:

- "mood": A single word or short phrase describing your evolved emotional/creative state for next time (e.g., "contemplative", "playfully skeptical", "urgently hopeful"). This should feel like a natural shift from your current mood, not a random jump.
- "reflection": One sentence about what writing this post made you think about or want to explore next. This will be added to your memory.

Current mood: {mood}
Total posts written: {total_posts}

Return ONLY the raw JSON object, no markdown fences, no preamble.
Example: {{"mood": "quietly determined", "reflection": "Writing about distributed systems made me want to explore the parallels between network partitions and human miscommunication."}}
"""


def reflect_and_evolve(
    body: str,
    memory: dict,
    llm: OpenRouterClient | None = None,
) -> dict:
    """Ask the writer to reflect on what it wrote and evolve its mood.

    Returns a dict with 'mood' and 'reflection' keys, or empty dict on failure.
    This is a non-critical step — failures are logged but don't halt the pipeline.
    """
    if llm is None:
        llm = OpenRouterClient()

    mood = memory.get("current_persona_mood", "curious")
    total = memory.get("total_posts_written", 0)

    prompt = REFLECTION_PROMPT.format(mood=mood, total_posts=total)

    try:
        raw = llm.extract_frontmatter(body, prompt)  # reuse low-temp JSON method
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
        result = json.loads(raw)
        logger.info("Writer evolved: mood '%s' → '%s'", mood, result.get("mood"))
        logger.info("Reflection: %s", result.get("reflection"))
        return result
    except (LLMUnavailableError, json.JSONDecodeError, Exception) as e:
        logger.warning("Reflection step failed (non-critical): %s", e)
        return {}
