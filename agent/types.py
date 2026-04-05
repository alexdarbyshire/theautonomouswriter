"""Shared type definitions for the agent package."""

from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable

# -- atproto SDK structural types (used in bluesky_replies.py) --


class _HasText(Protocol):
    text: str


class _HasDid(Protocol):
    did: str


class BlueskyPostRecord(Protocol):
    uri: str
    cid: str
    author: _HasDid
    record: _HasText


@runtime_checkable
class BlueskyThread(Protocol):
    post: BlueskyPostRecord
    parent: BlueskyThread | None


class BlueskyNotification(Protocol):
    reason: str
    uri: str
    cid: str


class _BskyFeedNS(Protocol):
    def get_post_thread(self, params: dict[str, object]) -> _HasThread: ...


class _HasThread(Protocol):
    thread: BlueskyThread


class _BskyNotificationNS(Protocol):
    def list_notifications(self, params: dict[str, object]) -> _HasNotifications: ...


class _HasNotifications(Protocol):
    notifications: list[BlueskyNotification] | None


class _BskyAppNS(Protocol):
    @property
    def feed(self) -> _BskyFeedNS: ...
    @property
    def notification(self) -> _BskyNotificationNS: ...


class _BskyNS(Protocol):
    @property
    def bsky(self) -> _BskyAppNS: ...


class BlueskyClient(Protocol):
    @property
    def app(self) -> _BskyNS: ...
    def send_post(self, text: object, reply_to: object = ...) -> _HasUri: ...


class _HasUri(Protocol):
    uri: str


class UsageDict(TypedDict):
    prompt_tokens: int
    completion_tokens: int


class WriterMemory(TypedDict, total=False):
    past_topics: list[str]
    past_slugs: list[str]
    past_reflections: list[str]
    last_run_timestamp: str
    last_post_timestamp: str
    next_scheduled_post: str
    current_persona_mood: str
    total_posts_written: int
    consecutive_skip_count: int
    last_newsletter_at_post_count: int


class EvolveResult(TypedDict, total=False):
    mood: str
    reflection: str
    prompt_evolution: str | None


class SuggestionEntry(TypedDict, total=False):
    id: str
    source: str
    text: str
    submitter_encrypted: str
    submitted_at: str
    status: str
    safety_reason: str | None
    used_in_slug: str | None


class SuggestionsData(TypedDict, total=False):
    suggestions: list[SuggestionEntry]
    processed_issues: list[str]
    processed_reply_ids: list[str]
    last_cleanup: str | None


class BlueskyState(TypedDict):
    replied_uris: list[str]
    thread_reply_counts: dict[str, int]


class BlueskyStats(TypedDict):
    replies_sent: int
    tokens_used: int
    skipped_unsafe: int


class NewsletterReplyState(TypedDict):
    replied_ids: list[str]
    subscriber_reply_counts: dict[str, int]


class NewsletterReplyStats(TypedDict):
    replies_sent: int
    tokens_used: int
    skipped_unsafe: int
    suggestions_found: int


class ResearchSource(TypedDict):
    title: str
    url: str
    content: str


class PostMetadata(TypedDict, total=False):
    title: str
    date: str
    slug: str
    description: str
    tags: list[str]
    url: str
