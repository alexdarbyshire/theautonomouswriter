from datetime import datetime, timedelta, timezone
from agent.scheduler import should_post, next_post_time


def test_should_post_null_means_first_run():
    memory = {"next_scheduled_post": None}
    assert should_post(memory) is True


def test_should_post_missing_key_means_first_run():
    assert should_post({}) is True


def test_should_post_past_timestamp():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    memory = {"next_scheduled_post": past}
    assert should_post(memory) is True


def test_should_post_future_timestamp():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    memory = {"next_scheduled_post": future}
    assert should_post(memory) is False


def test_next_post_time_in_range():
    result = next_post_time()
    now = datetime.now(timezone.utc)
    delta = result - now
    assert 3.5 <= delta.total_seconds() / 86400 <= 5.5


def test_next_post_time_is_utc():
    result = next_post_time()
    assert result.tzinfo == timezone.utc
