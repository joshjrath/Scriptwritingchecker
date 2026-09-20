"""Fetch threads live with a Discord bot token.

Requires ``discord.py`` and a bot that is in the server with *Read Messages*,
*Read Message History* and the privileged **Message Content** intent.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional

from ..config import Config
from ..dropbox import collect_from_messages, looks_like_brief
from ..models import Attachment, Author, Message, Thread

try:  # pragma: no cover - exercised only with the optional dependency present
    import discord
except ImportError:  # pragma: no cover
    discord = None


class MissingDependency(RuntimeError):
    pass


def _require_discord():
    if discord is None:
        raise MissingDependency(
            "discord.py is not installed. Run: pip install -r requirements.txt"
        )
    return discord


def message_text(message) -> str:
    """All the readable text of a message, forwarded content included.

    Discord's Forward feature sends a message whose own `content` is empty and
    puts the original text in a snapshot. Reading only `content` would make
    every forwarded brief look blank, which is the whole input path here.
    """

    parts: list[str] = []
    if getattr(message, "content", ""):
        parts.append(message.content)

    for snapshot in getattr(message, "message_snapshots", None) or []:
        if getattr(snapshot, "content", ""):
            parts.append(snapshot.content)
        parts.extend(_embed_text(getattr(snapshot, "embeds", None) or []))

    parts.extend(_embed_text(getattr(message, "embeds", None) or []))
    return "\n".join(p for p in parts if p and p.strip())


def _embed_text(embeds) -> list[str]:
    out: list[str] = []
    for embed in embeds:
        for attr in ("title", "description"):
            value = getattr(embed, attr, None)
            if value:
                out.append(str(value))
        for field in getattr(embed, "fields", None) or []:
            name = getattr(field, "name", "") or ""
            value = getattr(field, "value", "") or ""
            if name or value:
                out.append(f"{name}\n{value}")
    return out


def message_attachments(message) -> list:
    """Attachments on the message and on anything forwarded with it."""

    found = list(getattr(message, "attachments", None) or [])
    for snapshot in getattr(message, "message_snapshots", None) or []:
        found.extend(getattr(snapshot, "attachments", None) or [])
    return found


def _convert_message(message) -> Message:
    return Message(
        id=str(message.id),
        author=Author(
            id=str(message.author.id),
            name=getattr(message.author, "name", "") or "",
            display_name=getattr(message.author, "display_name", "") or "",
            bot=bool(getattr(message.author, "bot", False)),
        ),
        content=message_text(message),
        created_at=message.created_at,
        edited_at=message.edited_at,
        attachments=[
            Attachment(filename=a.filename, url=a.url)
            for a in message_attachments(message)
        ],
        jump_url=message.jump_url,
    )


async def collect_dropbox(guild, channel, config: Config, create_threads: bool = False) -> list[Thread]:
    """Read one of your own channels where briefs get forwarded.

    A thread created from a message carries that message's ID, which is what
    links a delivery posted in the thread back to the brief above it.
    """

    dc = _require_discord()
    raw = []
    replies_to: dict[str, str] = {}
    try:
        async for message in channel.history(
            limit=config.max_messages_per_thread, oldest_first=True
        ):
            raw.append(message)
            reference = getattr(message, "reference", None)
            if reference and getattr(reference, "message_id", None):
                replies_to[str(message.id)] = str(reference.message_id)
    except dc.Forbidden:
        print(f"  ! no access to #{channel.name}", file=sys.stderr)
        return []

    threads_by_id = {str(t.id): t for t in getattr(channel, "threads", [])}
    if config.include_archived:
        try:
            async for thread in channel.archived_threads(limit=None):
                threads_by_id[str(thread.id)] = thread
        except Exception:
            pass

    thread_messages: dict[str, list[Message]] = {}
    thread_names: dict[str, str] = {}
    for message in raw:
        key = str(message.id)
        if not looks_like_brief(message_text(message), config):
            continue
        existing = threads_by_id.get(key)
        if existing is None and create_threads:
            try:
                from ..dropbox import brief_title

                existing = await message.create_thread(
                    name=brief_title(message_text(message), config)
                )
                print(f"  opened a thread for {existing.name}", file=sys.stderr)
            except Exception as exc:  # a missing permission must not stop the sync
                print(f"  ! could not open a thread: {exc}", file=sys.stderr)
                existing = None
        if existing is None:
            continue
        thread_names[key] = existing.name
        try:
            thread_messages[key] = [
                _convert_message(m)
                async for m in existing.history(
                    limit=config.max_messages_per_thread, oldest_first=True
                )
            ]
        except Exception:
            thread_messages[key] = []

    return collect_from_messages(
        [_convert_message(m) for m in raw],
        config,
        replies_to=replies_to,
        thread_messages=thread_messages,
        thread_names=thread_names,
        channel_name=channel.name,
        guild_name=guild.name,
        guild_id=str(guild.id),
        channel_id=str(channel.id),
    )


async def _collect_threads(client, config: Config) -> list[Thread]:
    dc = _require_discord()
    collected: list[Thread] = []
    wanted_guilds = {str(g) for g in config.guild_ids}

    for guild in client.guilds:
        if wanted_guilds and str(guild.id) not in wanted_guilds:
            continue
        for channel in guild.channels:
            if not isinstance(channel, (dc.TextChannel, dc.ForumChannel)):
                continue

            if config.dropbox_matches(channel.name, str(channel.id)):
                found = await collect_dropbox(
                    guild, channel, config, create_threads=config.auto_thread
                )
                collected.extend(found)
                print(
                    f"  read {len(found)} brief(s) from #{channel.name}",
                    file=sys.stderr,
                )
                continue

            if not config.channel_matches(channel.name, str(channel.id)):
                continue

            threads = list(getattr(channel, "threads", []))
            if config.include_archived:
                try:
                    async for thread in channel.archived_threads(limit=None):
                        threads.append(thread)
                except dc.Forbidden:
                    print(
                        f"  ! no access to archived threads in #{channel.name}",
                        file=sys.stderr,
                    )
                except Exception as exc:  # pragma: no cover - network edge cases
                    print(f"  ! {channel.name}: {exc}", file=sys.stderr)

            seen: set[int] = set()
            for thread in threads:
                if thread.id in seen:
                    continue
                seen.add(thread.id)
                try:
                    messages = [
                        _convert_message(m)
                        async for m in thread.history(
                            limit=config.max_messages_per_thread, oldest_first=True
                        )
                    ]
                except dc.Forbidden:
                    print(f"  ! no access to thread: {thread.name}", file=sys.stderr)
                    continue
                collected.append(
                    Thread(
                        id=str(thread.id),
                        name=thread.name,
                        guild_id=str(guild.id),
                        guild_name=guild.name,
                        parent_id=str(channel.id),
                        parent_name=channel.name,
                        created_at=thread.created_at,
                        archived=bool(getattr(thread, "archived", False)),
                        locked=bool(getattr(thread, "locked", False)),
                        tags=[t.name for t in getattr(thread, "applied_tags", [])],
                        jump_url=thread.jump_url,
                        messages=messages,
                    )
                )
                print(f"  fetched {thread.name} ({len(messages)} messages)", file=sys.stderr)
    return collected


def fetch_threads(config: Config, token: Optional[str] = None) -> list[Thread]:
    """Log in, walk the configured channels, and return their threads."""

    dc = _require_discord()
    token = token or os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise RuntimeError(
            "No bot token. Set DISCORD_BOT_TOKEN or pass --token."
        )

    intents = dc.Intents.default()
    intents.message_content = True
    intents.guilds = True
    client = dc.Client(intents=intents)
    result: dict[str, object] = {}

    @client.event
    async def on_ready():  # pragma: no cover - requires a live connection
        try:
            result["threads"] = await _collect_threads(client, config)
        except Exception as exc:
            result["error"] = exc
        finally:
            await client.close()

    asyncio.run(client.start(token))

    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result.get("threads", [])  # type: ignore[return-value]
