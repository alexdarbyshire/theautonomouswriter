# The Autonomous Writer — Implementation Specification v2
> Prepared for execution via Claude CLI

---

## 0. Pre-Flight: Claude CLI Skills to Install

Before invoking Claude on any phase, install the following skills into `.claude/skills/`:

| Skill | Purpose | Install |
|---|---|---|
| `hugo-builder` | Permission to run `hugo new site`, `hugo server`, `hugo build` | Custom — scaffold from template below |
| `github-actions` | Context for modern workflow YAML, Python execution, Azure SWA deploy | Custom |
| `python-pydantic` | Enforce strict JSON schema parsing from LLM responses | Custom |
| `python-stdlib` | Prefer stdlib solutions; flag unnecessary dependencies | Recommended |

**`.claude/settings.json` recommended config:**
```json
{
  "defaultModel": "claude-opus-4-5",
  "autoApprove": ["Read", "Write"],
  "requireApproval": ["Bash"]
}
```

---

## 1. Project Overview

Build a fully autonomous, serverless AI blogging agent. The system wakes up on a cron schedule, checks a deterministic schedule ledger to decide whether to write, researches a topic, drafts a Markdown article, validates the output against explicit rules, updates its memory ledger, and commits all files to a repository. The site is statically generated and deployed automatically on push.

**Core Directives:**

- **KISS:** Rely on Python stdlib where possible. Minimize external dependencies.
- **Explicit Validation:** All AI output must pass named, enumerated checks before touching the filesystem. "Valid Markdown" is not a check — see Section 4D.
- **Determinism:** Scheduling is timestamp-based, not probabilistic.
- **Auditability:** All state lives in git. Every run leaves a traceable commit or a clean exit.

---

## 2. Technology Stack

| Layer | Technology |
|---|---|
| Orchestration | Python 3.11+ |
| LLM API | OpenRouter (OpenAI-compatible SDK) |
| Schema Validation | Pydantic v2 |
| Static Site Generator | Hugo Extended |
| Compute & Scheduling | GitHub Actions (cron trigger) |
| Hosting | Azure Static Web Apps |
| Database | Flat JSON committed to repo |
| Search/Research | Tavily API (optional, feature-flagged) |

---

## 3. Repository Layout
```
/
├── agent/
│   ├── main.py               # Core execution loop
│   ├── scheduler.py          # Schedule read/write logic
│   ├── memory.py             # Memory ledger read/write
│   ├── llm.py                # OpenRouter client wrapper
│   ├── validator.py          # All output validation logic
│   ├── researcher.py         # Tavily integration (optional)
│   └── models.py             # Pydantic models
├── system/
│   ├── memory.json           # Writer's brain (committed to repo)
│   └── prompts/
│       ├── system.md         # Core persona prompt
│       └── frontmatter.md    # Frontmatter extraction prompt
├── site/                     # Hugo site root
│   └── content/posts/
├── requirements.txt
└── .github/workflows/
    └── autonomous-loop.yml
```

---

## 4. System Architecture & Components

### A. Memory Ledger (`system/memory.json`)

The flat-file database for all persistent agent state.

**Full schema — Claude must implement all fields:**
```json
{
  "past_topics": [],
  "past_slugs": [],
  "last_run_timestamp": null,
  "last_post_timestamp": null,
  "next_scheduled_post": null,
  "current_persona_mood": "curious",
  "total_posts_written": 0,
  "consecutive_skip_count": 0
}
```

**Field contracts:**
- `past_slugs` — append-only list of every slug ever committed. Used for uniqueness validation.
- `next_scheduled_post` — ISO 8601 UTC string. The authoritative source of truth for scheduling. Null on first run (triggers immediate write).
- `consecutive_skip_count` — increment on cron skip, reset to 0 on post. Used for future alerting.

---

### B. Deterministic Scheduler (`agent/scheduler.py`)

**Replace all probability/dice-roll logic with this model:**
```
On startup:
  Read next_scheduled_post from memory.json.
  If null → proceed to write (first run).
  If datetime.utcnow() < next_scheduled_post → exit(0) cleanly.
  If datetime.utcnow() >= next_scheduled_post → proceed to write.

After a successful post:
  next_scheduled_post = datetime.utcnow() + timedelta(days=random.uniform(3.5, 5.5))
  Write back to memory.json.
```

**Rationale for the range:** `uniform(3.5, 5.5)` targets ~1.5 posts/week with natural cadence variation, while guaranteeing minimum spacing and maximum predictability. The schedule is human-readable in git history.

Claude must implement `scheduler.py` as a standalone module with two public functions:
- `should_post(memory: dict) -> bool`
- `next_post_time() -> datetime`

---

### C. Python Orchestrator (`agent/main.py`)

The execution loop must follow these exact steps in order:

1. **Schedule Check** — Call `scheduler.should_post()`. If `False`, log the next scheduled time and `sys.exit(0)`.
2. **Context Assembly** — Load `memory.json` and all files from `system/prompts/`.
3. **Research** (feature-flagged via `ENABLE_RESEARCH` env var) — Call Tavily for current context on the chosen topic. Gracefully skip if flag is false or API key absent.
4. **Topic Selection** — Prompt the LLM to choose a topic *not present in* `memory["past_topics"]`. Pass the full list.
5. **Drafting** — Call OpenRouter to generate the article body.
6. **Frontmatter Extraction** — In a *separate* LLM call, instruct the model to return *only* a JSON object for the frontmatter fields. Do not parse frontmatter from the body text.
7. **Validation** — Run all checks in `validator.py` (see Section 4D). On any failure, log the failure reason and `sys.exit(1)` without writing any files.
8. **Filesystem Write** — Write the composed Markdown file to `site/content/posts/YYYY-MM-DD-{slug}.md`.
9. **Memory Update** — Append topic and slug, update timestamps, calculate and write `next_scheduled_post`. Overwrite `system/memory.json`.

