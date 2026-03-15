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
