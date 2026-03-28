# Topic Suggestions & Newsletter Replies — Design Document

**Status:** Draft
**Branch:** `feature/topic-suggestions`
**Date:** 2026-03-28

---

## Problem

Readers have no way to suggest topics to the autonomous writer. The audience spans multiple platforms (website visitors, newsletter subscribers, GitHub users, Bluesky followers), so a single channel won't reach everyone. Additionally, the newsletter is one-way — subscribers can't reply and get a response.

## Solution

Three ingestion channels for topic suggestions, all funneling into `system/suggestions.json`. Plus bidirectional newsletter replies where the writer responds to subscriber emails. The writer retains full creative autonomy — suggestions are inspiration, not assignments.

## Principles

- **Nothing unscreened enters the repo.** Every suggestion passes Llama Guard before being committed.
- **No PII in plaintext in git.** Email addresses and Google account IDs are encrypted (Fernet symmetric encryption) before storage, so the owner can decrypt and see usernames when needed. Public handles (GitHub, Bluesky) are stored as-is.
- **Writer autonomy is sacred.** Suggestions are framed as optional inspiration. No voting, no ranking, no queue obligations.
- **All permanent state in git.** Matches the existing project constraint.
- **Progressive delivery.** Each feature ships independently.

---

## Architecture

```
                              system/suggestions.json
                                       ^
            +--------------------------+---------------------------+
            |                          |                           |
   Azure SWA Function          GitHub Issues API          Buttondown API
   (Google OIDC auth)          (label filter)             (subscriber replies)
            ^                          ^                           ^
            |                          |                           |
   /suggest page on site       Issue template             Newsletter CTA
   (sign in with Google)       on GitHub repo             "Reply to suggest"
```

### Safety Pipeline

| Channel | Stage 1 (edge) | Stage 2 (before commit) | Stage 3 (agent runtime) |
|---------|----------------|-------------------------|-------------------------|
| Web form | Azure Function: length, no URLs, blocklist | `ingest-suggestion.yml`: Llama Guard via `check_safety()` | Agent: re-verify status before injecting into prompt |
| GitHub Issues | GitHub account required (anti-spam) | N/A (stays on GitHub until agent reads) | Agent: Llama Guard screen before writing to `suggestions.json` |
| Newsletter | Buttondown subscriber account required | N/A (stays in Buttondown until agent reads) | Agent: Llama Guard screen before writing to `suggestions.json` |

### Rate Limiting & Identity Encryption

Private user identifiers are encrypted with Fernet symmetric encryption before storage. This keeps PII out of plaintext in git while allowing the project owner to decrypt and view usernames when needed.

```python
from cryptography.fernet import Fernet

def encrypt_identifier(identifier: str, key: str) -> str:
    """Encrypt a user identifier. Returns base64 ciphertext."""
    f = Fernet(key.encode())
    return f.encrypt(identifier.encode()).decode()

def decrypt_identifier(token: str, key: str) -> str:
    """Decrypt a stored identifier back to plaintext."""
    f = Fernet(key.encode())
    return f.decrypt(token.encode()).decode()
```

For rate limiting, encrypted tokens are not directly comparable (Fernet produces different ciphertext each time). So rate-limit checks encrypt-then-compare by decrypting existing entries and comparing plaintext in memory — never storing plaintext to disk.

| Channel | Raw identifier | Stored in git | Rate limit |
|---------|---------------|---------------|------------|
| Web form | Google `sub` claim (opaque ID) | Fernet-encrypted | 3 per user per 30 days |
| Newsletter | Buttondown subscriber ID | Fernet-encrypted | 2 per subscriber per email |
| GitHub Issues | GitHub username | Username (public) | 2 open suggestions at a time |
| Bluesky | Handle | Handle (public) | 2 per user per 30 days |

