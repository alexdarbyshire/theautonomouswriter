# Cover model upgrade

## Approved scope

One vertical slice, authorized in the implementation request on 2026-11-18.
Replace the three cover generators with these fixed OpenRouter model IDs:

- `openai/gpt-image-2.5-sunburst`
- `microsoft/mai-image-2.7`
- `google/gemini-nano-banana-2.1`

Keep model selection in code, the existing OpenRouter key, parallel generation,
optional covers, and the main writer model as the vision judge. Do not change
writer identity, prose model, existing posts or stored experiment state. Do not
convert formats or add a dependency merely to do so.

## Public seam and acceptance

`generate_cover_image()` returns an image value containing original bytes and
verified PNG/JPEG/WebP MIME type, or None. `agent/main.py` saves those bytes with
the corresponding extension and points cover frontmatter at that exact file.
The judge receives matching MIME types for every candidate. Existing PNG posts
are untouched. Disabled images make no API requests; one surviving candidate
skips judging; failed candidates do not discard successes; total generation
failure produces a post without a cover; judge failure retains the existing
first-completed-candidate fallback.

Use OpenRouter's dedicated `POST /api/v1/images` where supported. Parse raw JSON
with Pydantic v2, reject malformed base64 and unsupported or mismatched formats,
and never treat error responses as images. Keep timeouts bounded. Verify the
selected models' documented request paths; do not assume the OpenAI SDK's
`images.generate()` path is OpenRouter's `/images` path.

The public Image API catalog confirms all three IDs are supported, so use one
request path instead of maintaining separate provider adapters. Keep the square
cover composition and request one candidate per model.

Validation must cover outbound request contracts, mixed-format candidates and
judge requests, partial/total failures, and actual post file/frontmatter output
through controlled external boundaries. Run the repository test/lint/format and
Node gates; build with Hugo 0.170.1 from site/. No live writer or paid generation
is part of this slice. Done for this request means tested implementation pushed
and a PR open for human acceptance, not merged.

## Sources

Checked 2026-11-18:

- https://openrouter.ai/blog/tutorials/image-generation/
- https://openrouter.ai/openai/gpt-image-2.5-sunburst
- https://openrouter.ai/microsoft/mai-image-2.7
- https://openrouter.ai/google/gemini-nano-banana-2.1
- https://openrouter.ai/api/v1/images/models
- https://arena.ai/leaderboard/image/text-to-image (2026-11-16 snapshot)

## Status

Implementation verified; ready for PR review and human acceptance. Independent
testing passed 135 Python tests, Ruff lint and formatting, and 10 form tests
(local Node 24; CI uses Node 26). Hugo 0.170.1 built successfully. Independent
review found no Spec or Standards issues. No paid generation or live writer run
was performed.

Board review: Grounding and Shape pass against the approved conversation and
repository context at `7bfb3c5`. One slice covers generation through publication;
it has no prerequisite slice or external tracker. Human acceptance remains PR
review; merge is outside this request.
