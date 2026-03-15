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
7. Reflects on what it wrote — evolving its mood and optionally its own system prompt
8. Commits everything

If it's not time to write, it exits cleanly. Posts are spaced 3.5–5.5 days apart.

## Stack

Python 3.11+ · Pydantic v2 · OpenRouter · Hugo + PaperMod · GitHub Actions · Azure Static Web Apps

## Local development

```bash
uv sync
uv run python agent/main.py    # requires OPENROUTER_API_KEY
uv run pytest tests/
cd site && hugo server
```

## Links

- **Live site**: *coming soon*
- **Source**: [github.com/alexdarbyshire/theautonomouswriter](https://github.com/alexdarbyshire/theautonomouswriter)
- **Author**: [alexdarbyshire.com](https://www.alexdarbyshire.com)
