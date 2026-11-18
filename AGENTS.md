# Agent Guidance

Read [CONTEXT.md](CONTEXT.md) before planning or implementation. It defines the
shared language, constraints, and approved work. If a `CONTEXT-MAP.md` is later
added, follow it to the nearest applicable context before starting work.

## Source And Scope

- Use current code, tests, and configuration to establish implemented behavior.
  Use the linked design documents to establish historical intent. Report a
  conflict before changing a contract; do not silently restore an old design.
- Keep writer identity, mood, and reflection distinct. Use the terms in
  `CONTEXT.md` when assessing the experiment or proposing changes.
- Preserve existing posts, state, and user changes. Do not run the live agent
  merely to inspect behavior: it can call paid services, send replies, and write
  experiment state.

## Implementation Rules

- Use Python 3.11+ and prefer the standard library. Minimize new dependencies.
  Use `json`, UTC `datetime`, `pathlib`, `os.replace`, `re`, and `logging` for
  their existing roles. Dependencies are declared in `pyproject.toml`.
- Annotate `agent/` code. Use `from __future__ import annotations` and
  `TYPE_CHECKING` imports where needed for forward references and import cycles.
- Use Pydantic v2 for structured validation. Extract frontmatter separately;
  do not recover it from the article body. Validate raw JSON directly when
  available. Surface validation failures; do not silently accept invalid posts
  or add frontmatter fields without an agreed contract.
- Preserve the ordered stages in `agent/main.py`: load memory; process Bluesky
  and newsletter replies; check schedule; assemble context and suggestions;
  select topic; research; draft; extract frontmatter; validate; generate an
  optional cover; write post; check Hugo; mark offered suggestions presented;
  announce; reflect; save memory; clean
  and save suggestions; send newsletter. Consult the code for conditional paths.
- Keep the scheduler's public seams `should_post()` and `next_post_time()`.
  Keep named validator checks returning `(bool, str)` and stop on first failure.
- Keep OpenRouter retry exhaustion visible through `LLMUnavailableError`.
  Consult `agent/llm.py` for current request settings.
- Keep the four workflows separate. Preserve queued writer runs with
  `cancel-in-progress: false`, bot commit identity, full history for the writer,
  and theme submodule checkout where builds need it. Use current workflow
  configuration for action versions, environment flags, and staged state paths.
- Run Hugo from `site/`. Preserve YAML frontmatter and support both flat posts
  and page bundles under `site/content/posts/`. Do not re-scaffold the existing
  site. Use the Hugo version pinned in the writer workflow.

## Commands And Checks

```sh
uv sync
uv run pytest tests/
uv run ruff check agent/ tests/
uv run ruff format --check agent/ tests/
node tests/test_suggestion_form.cjs
```

CI runs the suggestion form tests with Node.js 26.

For a site change, run `hugo` from `site/`; use `hugo server` there for a local
preview. Before committing Python changes, run Ruff fixes and formatting for
the changed files, then the lint and test gates above. Inspect automatic edits
and avoid changing unrelated work.

For an authorized live run, the entry point is `uv run python -m agent.main`.
`FORCE_POST=true` bypasses the schedule. Refer to `.env.example`, feature code,
and `.github/workflows/autonomous-loop.yml` for required credentials and flags;
do not print secrets or include them in commits.
