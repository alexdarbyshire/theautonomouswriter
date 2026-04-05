from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.types import ResearchSource

logger = logging.getLogger(__name__)


def research_topic(topic: str) -> list[ResearchSource] | None:
    if os.environ.get("ENABLE_RESEARCH", "").lower() != "true":
        logger.info("Research disabled (ENABLE_RESEARCH not set to 'true')")
        return None

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        logger.warning("TAVILY_API_KEY not set, skipping research")
        return None

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
        result = client.search(query=topic, max_results=5)
        sources = []
        for item in result.get("results", []):
            sources.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                }
            )
        logger.info("Research complete: %d results for '%s'", len(sources), topic)
        return sources if sources else None
    except Exception as e:
        logger.warning("Research failed, continuing without: %s", e)
        return None
