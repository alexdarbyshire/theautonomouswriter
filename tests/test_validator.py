from agent.validator import (
    run_all_checks,
    validate_date_format,
    validate_frontmatter_fields,
    validate_no_empty_sections,
    validate_no_placeholders,
    validate_slug_unique,
    validate_word_count,
)


def test_slug_unique_passes():
    assert validate_slug_unique("new-post", ["old-post"])[0] is True


def test_slug_unique_fails():
    passed, reason = validate_slug_unique("old-post", ["old-post"])
    assert passed is False
    assert "already exists" in reason


def test_word_count_passes():
    body = " ".join(["word"] * 400)
    assert validate_word_count(body)[0] is True


def test_word_count_fails():
    body = " ".join(["word"] * 50)
    passed, reason = validate_word_count(body)
    assert passed is False
    assert "below minimum" in reason


def test_frontmatter_valid():
    data = {
        "title": "A Valid Blog Post Title Here",
        "date": "2026-03-15",
        "slug": "a-valid-blog-post",
        "description": "This is a valid description for the post.",
        "tags": ["python", "ai"],
        "draft": False,
    }
    assert validate_frontmatter_fields(data)[0] is True


def test_frontmatter_bad_slug():
    data = {
        "title": "A Valid Blog Post Title Here",
        "date": "2026-03-15",
        "slug": "BAD SLUG",
        "description": "This is a valid description for the post.",
        "tags": ["python"],
        "draft": False,
    }
    passed, reason = validate_frontmatter_fields(data)
    assert passed is False
    assert "validation failed" in reason.lower()


def test_frontmatter_draft_true():
    data = {
        "title": "A Valid Blog Post Title Here",
        "date": "2026-03-15",
        "slug": "a-valid-post",
        "description": "This is a valid description for the post.",
        "tags": ["python"],
        "draft": True,
    }
    passed, _ = validate_frontmatter_fields(data)
    assert passed is False


def test_no_placeholders_clean():
    assert validate_no_placeholders("This is a normal blog post body.")[0] is True


def test_no_placeholders_todo():
    passed, reason = validate_no_placeholders("This has a TODO item")
    assert passed is False
    assert "TODO" in reason


def test_no_placeholders_insert():
    passed, _ = validate_no_placeholders("Something [INSERT your name here]")
    assert passed is False


def test_no_empty_sections_clean():
    body = "## Intro\nSome content here.\n## Next\nMore content."
    assert validate_no_empty_sections(body)[0] is True


def test_no_empty_sections_fails():
    body = "## Intro\n## Next Section"
    passed, reason = validate_no_empty_sections(body)
    assert passed is False
    assert "Empty section" in reason


def test_date_format_valid():
    assert validate_date_format("2026-03-15")[0] is True


def test_date_format_invalid():
    passed, _ = validate_date_format("not-a-date")
    assert passed is False


def test_run_all_checks_passes():
    body = " ".join(["word"] * 450) + "\n## Heading\nContent here."
    data = {
        "title": "A Complete Valid Post Title",
        "date": "2026-03-15",
        "slug": "complete-valid-post",
        "description": "A thorough description of this post content.",
        "tags": ["testing"],
        "draft": False,
    }
    passed, reason = run_all_checks("complete-valid-post", body, data, [])
    assert passed is True
    assert reason == "All checks passed"


def test_run_all_checks_halts_on_first_failure():
    passed, reason = run_all_checks("dup-slug", "short", {}, ["dup-slug"])
    assert passed is False
    assert "already exists" in reason
