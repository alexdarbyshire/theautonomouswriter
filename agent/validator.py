import re
from datetime import date

from pydantic import ValidationError

from agent.models import PostFrontmatter


def validate_slug_unique(slug: str, past_slugs: list[str]) -> tuple[bool, str]:
    if slug in past_slugs:
        return False, f"Slug '{slug}' already exists in past_slugs"
    return True, "Slug is unique"


def validate_word_count(body: str) -> tuple[bool, str]:
    count = len(body.split())
    if count < 400:
        return False, f"Word count {count} is below minimum 400"
    return True, f"Word count {count} is acceptable"


def validate_frontmatter_fields(frontmatter_data: dict) -> tuple[bool, str]:
    try:
        PostFrontmatter.model_validate(frontmatter_data)
        return True, "Frontmatter validation passed"
    except ValidationError as e:
        return False, f"Frontmatter validation failed: {e}"


def validate_no_placeholders(body: str) -> tuple[bool, str]:
    patterns = [r"\bTODO\b", r"\bPLACEHOLDER\b", r"\[INSERT"]
    for pattern in patterns:
        match = re.search(pattern, body)
        if match:
            return False, f"Placeholder found: '{match.group()}'"
    return True, "No placeholders found"


def validate_no_empty_sections(body: str) -> tuple[bool, str]:
    lines = body.strip().split("\n")
    for i in range(len(lines) - 1):
        current = lines[i].strip()
        next_line = lines[i + 1].strip()
        if current.startswith("##") and next_line.startswith("##"):
            return False, f"Empty section: '{current}' followed immediately by '{next_line}'"
    return True, "No empty sections found"


def validate_date_format(date_str: str) -> tuple[bool, str]:
    try:
        if isinstance(date_str, date):
            return True, "Date is valid"
        date.fromisoformat(str(date_str))
        return True, "Date is valid ISO 8601"
    except (ValueError, TypeError) as e:
        return False, f"Invalid date format: {e}"


def run_all_checks(
    slug: str,
    body: str,
    frontmatter_data: dict,
    past_slugs: list[str],
) -> tuple[bool, str]:
    checks = [
        lambda: validate_slug_unique(slug, past_slugs),
        lambda: validate_word_count(body),
        lambda: validate_frontmatter_fields(frontmatter_data),
        lambda: validate_no_placeholders(body),
        lambda: validate_no_empty_sections(body),
        lambda: validate_date_format(frontmatter_data.get("date", "")),
    ]
    for check in checks:
        passed, reason = check()
        if not passed:
            return False, reason
    return True, "All checks passed"
