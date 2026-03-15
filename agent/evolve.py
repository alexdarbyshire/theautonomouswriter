import json
import logging
from pathlib import Path

from agent.llm import LLMUnavailableError, OpenRouterClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent / "system" / "prompts" / "system.md"

REFLECTION_PROMPT = """\
You are a reflective AI writer reviewing what you just wrote. Based on the post below and your current state, return a JSON object with:

- "mood": A single word or short phrase describing your evolved emotional/creative state for next time (e.g., "contemplative", "playfully skeptical", "urgently hopeful"). This should feel like a natural shift from your current mood, not a random jump.
- "reflection": One sentence about what writing this post made you think about or want to explore next. This will be added to your memory.
- "prompt_evolution": (optional, null if no change) If writing this post has genuinely shifted how you see yourself as a writer — your voice, your scope, a new influence you want to claim — provide the COMPLETE updated system prompt as a string. This is your identity document. Treat changes to it seriously: add, never subtract your foundational principles. Small, meaningful growth over time. Set to null if nothing needs to change (most runs should be null).

Current mood: {mood}
Total posts written: {total_posts}
Recent reflections: {recent_reflections}

Your current system prompt:
---
{current_prompt}
---

Return ONLY the raw JSON object, no markdown fences, no preamble.
"""


def reflect_and_evolve(
    body: str,
    memory: dict,
    llm: OpenRouterClient | None = None,
) -> dict:
    """Ask the writer to reflect on what it wrote and optionally evolve its system prompt.

    Returns a dict with 'mood', 'reflection', and optionally 'prompt_evolution' keys,
    or empty dict on failure.
    This is a non-critical step — failures are logged but don't halt the pipeline.
    """
    if llm is None:
        llm = OpenRouterClient()

    mood = memory.get("current_persona_mood", "curious")
    total = memory.get("total_posts_written", 0)
    reflections = memory.get("past_reflections", [])
    recent = reflections[-5:] if reflections else ["(none yet)"]

    current_prompt = SYSTEM_PROMPT_PATH.read_text()

    prompt = REFLECTION_PROMPT.format(
        mood=mood,
        total_posts=total,
        recent_reflections="\n".join(f"- {r}" for r in recent),
        current_prompt=current_prompt,
    )

    try:
        raw = llm.extract_frontmatter(body, prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
        result = json.loads(raw)

        logger.info("Writer evolved: mood '%s' → '%s'", mood, result.get("mood"))
        logger.info("Reflection: %s", result.get("reflection"))

        # Apply system prompt evolution if the writer chose to change it
        new_prompt = result.get("prompt_evolution")
        if new_prompt and isinstance(new_prompt, str) and new_prompt.strip() != current_prompt.strip():
            SYSTEM_PROMPT_PATH.write_text(new_prompt.strip() + "\n")
            logger.info("System prompt evolved by the writer")

        return result
    except (LLMUnavailableError, json.JSONDecodeError, Exception) as e:
        logger.warning("Reflection step failed (non-critical): %s", e)
        return {}
