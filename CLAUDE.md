# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Autonomous AI blogging agent. Runs on a GitHub Actions cron schedule, uses an LLM (via OpenRouter) to draft blog posts, validates output against strict rules, commits to repo, and deploys via Hugo + Azure Static Web Apps. Full spec in `docs/DESIGN_SPECIFICATION.md`.

## Architecture

**Execution flow** (in `agent/main.py`, steps must execute in this exact order):
1. Schedule check → 2. Load memory + prompts → 3. Research (feature-flagged) → 4. Topic selection (must avoid past topics) → 5. Draft article → 6. Extract frontmatter (separate LLM call, JSON only) → 7. Validate → 8. Write markdown to `site/content/posts/YYYY-MM-DD-{slug}.md` → 9. Reflect & evolve (mood, optional system prompt rewrite) → 10. Update memory

**Key modules:**
- `agent/scheduler.py` — Deterministic scheduling via `next_scheduled_post` timestamp (not probabilistic). Two public functions: `should_post()`, `next_post_time()`.
- `agent/llm.py` — OpenRouter client class. Retry 3x with `2^n` backoff on 429/5xx. 90s timeout. Raises `LLMUnavailableError` on exhaustion.
- `agent/validator.py` — Six named checks, each returns `(bool, str)`. Halts on first failure.
- `agent/memory.py` — Atomic writes (write to `.tmp`, then `os.replace`).
- `agent/models.py` — Pydantic v2 models for frontmatter validation.
- `agent/evolve.py` — Post-write reflection. Evolves mood, records reflections, can rewrite `system/prompts/system.md`.
- `system/memory.json` — Flat-file database, committed to repo. Source of truth for scheduling, topic history, mood, and reflections.

**Two separate GitHub Actions workflows:** agent loop (`autonomous-loop.yml`) and Azure SWA deploy (triggered on push to main). Keep them decoupled.

## Commands

```bash
# Install dependencies
uv sync

# Run the agent locally
uv run python -m agent.main

# Build Hugo site
cd site && hugo

# Run Hugo dev server
cd site && hugo server

# Run tests
uv run pytest tests/
```

## Environment Variables

- `OPENROUTER_API_KEY` — Required for LLM calls
- `TAVILY_API_KEY` — Optional, for research
- `ENABLE_RESEARCH` — Set to `'true'` to enable Tavily research step

## Key Constraints

- Python 3.11+, prefer stdlib. Minimize external dependencies.
- All validation checks must pass before any file is written. On failure: log reason, `sys.exit(1)`, write nothing.
- Scheduling is deterministic (timestamp comparison), never probabilistic.
- All state lives in git — every run produces a traceable commit or a clean exit.
- LLM draft call: `temperature=0.8`, `max_tokens=2500`. Frontmatter call: `temperature=0.1`, `max_tokens=400`, raw JSON only.
- Post spacing: `random.uniform(3.5, 5.5)` days after each post.
