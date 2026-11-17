# Present reader suggestions once per completed writing cycle

Revised scope: the user's decision to replace LLM attribution with deterministic
presentation bookkeeping, 17 November 2026. Baseline: merged main `6cd8c95`.
Shared terms and constraints: [CONTEXT.md](../../CONTEXT.md).

## Contract

The application offers up to five safe reader suggestions in the topic-selection
prompt. It records their exact IDs internally; the prompt contains only their
text. The writer returns a topic as a short phrase. Suggestions remain optional:
the topic can be unrelated to every offered suggestion.

After post validation and a successful Hugo build, mark every offered suggestion
as `presented`. Save suggestion state at the existing persistence stage. Exclude
presented suggestions from later topic prompts. A failed selection, draft,
validation, or build leaves those suggestions available for retry. Suggestions
beyond the prompt cap are not presented and remain available.

The state records an application action, not model attention, agreement, or
influence. Drafting receives the same suggestion text and may acknowledge a
reader if a suggestion inspired the topic and acknowledgement serves the piece.
There is no attribution response, word-overlap inference, or post-slug link.
Presented and expired records are retained; unsafe records are removed after seven days.

## Ownership And Verification

`agent/main.py` captures the exact offered IDs and owns the post-build transition.
`agent/suggestions.py` formats suggestion text, updates offered safe records,
filters later prompts, and applies retention. Topic selection, frontmatter,
Hugo repair, and their model request settings retain their original interfaces.
The obsolete empty post-link field is removed from suggestion metadata.
Suggestion text, lifecycle status, and historical posts are unchanged.

`tests/test_suggestion_presentation.py` exercises `main()` with actual validation and
persistence, temporary files, and controlled SDK and Hugo process boundaries.
It covers an unrelated topic retiring all offered suggestions, exclusion on the
next cycle, the five-item cap, disabled and absent suggestions, and failure paths.
`tests/test_suggestions.py` covers state transitions, prompt text, and retention.

Run the Python suite, form tests, Ruff checks, and whitespace checks. Independent
review, human acceptance, and merge remain required. The completed slice is
removed from the context board when this PR lands; identity evolution remains
open separately. This change does not create a transaction across files or
external services.
