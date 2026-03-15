---
description: Pydantic v2 patterns for strict validation of LLM-generated JSON output
---

# Pydantic v2 Strict Validation

Use Pydantic v2 for all structured data validation in this project, especially LLM output parsing.

## Patterns
- Use `BaseModel` with `Field()` constraints (`min_length`, `max_length`, `min_items`, `max_items`)
- Use `@field_validator` for custom validation logic (e.g., slug format, draft must be false)
- Parse LLM JSON responses with `Model.model_validate_json()` — never manually parse frontmatter from markdown body
- On validation failure, let `ValidationError` propagate with its structured error messages

## Project-specific models
- `PostFrontmatter` in `agent/models.py` — validates title, date, slug, description, tags, draft fields
- Slug must be lowercase kebab-case: `^[a-z0-9]+(?:-[a-z0-9]+)*$`
- `draft` field must always be `False` for published posts
- Tags: 1–8 items

## Anti-patterns to avoid
- Do not use `model_validate()` with `dict` when you have raw JSON — use `model_validate_json()` directly
- Do not catch `ValidationError` and silently continue — validation failures must halt the pipeline
- Do not add `Optional` fields to the frontmatter model unless the spec requires them