The encryption key is stored as `SUGGESTION_ENCRYPTION_KEY` in GitHub Actions secrets and Azure SWA app settings. Generate with: `uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

---

## Feature 1: Core + Web Form

**Ships first. Provides the foundation all other channels build on.**

### 1.1 Suggestion Schema — `system/suggestions.json`

```json
{
  "suggestions": [
    {
      "id": "web-1711612800-a1b2c3",
      "source": "web",
      "text": "The ethics of AI writing about itself",
      "submitter_encrypted": "a8f2e1c903b7d4e1",
      "submitted_at": "2026-03-28T12:00:00Z",
      "status": "pending",
      "safety_reason": null,
      "used_in_slug": null
    }
  ],
  "processed_issues": [],
  "processed_reply_ids": [],
  "last_cleanup": null
}
```

**Status lifecycle:** `pending` -> `screened_safe` / `screened_unsafe` -> `used` / `expired`

### 1.2 Core Agent Module — `agent/suggestions.py` (~130 lines)

Functions (reusing `agent/memory.py` atomic write pattern):

| Function | Purpose |
|----------|---------|
| `load_suggestions()` | Read `system/suggestions.json`, return dict (default empty structure if missing) |
| `save_suggestions(data)` | Atomic write (`.tmp` then `os.replace`) |
| `screen_pending(suggestions, llm)` | Run `llm.check_safety()` on all `pending` entries. Cap 10 per run. Update status. |
| `get_safe_suggestions(suggestions)` | Return `screened_safe` entries, max 5 |
| `mark_used(suggestions, suggestion_id, slug)` | Set status `used`, record slug |
| `cleanup(suggestions)` | Expire safe > 90 days, remove unsafe > 7 days, remove used > 30 days |
| `user_hash(identifier, secret)` | HMAC-SHA256 keyed hash, returns 16-char hex |
| `check_rate_limit(suggestions, submitter_encrypted, source, ...)` | Count recent submissions by hash, return bool |

Feature-gated via `ENABLE_SUGGESTIONS` env var.

### 1.3 Topic Selection Integration — `agent/main.py`

After context assembly (~line 64), before topic selection (~line 71):

```python
if os.environ.get("ENABLE_SUGGESTIONS", "").lower() == "true":
    suggestions = load_suggestions()
    screen_pending(suggestions, llm)
    safe = get_safe_suggestions(suggestions)
    if safe:
        suggestions_context = format_suggestions_for_prompt(safe)
```

**Prompt addition** (appended to existing topic prompt):

```
Your readers have left some suggestions. You may draw inspiration from
one if it genuinely resonates with your mood — or ignore them all.
If you use a suggestion, begin your reply with [ID] then the topic.

- [web-1711612800-a1b2c3] "The ethics of AI writing about itself"
- [github-1711613000-d4e5f6] "How ancient maps shaped exploration"

Or suggest your own original topic as usual.
```

After topic selection: parse for `[ID]` prefix -> `mark_used()` -> strip ID before passing downstream.

At end of run: `cleanup()` + `save_suggestions()`.

### 1.4 Azure SWA Function — `api/function_app.py`

Python v2 programming model. Single endpoint `POST /api/suggest`:

1. **Auth check** — Azure SWA injects `x-ms-client-principal` header for authenticated users. Decode base64 JSON to get `userId`.
2. **Validate** — `suggestion` field, 10-300 chars, no URLs (`https?://`), basic profanity blocklist.
3. **Rate limit** — In-memory dict by `userId`, 5 per hour (resets on cold start). This is a coarse first-pass; the real per-user rate limit is enforced by `submitter_encrypted` checks in the ingest workflow.
4. **Dispatch** — Trigger `ingest-suggestion.yml` via GitHub API `workflow_dispatch` with inputs: `source`, `text`, `submitted_at`, `submitter_encrypted` (HMAC of userId).
5. **Return** — `200 { "ok": true, "message": "..." }` or `400`/`429` with error.

**Why workflow_dispatch:** Avoids race conditions between concurrent form submissions and agent runs. The workflow serializes writes via `concurrency: group: suggestions-writer`.

### 1.5 Ingest Workflow — `.github/workflows/ingest-suggestion.yml`

```yaml
name: Ingest Topic Suggestion

on:
  workflow_dispatch:
    inputs:
      source:
        required: true
        type: string
      text:
        required: true
        type: string
      submitted_at:
        required: true
        type: string
      submitter_encrypted:
        required: true
        type: string

concurrency:
  group: suggestions-writer
  cancel-in-progress: false

jobs:
  ingest:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v6

      - name: Install dependencies
        run: uv sync

      - name: Screen suggestion via Llama Guard
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
        run: uv run python scripts/screen_suggestion.py "${{ inputs.text }}"
        # Exits non-zero if unsafe — stops the workflow before commit

      - name: Append to suggestions.json
        run: >
          uv run python scripts/append_suggestion.py
          "${{ inputs.source }}"
          "${{ inputs.text }}"
          "${{ inputs.submitted_at }}"
          "${{ inputs.submitter_encrypted }}"

      - name: Commit
        run: |
          git config user.name "autonomous-writer[bot]"
          git config user.email "autonomous-writer[bot]@users.noreply.github.com"
          git add system/suggestions.json
          git diff --cached --quiet || git commit -m "suggestion: ingest from ${{ inputs.source }}"
          git push
```

