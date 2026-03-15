---
description: GitHub Actions workflow authoring for the autonomous writer pipeline
---

# GitHub Actions

Context for writing and maintaining GitHub Actions workflows in this project.

## Workflow architecture
- **`autonomous-loop.yml`** — The agent cron loop. Runs daily at 08:00 UTC via `schedule`, plus `workflow_dispatch` for manual triggers. Must include a `concurrency` block (`cancel-in-progress: false`) to queue runs, never discard.
- **Azure SWA deploy** — Separate workflow triggered on push to `main`. Never merge with the agent loop.

## Conventions
- Use `actions/checkout@v4` with `fetch-depth: 0`
- Use `actions/setup-python@v5` with `python-version: '3.11'` and `cache: 'pip'`
- Install deps with `pip install -r requirements.txt` (GitHub Actions runner, not local dev)
- Agent runs via `python agent/main.py`
- Git commits use bot identity: `autonomous-writer[bot]`
- Only commit `site/content/posts/` and `system/memory.json`
- Secrets: `OPENROUTER_API_KEY`, `TAVILY_API_KEY`
- Job needs `permissions: contents: write` for pushing commits
