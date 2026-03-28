from unittest.mock import MagicMock, patch

from agent.bluesky import _generate_announcement, _truncate_announcement, post_to_bluesky


def test_disabled_when_flag_off(monkeypatch):
    monkeypatch.delenv("ENABLE_BLUESKY", raising=False)
    assert post_to_bluesky("Title", "Desc", "slug") is False


def test_disabled_when_credentials_missing(monkeypatch):
    monkeypatch.setenv("ENABLE_BLUESKY", "true")
    monkeypatch.delenv("BLUESKY_HANDLE", raising=False)
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)
    assert post_to_bluesky("Title", "Desc", "slug") is False


def test_successful_post(monkeypatch):
    monkeypatch.setenv("ENABLE_BLUESKY", "true")
    monkeypatch.setenv("BLUESKY_HANDLE", "test.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "test-pass")

    mock_client = MagicMock()
    mock_client.send_post.return_value = MagicMock(uri="at://did:plc:123/app.bsky.feed.post/abc")

    mock_text_builder = MagicMock()
    mock_text_builder.text.return_value = mock_text_builder
    mock_text_builder.link.return_value = mock_text_builder

    mock_client_utils = MagicMock()
    mock_client_utils.TextBuilder.return_value = mock_text_builder

    mock_atproto = MagicMock(
        Client=MagicMock(return_value=mock_client),
        client_utils=mock_client_utils,
    )

    with patch.dict("sys.modules", {"atproto": mock_atproto}):
        import importlib

        import agent.bluesky

        importlib.reload(agent.bluesky)

        mock_llm = MagicMock()
        mock_llm.compose_bluesky_post.return_value = "Just wrote something new."

        result = agent.bluesky.post_to_bluesky(
            "My Title",
            "A description",
            "my-slug",
            llm=mock_llm,
            mood="curious",
        )
        assert result is True

    mock_client.login.assert_called_once_with("test.bsky.social", "test-pass")
    mock_client.send_post.assert_called_once_with(mock_text_builder)
    mock_text_builder.text.assert_called_once_with("Just wrote something new.\n\n")
    mock_text_builder.link.assert_called_once()
    link_args = mock_text_builder.link.call_args[0]
    assert "my-slug" in link_args[0]


def test_graceful_failure_on_api_error(monkeypatch):
    monkeypatch.setenv("ENABLE_BLUESKY", "true")
    monkeypatch.setenv("BLUESKY_HANDLE", "test.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "test-pass")

    mock_client = MagicMock()
    mock_client.login.side_effect = Exception("auth failed")

    with patch.dict("sys.modules", {"atproto": MagicMock(Client=MagicMock(return_value=mock_client))}):
        import importlib

        import agent.bluesky

        importlib.reload(agent.bluesky)
        assert agent.bluesky.post_to_bluesky("Title", "Desc", "slug") is False


def test_generate_announcement_uses_llm():
    mock_llm = MagicMock()
    mock_llm.compose_bluesky_post.return_value = "I wrote a thing."
    result = _generate_announcement("Title", "Desc", "curious", mock_llm)
    assert result == "I wrote a thing."


def test_generate_announcement_falls_back_on_llm_failure():
    mock_llm = MagicMock()
    mock_llm.compose_bluesky_post.side_effect = Exception("LLM down")
    result = _generate_announcement("Title", "Desc", "curious", mock_llm)
    assert result == "Title\n\nDesc"


def test_generate_announcement_falls_back_without_llm():
    result = _generate_announcement("Title", "Desc", "curious", None)
    assert result == "Title\n\nDesc"


def test_truncate_announcement_no_change():
    result = _truncate_announcement("Just wrote something new.", "https://example.com/posts/slug/")
    assert result == "Just wrote something new."


def test_truncate_announcement_truncates_long_text():
    url = "https://theautonomouswriter.com/posts/long-slug/"
    announcement = "A" * 300  # way too long
    result = _truncate_announcement(announcement, url)
    # announcement + \n\n + url must fit in 300 graphemes
    full_text = result + "\n\n" + url
    assert len(full_text) <= 300
    assert result.endswith("...")