### 1.6 Helper Scripts

**`scripts/screen_suggestion.py`** (~20 lines):
- Imports `agent.llm.LLMClient`
- Calls `check_safety(text)`
- `sys.exit(0)` if safe, `sys.exit(1)` if unsafe (halts workflow)

**`scripts/append_suggestion.py`** (~40 lines):
- Reads `system/suggestions.json`
- Generates ID: `{source}-{unix_timestamp}-{random_hex_6}`
- Appends entry with `status: "screened_safe"` (already passed Llama Guard)
- Writes back atomically
- Also checks rate limit by `submitter_encrypted` — exits if limit exceeded

### 1.7 Google OIDC Auth — `site/staticwebapp.config.json`

Azure SWA built-in auth handles the entire OAuth flow:

```json
{
  "auth": {
    "identityProviders": {
      "google": {
        "registration": {
          "clientIdSettingName": "GOOGLE_CLIENT_ID",
          "clientSecretSettingName": "GOOGLE_CLIENT_SECRET"
        }
      }
    }
  },
  "routes": [
    {
      "route": "/api/suggest",
      "methods": ["POST"],
      "allowedRoles": ["authenticated"]
    }
  ],
  "responseOverrides": {
    "401": {
      "redirect": "/.auth/login/google?post_login_redirect_uri=/suggest/",
      "statusCode": 302
    }
  }
}
```

- `/suggest` page is public (anyone can see the form)
- `POST /api/suggest` requires authentication
- Unauthenticated API calls get redirected to Google sign-in
- On the page, a "Sign in with Google" button links to `/.auth/login/google?post_login_redirect_uri=/suggest/`
- After sign-in, Azure SWA injects `x-ms-client-principal` header with the user's opaque Google `userId`

