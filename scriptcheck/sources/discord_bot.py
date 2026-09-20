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


def _convert_message(message) -> Message:
    return Message(
        id=str(message.id),
        author=Author(
            id=str(message.author.id),
            name=getattr(message.author, "name", "") or "",
            display_name=getattr(message.author, "display_name", "") or "",
            bot=bool(getattr(message.author, "bot", False)),
        ),
        content=message.content or "",
        created_at=message.created_at,
        edited_at=message.edited_at,
        attachments=[
            Attachment(filename=a.filename, url=a.url) for a in message.attachments
        ],
        jump_url=message.jump_url,
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
