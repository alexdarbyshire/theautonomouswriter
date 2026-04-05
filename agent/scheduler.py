from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.types import WriterMemory


def should_post(memory: WriterMemory) -> bool:
    next_scheduled = memory.get("next_scheduled_post")
    if next_scheduled is None:
        return True
    scheduled_time = datetime.fromisoformat(next_scheduled)
    if scheduled_time.tzinfo is None:
        scheduled_time = scheduled_time.replace(tzinfo=UTC)
    return datetime.now(UTC) >= scheduled_time


def next_post_time() -> datetime:
    days = random.uniform(3.5, 5.5)
    return datetime.now(UTC) + timedelta(days=days)
