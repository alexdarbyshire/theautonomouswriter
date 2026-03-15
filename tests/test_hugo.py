import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.hugo import _rebuild_post, _split_post, validate_and_fix


@pytest.fixture
def site_dir(tmp_path):
    return tmp_path / "site"


@pytest.fixture
def post_path(tmp_path):
    posts = tmp_path / "site" / "content" / "posts"
    posts.mkdir(parents=True)
    return posts / "2026-03-15-test-post.md"


@pytest.fixture
def mock_llm():
    return MagicMock()


def _make_post(post_path, fm_dict, body="## Hello\n\nSome content here.\n"):
    """Write a post with given frontmatter dict."""
    post_path.write_text(_rebuild_post(fm_dict, body))


class TestSplitPost:
    def test_splits_correctly(self):
        content = '---\ntitle: "Test"\n---\n\nBody here.\n'
        fm, body = _split_post(content)
        assert 'title: "Test"' in fm
        assert "Body here." in body

    def test_returns_none_no_delimiters(self):
        assert _split_post("No frontmatter here\n") is None


class TestRebuildPost:
    def test_produces_valid_frontmatter(self):
        fm = {"title": "Hello: World", "tags": ["a", "b"], "draft": False}
        result = _rebuild_post(fm, "Body\n")
        assert result.startswith("---\n")
        assert '"Hello: World"' in result
        assert '["a", "b"]' in result
        assert "Body\n" in result


class TestValidateAndFix:
    def test_passes_on_first_try(self, post_path, site_dir, mock_llm):
        _make_post(post_path, {"title": "OK", "date": "2026-03-15", "slug": "ok", "description": "d", "tags": ["a"], "draft": False})
        with patch("agent.hugo.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            assert validate_and_fix(post_path, site_dir, mock_llm)
            assert mock_run.call_count == 1
            mock_llm.fix_frontmatter.assert_not_called()

    def test_fixes_and_retries(self, post_path, site_dir, mock_llm):
        _make_post(post_path, {"title": "Broken", "date": "2026-03-15", "slug": "broken", "description": "d", "tags": ["a"], "draft": False})
        fixed = {"title": "Fixed", "date": "2026-03-15", "slug": "broken", "description": "d", "tags": ["a"], "draft": False}
        mock_llm.fix_frontmatter.return_value = json.dumps(fixed)

        fail = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="YAML error")
        success = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("agent.hugo.subprocess.run", side_effect=[fail, success]):
            assert validate_and_fix(post_path, site_dir, mock_llm)
            mock_llm.fix_frontmatter.assert_called_once()

    def test_exhausts_retries(self, post_path, site_dir, mock_llm):
        _make_post(post_path, {"title": "OK", "date": "2026-03-15", "slug": "ok", "description": "d", "tags": ["a"], "draft": False})
        fixed = {"title": "Still Broken", "date": "2026-03-15", "slug": "ok", "description": "d", "tags": ["a"], "draft": False}
        mock_llm.fix_frontmatter.return_value = json.dumps(fixed)

        fail = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="persistent error")
        with patch("agent.hugo.subprocess.run", return_value=fail):
            assert not validate_and_fix(post_path, site_dir, mock_llm, max_attempts=3)
            # LLM called on attempts 1 and 2 (not on attempt 3 since that's the last)
            assert mock_llm.fix_frontmatter.call_count == 2

    def test_hugo_not_found_returns_true(self, post_path, site_dir, mock_llm):
        _make_post(post_path, {"title": "OK"})
        with patch("agent.hugo.subprocess.run", side_effect=FileNotFoundError):
            assert validate_and_fix(post_path, site_dir, mock_llm)
            mock_llm.fix_frontmatter.assert_not_called()

    def test_llm_fix_failure_returns_false(self, post_path, site_dir, mock_llm):
        _make_post(post_path, {"title": "OK", "date": "2026-03-15", "slug": "ok", "description": "d", "tags": ["a"], "draft": False})
        mock_llm.fix_frontmatter.return_value = "not valid json"

        fail = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="YAML error")
        with patch("agent.hugo.subprocess.run", return_value=fail):
            assert not validate_and_fix(post_path, site_dir, mock_llm)
