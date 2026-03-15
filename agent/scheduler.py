import random
from datetime import datetime, timedelta, timezone


def should_post(memory: dict) -> bool:
    next_scheduled = memory.get("next_scheduled_post")
    if next_scheduled is None:
        return True
    scheduled_time = datetime.fromisoformat(next_scheduled)
    if scheduled_time.tzinfo is None:
        scheduled_time = scheduled_time.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= scheduled_time


def next_post_time() -> datetime:
    days = random.uniform(3.5, 5.5)
    return datetime.now(timezone.utc) + timedelta(days=days)