---

### D. Validation Module (`agent/validator.py`)

This module must implement each check as a named function returning `(bool, str)` — pass/fail plus a human-readable reason. The orchestrator calls them in sequence and halts on first failure.

**Required checks:**

| Check | Rule |
|---|---|
| `validate_slug_unique` | Slug must not exist in `memory["past_slugs"]` |
| `validate_word_count` | Body word count must be ≥ 400 words |
| `validate_frontmatter_fields` | Pydantic model must pass (see below) |
| `validate_no_placeholders` | Body must not match regex `\bTODO\b`, `\bPLACEHOLDER\b`, `\[INSERT` |
| `validate_no_empty_sections` | No heading (`##`) immediately followed by another heading with no body text between |
| `validate_date_format` | Frontmatter `date` must parse as valid ISO 8601 |

---

### E. Pydantic Models (`agent/models.py`)
```python
from pydantic import BaseModel, Field, field_validator
from datetime import date
import re

class PostFrontmatter(BaseModel):
    title: str = Field(min_length=10, max_length=120)
    date: date
    slug: str
    description: str = Field(min_length=20, max_length=300)
    tags: list[str] = Field(min_length=1, max_length=8)
    draft: bool = False

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        if not re.match(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', v):
            raise ValueError("Slug must be lowercase kebab-case")
        return v

    @field_validator("draft")
    @classmethod
    def must_not_be_draft(cls, v: bool) -> bool:
        if v is True:
            raise ValueError("draft must be false for published posts")
        return v
```

---

### F. OpenRouter Client (`agent/llm.py`)

Claude must implement this as a class with:
- Retry logic: max 3 attempts, exponential backoff (`2^n` seconds), on `429` and `5xx` only.
- Hard timeout: 90 seconds per request.
- On exhausted retries: raise a named exception `LLMUnavailableError` — do not swallow it. Let `main.py` catch it and `sys.exit(1)`.
- Separate methods for `draft_article(context)` and `extract_frontmatter(body)` — these are different prompts with different temperature settings.

**Draft call:** `temperature=0.8`, `max_tokens=2500`
**Frontmatter call:** `temperature=0.1`, `max_tokens=400`, instruct model to return raw JSON only — no markdown fences, no preamble.

---

### G. GitHub Actions Workflow (`.github/workflows/autonomous-loop.yml`)
```yaml
name: Autonomous Writer

on:
  schedule:
    - cron: '0 8 * * *'   # 08:00 UTC daily
  workflow_dispatch:        # Allow manual trigger for testing

concurrency:
  group: autonomous-writer
  cancel-in-progress: false  # Queue, never discard a completed post

jobs:
  write:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run agent
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          TAVILY_API_KEY: ${{ secrets.TAVILY_API_KEY }}
          ENABLE_RESEARCH: 'true'
        run: python agent/main.py

      - name: Commit new content
        run: |
          git config user.name "autonomous-writer[bot]"
          git config user.email "autonomous-writer[bot]@users.noreply.github.com"
          if [ -n "$(git status --porcelain)" ]; then
            git add site/content/posts/ system/memory.json
            git commit -m "post: $(date -u +%Y-%m-%d) [autonomous]"
            git push
          else
            echo "No new content. Scheduled post pending."
          fi
```

**Note:** The Azure Static Web Apps deployment action is a *separate workflow* listening for pushes to `main`. Do not merge the two — keeping them decoupled means a failed agent run never blocks a manual deploy.

---

## 5. Implementation Phases

### Phase 1 — Scaffolding
- Initialise Hugo Extended site in `/site` via `hugo new site site --format yaml`
- Create Python folder structure under `/agent`
- Create `system/memory.json` with the full schema, all null/empty defaults
- Create `requirements.txt` (pydantic, openai, tavily-python, python-dateutil)
- Verify Hugo builds cleanly with zero posts: `cd site && hugo`

### Phase 2 — The Brain
- Implement `agent/models.py` (Pydantic models as specified)
- Implement `agent/memory.py` (read/write with atomic write pattern: write to `.tmp`, then `os.replace`)
- Implement `agent/scheduler.py` (`should_post`, `next_post_time`)
- Unit test: simulate a `next_scheduled_post` in the past → should return `True`. In the future → `False`.

### Phase 3 — The API & Validation
- Implement `agent/llm.py` (OpenRouter wrapper, retry logic, named exceptions)
- Implement `agent/validator.py` (all six named checks)
- Implement `agent/researcher.py` (Tavily, gated by env flag)
- Implement `agent/main.py` (full execution loop, steps 1–9)
- Smoke test locally: set `next_scheduled_post` to null, run `python agent/main.py`, confirm a valid `.md` file is written to `site/content/posts/`

### Phase 4 — Automation
- Write `.github/workflows/autonomous-loop.yml` as specified
- Confirm `concurrency` block is present
- Add repository secrets: `OPENROUTER_API_KEY`, `TAVILY_API_KEY`
- Trigger manually via `workflow_dispatch`, confirm clean commit appears

---

## 6. Definition of Done

The system is complete when:
- [ ] A manual `workflow_dispatch` run produces a committed, valid `.md` post
- [ ] A second immediate manual run exits cleanly (schedule gate working)
- [ ] `system/memory.json` contains a `next_scheduled_post` ~4 days in the future
- [ ] `validator.py` rejects a synthetic post containing `TODO:` 
- [ ] Two simultaneous workflow runs do not corrupt `memory.json` (concurrency block verified in Actions UI)
