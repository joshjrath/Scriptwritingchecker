"""Drop-box mode: track assignments without any access to their server.

You forward the brief into a channel of your own server; the bot lives there
and nowhere else. Each forwarded brief becomes an assignment, and the bot opens
a thread on it so deliveries have somewhere to go - which means everything
downstream sees exactly the shape it already understands.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from .config import Config
from .models import Message, Thread
from .parsing import (
    deadline_text,
    extract_datetimes,
    parse_thread_title,
    split_role_sections,
)

#: Discord's limit for a thread name.
MAX_THREAD_NAME = 100


def looks_like_brief(text: str, config: Config) -> bool:
    """Is this message an assignment brief, or just chat?

    Deliberately narrow: a stray "thanks!" in the drop-box channel must not
    become a tracked assignment with no deadline, because that would train you
    to ignore the board's warnings.
    """

    if not text or not text.strip():
        return False

    my_roles = {r.strip().upper() for r in config.my_roles}
    sections = split_role_sections(text, config.known_roles)
    if any(section.role in my_roles for section in sections):
        return True

    # No role header, but a labelled deadline with a real date in it.
    labelled = deadline_text(text)
    if labelled and extract_datetimes(
        labelled,
        default_tz=config.default_timezone,
        assume_time=config.assume_time_obj,
        date_order=config.date_order,
    ):
        return True
    return False


def brief_title(text: str, config: Config, fallback: str = "Assignment") -> str:
    """A thread name for a brief: its title line if it has one."""

    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        info = parse_thread_title(line, date_order=config.date_order)
        if info.slot or info.slate_date:
            return line[:MAX_THREAD_NAME]
        # Strip heading and bullet markers, but leave * and _ alone:
        # they come in pairs, and halving them leaves "Heading**".
        cleaned = line.lstrip("#>-• ").strip()
        if cleaned:
            return cleaned[:MAX_THREAD_NAME]
    return fallback


def synthesize_thread(
    brief: Message,
    followups: Iterable[Message],
    config: Config,
    channel_name: str = "",
    guild_name: str = "",
    guild_id: str = "",
    channel_id: str = "",
    thread_name: str = "",
    jump_url: str = "",
    tags: Optional[list[str]] = None,
) -> Thread:
    """Fold a forwarded brief and its follow-ups into one Thread."""

    ordered = sorted(
        followups,
        key=lambda m: m.created_at or datetime.max.replace(tzinfo=timezone.utc),
    )
    return Thread(
        id=brief.id,
        name=thread_name or brief_title(brief.content, config),
        guild_id=guild_id,
        guild_name=guild_name,
        parent_id=channel_id,
        parent_name=channel_name,
        created_at=brief.created_at,
        tags=list(tags or []),
        jump_url=jump_url or brief.jump_url,
        messages=[brief] + ordered,
    )


def collect_from_messages(
    messages: list[Message],
    config: Config,
    replies_to: Optional[dict[str, str]] = None,
    thread_messages: Optional[dict[str, list[Message]]] = None,
    thread_names: Optional[dict[str, str]] = None,
    channel_name: str = "",
    guild_name: str = "",
    guild_id: str = "",
    channel_id: str = "",
) -> list[Thread]:
    """Turn one channel's messages into assignments.

    ``replies_to`` maps a message ID to the message it replies to, so a link
    posted as a reply counts even when no thread was opened.
    """

    replies_to = replies_to or {}
    thread_messages = thread_messages or {}
    thread_names = thread_names or {}

    briefs = [m for m in messages if looks_like_brief(m.content, config)]
    brief_ids = {m.id for m in briefs}

    followups: dict[str, list[Message]] = {b.id: [] for b in briefs}
    for message in messages:
        if message.id in brief_ids:
            continue
        parent = replies_to.get(message.id)
        if parent in followups:
            followups[parent].append(message)

    threads = []
    for brief in briefs:
        collected = followups[brief.id] + thread_messages.get(brief.id, [])
        threads.append(
            synthesize_thread(
                brief,
                collected,
                config,
                channel_name=channel_name,
                guild_name=guild_name,
                guild_id=guild_id,
                channel_id=channel_id,
                thread_name=thread_names.get(brief.id, ""),
            )
        )
    return threads
