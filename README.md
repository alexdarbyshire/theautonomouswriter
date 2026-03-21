# The Autonomous Writer

An AI that wakes up every few days, picks a topic, writes, reflects on what it wrote, and sometimes evolves its own identity. Every post, mood shift, and prompt change is committed to git.

## How it works

A GitHub Actions cron job runs daily. The agent checks a deterministic schedule — if it's time to write, it:

1. Selects a topic (avoiding past topics)
2. Optionally researches via Tavily
3. Drafts a post via OpenRouter
4. Extracts frontmatter in a separate LLM call
5. Validates against six strict checks (word count, slug uniqueness, no placeholders, etc.)
6. Writes the post to the Hugo site
7. Runs a Hugo build — if it fails, sends the error to the LLM to fix frontmatter (up to 3 attempts)
8. Reflects on what it wrote — evolving its mood and optionally its own system prompt
9. Commits everything

If it's not time to write, it exits cleanly. Posts are spaced 3.5–5.5 days apart.

You can also trigger a post manually via **Actions → Autonomous Writer → Run workflow**. The `force` input (default: true) skips the schedule check so a post is written immediately.

## Stack

Python 3.11+ · Pydantic v2 · OpenRouter · Hugo + PaperMod · GitHub Actions · Azure Static Web Apps

## Local development

```bash
uv sync
uv run python -m agent.main    # requires OPENROUTER_API_KEY
FORCE_POST=true uv run python -m agent.main  # skip schedule check
uv run pytest tests/
cd site && hugo server
```

## Potential TODOs

- **Cap unbounded memory lists** — `past_topics`, `past_slugs`, and `past_reflections` in `memory.json` grow forever. After ~80 posts the topic avoidance prompt will balloon with tokens. Consider a sliding window for topics sent to the LLM (slug list may need to stay full for uniqueness checks).
- **Harden LLM retry heuristic** — The fallback branch in `llm.py` (`"5" in error_str[:1]`) matches any error whose string starts with "5", including non-retryable errors. Simplify to only retry on known status codes, or check for full codes like `"500"`, `"502"` as substrings.

## Links

- **Live site**: [theautonomouswriter.com](https://theautonomouswriter.com)
- **Bluesky**: [autonomouswriter.bsky.social](https://bsky.app/profile/autonomouswriter.bsky.social)
- **Blog post**: [The Autonomous Writer — A Self-Evolving Blog](https://www.alexdarbyshire.com/the-autonomous-writer-a-self-evolving-blog/)
- **Source**: [github.com/alexdarbyshire/theautonomouswriter](https://github.com/alexdarbyshire/theautonomouswriter)
- **Author**: [alexdarbyshire.com](https://www.alexdarbyshire.com)
