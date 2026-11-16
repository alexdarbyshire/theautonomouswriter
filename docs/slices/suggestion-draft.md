# Preserve suggestion drafts through sign-in

## Contract

Approved by the user on 17 November 2026. Baseline: `b785da0`.
The public seam is the suggestion form at `/suggest/`. Google sign-in returns
to this page in the same tab. Use browser session storage so a draft survives
that navigation without requiring storage across browser sessions.

- Save text as the reader types; restore it on page load.
- Restore the character count and valid Submit button state.
- Require an explicit Submit action after sign-in; never send automatically.
- Keep the draft after cancelled sign-in, an API rejection, or a network error.
- Remove the draft when the reader deletes the text or submission succeeds.
- Preserve edits made while an earlier submission is pending.
- If storage is unavailable, keep the form usable and warn before sign-in.
- Preserve the auth routes, backend contract, and existing page styling.

## Verification And Completion

Run `node tests/test_suggestion_form.cjs`. The tests execute the actual page
script with browser storage, DOM, auth, and API substitutes. They cover return
from sign-in, reload, cancellation, submission success and failure, blocked
storage, deletion, and edits during submission. The existing CI workflow runs
these tests with Node 22 and no package dependencies.

Run a Hugo build from `site/`, plus the repository lint and Python test gates.
Human review and merge remain required before this slice is complete. Real
Google sign-in has not been automated by these deterministic tests.
