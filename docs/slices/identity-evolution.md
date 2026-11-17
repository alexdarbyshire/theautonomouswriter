# Identity evolution

Approved repair, narrowed by the user to preserve existing response handling.
Baseline: merged main `a4c6c43`. Shared language: [CONTEXT.md](../../CONTEXT.md).

## Contract

- Give reflection a dedicated LLM request with a 4096-token output allowance
  and the existing temperature. Keep frontmatter extraction at 400 tokens.
- Keep existing JSON parsing, optional response fields, and the identity-string
  check. Do not add a response model, reject extra fields, or require nonblank
  mood and reflection values.
- Record the outcome: identity retained, identity changed, or reflection failed.
- Preserve the existing identity instructions and optional evolution. No
  identity-change frequency is required.
- Malformed JSON or an unavailable reflection returns no update. The existing
  caller continues publication after reflection failure.

## Verification

Exercise `reflect_and_evolve` with temporary prompt files and controlled LLM
responses. Check complete identity replacement, optional fields, retained
identity, and malformed or unavailable responses. Check the separate request
allowances and publication continuing after reflection failure. Run the Python
suite and Ruff checks. Human acceptance and merge remain pending.

No edits to current identity wording, experiment state, historical posts,
scheduling, suggestion presentation, or frontmatter behavior.
