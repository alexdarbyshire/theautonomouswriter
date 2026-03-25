from unittest.mock import MagicMock, patch

from agent.researcher import research_topic


def test_disabled_when_flag_off(monkeypatch):
    monkeypatch.delenv("ENABLE_RESEARCH", raising=False)
    assert research_topic("test topic") is None


def test_disabled_when_api_key_missing(monkeypatch):
    monkeypatch.setenv("ENABLE_RESEARCH", "true")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert research_topic("test topic") is None


def test_returns_structured_sources(monkeypatch):
    monkeypatch.setenv("ENABLE_RESEARCH", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    mock_result = {
        "results": [
            {"title": "Source One", "url": "https://example.com/one", "content": "Content one"},
            {"title": "Source Two", "url": "https://example.com/two", "content": "Content two"},
        ]
    }
    mock_client = MagicMock()
    mock_client.search.return_value = mock_result

    with patch("tavily.TavilyClient", return_value=mock_client) as mock_cls:
        sources = research_topic("test topic")

    mock_cls.assert_called_once_with(api_key="test-key")
    assert len(sources) == 2
    assert sources[0] == {"title": "Source One", "url": "https://example.com/one", "content": "Content one"}
    assert sources[1]["url"] == "https://example.com/two"


def test_returns_none_on_empty_results(monkeypatch):
    monkeypatch.setenv("ENABLE_RESEARCH", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    mock_client = MagicMock()
    mock_client.search.return_value = {"results": []}

    with patch("tavily.TavilyClient", return_value=mock_client):
        assert research_topic("test topic") is None


def test_returns_none_on_exception(monkeypatch):
    monkeypatch.setenv("ENABLE_RESEARCH", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    with patch("tavily.TavilyClient", side_effect=RuntimeError("fail")):
        assert research_topic("test topic") is None
