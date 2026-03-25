# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Autonomous AI blogging agent. Runs on a GitHub Actions cron schedule, uses an LLM (via OpenRouter) to draft blog posts, validates output against strict rules, commits to repo, and deploys via Hugo + Azure Static Web Apps. Full spec in `docs/DESIGN_SPECIFICATION.md`.

## Architecture

**Execution flow** (in `agent/main.py`, steps must execute in this exact order):
1. Load memory → 2. Bluesky replies (runs every cron, before schedule gate) → 3. Schedule check → 4. Context assembly → 5. Topic selection → 6. Research (feature-flagged, includes URLs for citations) → 7. Draft article → 8. Extract frontmatter → 9. Validate → 10. Write post → 11. Hugo build validation → 12. Social posting → 13. Reflect & evolve → 14. Memory update → 15. Newsletter (per-post notification + periodic recap letter)

**Key modules:**
- `agent/scheduler.py` — Deterministic scheduling via `next_scheduled_post` timestamp (not probabilistic). Two public functions: `should_post()`, `next_post_time()`.
- `agent/llm.py` — OpenRouter client class. Retry 3x with `2^n` backoff on 429/5xx. 90s timeout. Raises `LLMUnavailableError` on exhaustion. Also provides `check_safety()` (Llama Guard 3 8B), `compose_reply()`, `compose_newsletter()`, and `_call_with_usage()` for token tracking.
- `agent/validator.py` — Six named checks, each returns `(bool, str)`. Halts on first failure.
- `agent/memory.py` — Atomic writes (write to `.tmp`, then `os.replace`).
- `agent/models.py` — Pydantic v2 models for frontmatter validation.
- `agent/evolve.py` — Post-write reflection. Evolves mood, records reflections, can rewrite `system/prompts/system.md`.
- `agent/newsletter.py` — Buttondown integration. `notify_new_post()` sends per-post emails. `maybe_send_recap()` sends a personal letter every 3 posts in the writer's voice.
- `agent/bluesky_replies.py` — Responds to replies on own Bluesky posts. Safety-checked via Llama Guard 3, token-budgeted (50k/run), max 3 replies per thread with graceful sign-off on final reply.
- `system/memory.json` — Flat-file database, committed to repo. Source of truth for scheduling, topic history, mood, and reflections.
- `system/bluesky_state.json` — Bluesky reply tracking (replied URIs, per-thread counts). Separate from memory.json to avoid bloat.

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
- `ENABLE_NEWSLETTER` — Set to `'true'` to enable Buttondown newsletter
- `BUTTONDOWN_API_KEY` — Required when newsletter enabled
- `BUTTONDOWN_USERNAME` — Buttondown account username
- `ENABLE_BLUESKY_REPLIES` — Set to `'true'` to enable reply bot
- `BLUESKY_HANDLE` / `BLUESKY_APP_PASSWORD` — Required for Bluesky features

## Key Constraints

- Python 3.11+, prefer stdlib. Minimize external dependencies.
- All validation checks must pass before any file is written. On failure: log reason, `sys.exit(1)`, write nothing.
- Scheduling is deterministic (timestamp comparison), never probabilistic.
- All state lives in git — every run produces a traceable commit or a clean exit.
- LLM draft call: `temperature=0.8`, `max_tokens=2500`. Frontmatter call: `temperature=0.1`, `max_tokens=400`, raw JSON only.
- Post spacing: `random.uniform(3.5, 5.5)` days after each post.