**Setup required:** Create OAuth client in Google Cloud Console. Add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` as app settings in Azure SWA portal.

### 1.8 Hugo Suggest Page — `site/content/suggest.md`

Hugo content page using PaperMod layout. Contains:

- Brief intro explaining that the writer considers but isn't obligated to use suggestions
- "Sign in with Google" button (links to `/.auth/login/google?post_login_redirect_uri=/suggest/`)
- Textarea with character counter (10-300 chars)
- Submit button (vanilla JS `fetch('/api/suggest', ...)`)
- Success/error feedback area
- No external dependencies

### 1.9 Deployment Config Changes

**`.github/workflows/azure-static-web-apps-zealous-water-001fe8510.yml`:**
- Change `api_location: ""` to `api_location: "/api"`

**`.github/workflows/autonomous-loop.yml`:**
- Add `system/suggestions.json` to `git add` in commit step

**`site/hugo.yaml`:**
- Add "Suggest" to main menu

**`api/host.json`:**
```json
{
  "version": "2.0",
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  }
}
```

**`api/requirements.txt`:**
```
azure-functions
```

**`.gitignore` additions:**
```
api/local.settings.json
api/__pycache__/
```

### 1.10 Tests — `tests/test_suggestions.py`

| Test | What it verifies |
|------|-----------------|
| `test_load_empty_suggestions` | Returns default structure when file is missing |
| `test_save_and_load_roundtrip` | Atomic write works correctly |
| `test_screen_pending_safe` | Llama Guard safe result updates status to `screened_safe` |
| `test_screen_pending_unsafe` | Unsafe result sets status and records reason |
| `test_screen_pending_caps_at_10` | Only screens first 10 pending per run |
| `test_get_safe_suggestions` | Filters to only `screened_safe`, max 5 |
| `test_mark_used` | Sets status and records slug |
| `test_cleanup_expires_old_safe` | Safe suggestions > 90 days become `expired` |
| `test_cleanup_removes_old_unsafe` | Unsafe > 7 days removed |
| `test_cleanup_removes_old_used` | Used > 30 days removed |
| `test_user_hash_deterministic` | Same input + secret = same hash |
| `test_user_hash_varies_by_secret` | Different secret = different hash |
| `test_rate_limit_allows_under` | Returns True when under limit |
| `test_rate_limit_blocks_over` | Returns False when at limit |
| `test_disabled_when_flag_off` | Feature gate prevents execution |

### 1.11 Environment Variables (New)

| Variable | Where | Purpose |
|----------|-------|---------|
| `ENABLE_SUGGESTIONS` | Actions env | Feature gate for suggestion ingestion |
| `RATE_LIMIT_SECRET` | Actions secret + Azure app setting | HMAC key for hashing user identifiers |
| `GOOGLE_CLIENT_ID` | Azure SWA app setting | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Azure SWA app setting | Google OAuth client secret |
| `GITHUB_TOKEN` (for Azure Function) | Azure SWA app setting | Fine-grained PAT with `actions:write` for workflow dispatch |

---

## Feature 2: Newsletter (Bidirectional)

**Ships second. Requires Buttondown API verification for reply endpoints.**

### 2.1 Parse Subscriber Replies for Suggestions

**In `agent/suggestions.py`:** Add `ingest_newsletter_replies(suggestions)`:
- Fetch replies via Buttondown API (`GET /v1/emails` then per-email replies, or `GET /v1/comments` — verify exact endpoint)
- Safety-screen each reply via `llm.check_safety()`
- Parse for topic-like content (short replies that read as suggestions)
- Add to suggestions with `source: "newsletter"`, `submitter_encrypted` of subscriber ID
- Track processed reply IDs in `processed_reply_ids`

**Integration point in `agent/main.py`:** Called alongside other ingestion, before topic selection.

### 2.2 Writer Replies to Subscribers

**New file: `agent/newsletter_replies.py` (~150 lines)**

Mirrors `agent/bluesky_replies.py` architecture:

| Aspect | Bluesky | Newsletter |
|--------|---------|------------|
| State file | `system/bluesky_state.json` | `system/newsletter_reply_state.json` |
| Reply limit | 3 per thread | 2 per subscriber per newsletter email |
| Token budget | 50k/run | 30k/run |
| Safety check | Llama Guard on incoming text | Same |
| Composition | `llm.compose_reply()` | `llm.compose_email_reply()` (new) |
| Length limit | 300 graphemes | 500 words |
| Final reply | "close naturally" | "close warmly, suggest they write again" |

**State file: `system/newsletter_reply_state.json`:**
```json
{
  "replied_ids": [],
  "subscriber_reply_counts": {}
}
```

`subscriber_reply_counts` keyed by `"{email_id}:{subscriber_hash}"` to cap per-subscriber per-email. Subscriber identity is HMAC-hashed before storage.

**New LLM function: `agent/llm.py:compose_email_reply()`:**
- System prompt: writer's identity + mood (same as Bluesky)
- User prompt: includes the subscriber's message and conversation context
- Tuned for email: warmer, more reflective, up to 500 words
- Returns `(reply_text, usage_dict)`

**Integration in `agent/main.py`:**
- Runs early in pipeline, before schedule gate (like Bluesky replies)
- Feature-gated via `ENABLE_NEWSLETTER_REPLIES`
- Sends replies via Buttondown API

### 2.3 Newsletter CTA

Append to every newsletter email in `agent/newsletter.py`:

```markdown
---
*Have a topic you'd like me to explore? Just reply to this email.*
```

### 2.4 Tests — `tests/test_newsletter_replies.py`

- Safety screening of incoming subscriber messages
- Reply composition and sending
- Per-subscriber rate limiting with hashed identifiers
- Token budget enforcement
- State persistence and cleanup
- Feature gate behavior

### 2.5 Environment Variables

| Variable | Purpose |
|----------|---------|
| `ENABLE_NEWSLETTER_REPLIES` | Feature gate for writer replies to subscribers |

Reuses existing `BUTTONDOWN_API_KEY` and `BUTTONDOWN_USERNAME`.

---

## Feature 3: Bluesky Mentions as Suggestions

**Ships third. Extends existing Bluesky integration.**

### 3.1 Mention Scanning

Extend `agent/bluesky_replies.py` (or add to `agent/suggestions.py`):
- Scan mentions (not just replies to own posts) for suggestion-like content
- Differentiate: replies to posts are handled by existing reply bot; standalone mentions with suggestion-like phrasing become topic suggestions
- Safety-screen via `llm.check_safety()`
- Add to `suggestions.json` with `source: "bluesky"`, handle stored as-is (public)

### 3.2 Heuristic for "Is This a Suggestion?"

Not every mention is a topic suggestion. Use a simple heuristic:
- Mention contains phrases like "write about", "topic suggestion", "you should explore", "I'd love to read about"
- Or: run a lightweight LLM classification call (adds token cost)
- Fallback: treat all mentions as potential suggestions and let the writer decide (simplest, most in character)

### 3.3 Rate Limit

2 suggestions per Bluesky handle per 30 days. Handle stored directly (public identifier).

### 3.4 Tests

- Mention detection and filtering
- Suggestion extraction from mention text
- Rate limiting by handle
- Integration with existing reply bot (no double-processing)

---

## Files Summary

### Feature 1 (Core + Web Form)

| Action | File |
|--------|------|
| Create | `system/suggestions.json` |
| Create | `agent/suggestions.py` |
| Create | `tests/test_suggestions.py` |
| Create | `api/function_app.py` |
| Create | `api/host.json` |
| Create | `api/requirements.txt` |
| Create | `scripts/screen_suggestion.py` |
| Create | `scripts/append_suggestion.py` |
| Create | `site/content/suggest.md` |
| Create | `site/staticwebapp.config.json` |
| Create | `.github/workflows/ingest-suggestion.yml` |
| Create | `.github/ISSUE_TEMPLATE/topic-suggestion.yml` |
| Modify | `agent/main.py` — suggestion loading, screening, prompt injection |
| Modify | `.github/workflows/autonomous-loop.yml` — git add suggestions.json |
| Modify | `.github/workflows/azure-static-web-apps-zealous-water-001fe8510.yml` — api_location |
| Modify | `site/hugo.yaml` — menu item |
| Modify | `.gitignore` — api artifacts |
| Modify | `CLAUDE.md` — docs |

### Feature 2 (Newsletter)

| Action | File |
|--------|------|
| Create | `agent/newsletter_replies.py` |
| Create | `system/newsletter_reply_state.json` |
| Create | `tests/test_newsletter_replies.py` |
| Modify | `agent/llm.py` — add `compose_email_reply()` |
| Modify | `agent/newsletter.py` — add CTA, add reply-fetching helper |
| Modify | `agent/main.py` — newsletter replies step, newsletter suggestion ingestion |
| Modify | `.github/workflows/autonomous-loop.yml` — git add newsletter state |
| Modify | `CLAUDE.md` — docs |

### Feature 3 (Bluesky Mentions)

| Action | File |
|--------|------|
| Modify | `agent/bluesky_replies.py` or `agent/suggestions.py` — mention scanning |
| Modify | `agent/main.py` — Bluesky suggestion ingestion |
| Create | `tests/test_bluesky_suggestions.py` |
| Modify | `CLAUDE.md` — docs |

---

## Verification Checklist

### Feature 1
- [ ] `uv run pytest tests/test_suggestions.py` passes
- [ ] `uv run pytest tests/` — no regressions
- [ ] `cd site && hugo` builds without errors, `/suggest/` page renders
- [ ] Local agent run with `FORCE_POST=true ENABLE_SUGGESTIONS=true` — suggestions appear in topic prompt
- [ ] Deploy: `POST /api/suggest` with auth returns 200
- [ ] Deploy: `POST /api/suggest` without auth returns 401/redirect
- [ ] Workflow dispatch fires and commits suggestion to `suggestions.json`
- [ ] Llama Guard blocks unsafe suggestion in ingest workflow (no commit)
- [ ] Rate limit blocks excessive submissions from same user

### Feature 2
- [ ] `uv run pytest tests/test_newsletter_replies.py` passes
- [ ] Newsletter emails include suggestion CTA
- [ ] Writer replies to subscriber emails (capped, safety-checked)
- [ ] Subscriber replies parsed for topic suggestions
- [ ] No PII (email addresses) in committed state files

### Feature 3
- [ ] Bluesky mentions detected and parsed for suggestions
- [ ] No double-processing between reply bot and suggestion ingestion
- [ ] Rate limit enforced per handle
