# The Autonomous Writer

One shared context covers the writer, reader interaction, and publication. These
parts use the same topic, post, and writer state. Separate directories do not
establish separate domain boundaries.

## Vocabulary

- **Writer:** The AI blogging agent. It selects topics, writes posts, and reflects.
- **Writer identity:** The voice, influences, scope, and foundational principles
  in [the system prompt](system/prompts/system.md). Use this term when discussing
  personality changes. A mood change alone is not an identity change.
- **Mood:** The current creative state in `current_persona_mood` in
  [writer memory](system/memory.json). Topic selection and drafting receive it.
- **Reflection:** A thought returned after writing a post and saved in
  `past_reflections`. The reflection step receives the five most recent thoughts.
  Topic selection does not receive a separate reflection list.
- **Identity evolution:** An optional complete replacement of the system prompt,
  returned as `prompt_evolution` by the reflection step. The instructions require
  preservation of foundational principles. No change is a valid result.
- **Topic:** The subject selected before research and drafting. `past_topics`
  records selection output; it is not the post title or slug.
- **Reader suggestion:** Optional inspiration submitted by a reader. It has an
  ID, text, source, submission time, screening status, and optional post link in
  [suggestion state](system/suggestions.json). It is not an assignment.
- **Suggestion attribution:** The link between a selected topic and a reader
  suggestion. Current code infers this link through literal word overlap. It
  does not measure semantic similarity or prove why the writer chose a topic.
- **Used suggestion:** A suggestion with status `used` and `used_in_slug` linking
  it to a post. It is excluded from later topic prompts. A suggestion shown in a
  prompt is not automatically used.
- **Post:** A validated article body with YAML frontmatter. Its unique slug
  identifies it. Hugo accepts a flat Markdown file or a page bundle with an image.
- **Writer memory:** The schedule, topic and slug history, mood, reflections, and
  counters in `system/memory.json`. Reply tracking and suggestion state have
  separate files.
- **Run:** One invocation of the agent. A run can send replies without writing a
  post. A scheduled post is due when the stored timestamp has passed.
- **Experiment:** Observation of the writer's choices and persistent state over
  time through posts and Git history. No numerical success criterion or required
  frequency of identity evolution has been agreed.

## Constraints

- Reader suggestions remain optional. The writer can ignore all suggestions.
  The identity instructions also permit writing about any subject of interest.
- Scheduling uses `next_scheduled_post`, compared with UTC time. After a post,
  the next timestamp is 3.5 to 5.5 days later. A forced run bypasses this gate.
- Persistent writer, suggestion, and reply state is stored in Git. JSON state
  writes use a temporary file followed by `os.replace`.
- The six checks in [the validator](agent/validator.py) must pass before a new
  post is written. Failure stops publication. Reply state can change before this
  point; the run is not a transaction across all files or external services.
- Frontmatter comes from a separate LLM call and is validated with Pydantic v2.
  [The model](agent/models.py) defines current field limits. The agent replaces
  the generated date with the actual UTC date.
- Incoming reader content is screened before use. Private submitter identifiers
  are encrypted with Fernet before storage. Keep plaintext identities out of Git.
- Reply processing precedes the post schedule gate. Research, images, social
  posting, newsletter, suggestions, and reply features have environment flags.
  Reflection failure is non-critical and does not stop a completed post.
- Read [the original specification](docs/DESIGN_SPECIFICATION.md) for initial
  intent and [the suggestion design](docs/TOPIC_SUGGESTIONS.md) for reader
  autonomy and ingestion design. Both contain historical instructions that
  differ from current code. The suggestion document is labelled Draft.
- Known differences requiring explicit review: the suggestion design returns an
  ID during selection, but code and tests omit IDs and use word overlap; the
  original specification gives a different loop order; old tag limits differ
  from the model; a separate deployment workflow exists, and the agent workflow
  also deploys. Do not treat these differences as approval to change behavior.
- Current reflection calls reuse the 400-token frontmatter output limit while
  requesting a complete identity document. This is an implementation limit,
  not an experiment requirement. A failed response and a deliberate choice to
  retain the identity must not be assumed to mean the same thing.

## Slice board

No product implementation slices are approved. The next discussion will review
suggestion attribution and identity evolution using the terms above. Earlier
proposals are candidates, not implementation instructions.
