---
description: Prefer Python stdlib solutions and flag unnecessary external dependencies
---

# Python Stdlib First

This project follows a KISS principle — prefer Python standard library over third-party packages.

## Guidelines
- Use `json` for JSON read/write (not orjson, ujson)
- Use `datetime` and `datetime.timezone.utc` for timestamps (not arrow, pendulum)
- Use `pathlib.Path` for file operations
- Use `os.replace()` for atomic file writes (not external atomic-write packages)
- Use `re` for regex validation
- Use `logging` for all log output (not structlog, loguru)
- Use `random.uniform()` for schedule jitter (not numpy)
- Use `unittest` or `pytest` for tests (pytest is acceptable as a dev dependency)

## Allowed external dependencies
- `pydantic` — schema validation (core to the architecture)
- `openai` — OpenRouter uses OpenAI-compatible SDK
- `tavily-python` — research feature (optional, feature-flagged)
- `pytest` — dev/test only

## Flag these as unnecessary
If you find yourself reaching for `requests` (use `openai` SDK), `python-dotenv` (use env vars directly), `click`/`typer` (no CLI needed), or date libraries (use `datetime`), reconsider.
