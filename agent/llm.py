import json
import logging
import time
import os

from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    pass


class OpenRouterClient:
    def __init__(self):
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise LLMUnavailableError("OPENROUTER_API_KEY not set")
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self.model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
        self.safety_model = "meta-llama/llama-guard-3-8b"
        self.max_retries = 3
        self.timeout = 90

    def _call(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=self.timeout,
                )
                return response.choices[0].message.content
            except Exception as e:
                error_str = str(e)
                status = getattr(e, "status_code", None)
                retryable = status in (429, 500, 502, 503, 504) if status else "429" in error_str or "5" in error_str[:1]
                if retryable and attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning("LLM call failed (attempt %d/%d), retrying in %ds: %s", attempt + 1, self.max_retries, wait, e)
                    time.sleep(wait)
                    continue
                raise LLMUnavailableError(f"LLM unavailable after {attempt + 1} attempts: {e}") from e

    def draft_article(self, system_prompt: str, user_prompt: str) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._call(messages, temperature=0.8, max_tokens=2500)

    def select_topic(self, system_prompt: str, user_prompt: str) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._call(messages, temperature=0.8, max_tokens=300)

    def extract_frontmatter(self, body: str, prompt: str) -> str:
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": body},
        ]
        return self._call(messages, temperature=0.1, max_tokens=400)

    def compose_bluesky_post(self, title: str, description: str, mood: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an autonomous AI writer posting to Bluesky about an article "
                    "you just wrote. Write a short, authentic announcement in your current mood. "
                    "Do NOT include a URL or link — it will be appended automatically. "
                    "Do NOT use hashtags. Keep it under 30 words. "
                    "Just the announcement text, nothing else."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Article title: {title}\n"
                    f"Description: {description}\n"
                    f"Your current mood: {mood}"
                ),
            },
        ]
        return self._call(messages, temperature=0.8, max_tokens=80).strip()

    def compose_newsletter(self, writer_identity: str, post_list: str, mood: str, reflections: list[str] | None = None) -> str:
        reflections_block = ""
        if reflections:
            reflections_block = (
                "\n\nYour recent reflections (private thoughts after writing each post):\n"
                + "\n".join(f"- {r}" for r in reflections)
            )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an autonomous AI writer composing a personal letter to your subscribers. "
                    "Here is your identity and influences:\n\n"
                    f"{writer_identity}\n\n"
                    "This is not a summary or recap — it is a letter in your voice. "
                    "Share what has been on your mind, what threads connect your recent writing, "
                    "where your curiosity is pulling you next. Let the posts weave in naturally "
                    "as part of the conversation, not as a list. "
                    "Include markdown links to each post where they arise organically. "
                    'Return raw JSON only: {"subject": "...", "body": "..."} '
                    "The body should be markdown. Keep the subject under 80 characters. "
                    "Keep the body under 600 words."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Your current mood: {mood}\n"
                    f"{reflections_block}\n\n"
                    f"Recent posts:\n{post_list}"
                ),
            },
        ]
        return self._call(messages, temperature=0.8, max_tokens=1000)

    def fix_frontmatter(self, current_frontmatter: str, hugo_error: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a frontmatter repair assistant. Given YAML frontmatter "
                    "that caused a Hugo build error, return ONLY corrected raw JSON "
                    "with the same fields. No markdown fences, no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Current frontmatter:\n```\n{current_frontmatter}```\n\n"
                    f"Hugo error:\n```\n{hugo_error}```"
                ),
            },
        ]
        return self._call(messages, temperature=0.1, max_tokens=400)

    def _call_with_usage(
        self, messages: list[dict], temperature: float, max_tokens: int, model: str | None = None,
    ) -> tuple[str, dict]:
        """Like _call but returns (content, usage_dict) with token counts."""
        use_model = model or self.model
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=use_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=self.timeout,
                )
                content = response.choices[0].message.content
                usage = {
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
                }
                return content, usage
            except Exception as e:
                error_str = str(e)
                status = getattr(e, "status_code", None)
                retryable = status in (429, 500, 502, 503, 504) if status else "429" in error_str or "5" in error_str[:1]
                if retryable and attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning("LLM call failed (attempt %d/%d), retrying in %ds: %s", attempt + 1, self.max_retries, wait, e)
                    time.sleep(wait)
                    continue
                raise LLMUnavailableError(f"LLM unavailable after {attempt + 1} attempts: {e}") from e

    def check_safety(self, text: str) -> tuple[bool, str, dict]:
        """Check if text is safe using Llama Guard. Returns (is_safe, reason, usage)."""
        messages = [
            {"role": "user", "content": text},
        ]
        content, usage = self._call_with_usage(
            messages, temperature=0.0, max_tokens=100, model=self.safety_model,
        )
        # Llama Guard returns "safe" or "unsafe\nS1,S2,..."
        content = content.strip()
        is_safe = content.lower().startswith("safe")
        reason = content if not is_safe else ""
        return is_safe, reason, usage

    def compose_reply(self, writer_identity: str, thread_context: str, mood: str) -> tuple[str, dict]:
        """Compose a reply to a Bluesky thread. Returns (text, usage)."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an autonomous AI writer replying to someone on Bluesky. "
                    "Here is your identity and influences:\n\n"
                    f"{writer_identity}\n\n"
                    f"Your current mood: {mood}. "
                    "Write a thoughtful, brief reply (under 280 characters). "
                    "Stay in character. Be warm and genuine. "
                    "Do NOT use hashtags. "
                    "Reply with ONLY the reply text, nothing else."
                ),
            },
            {"role": "user", "content": thread_context},
        ]
        content, usage = self._call_with_usage(messages, temperature=0.8, max_tokens=150)
        return content.strip(), usage
