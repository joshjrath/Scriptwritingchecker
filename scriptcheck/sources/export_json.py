"""Read and write thread data as JSON.

Two shapes are understood:

* the native shape this tool writes (``{"version": 1, "threads": [...]}``)
* DiscordChatExporter's per-channel JSON export, so the tracker works even
  without a bot in the server
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..models import Message, Thread

FORMAT_VERSION = 1


def save_threads(threads: Iterable[Thread], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": FORMAT_VERSION,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "threads": [t.to_dict() for t in threads],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def load_threads(path: str | Path) -> list[Thread]:
    """Load one JSON file, or every ``*.json`` in a directory."""

    path = Path(path)
    if path.is_dir():
        threads: list[Thread] = []
        for child in sorted(path.glob("*.json")):
            threads.extend(load_threads(child))
        return threads
    if not path.exists():
        raise FileNotFoundError(
            f"No thread data at {path}. Run `scriptcheck fetch` first, or point "
            "--input at an export file."
        )
    data = json.loads(path.read_text())
    return threads_from_payload(data)


def threads_from_payload(data: Any) -> list[Thread]:
    if isinstance(data, list):
        return [Thread.from_dict(item) for item in data]
    if isinstance(data, dict) and "threads" in data:
        return [Thread.from_dict(item) for item in data["threads"]]
    if isinstance(data, dict) and "messages" in data:
        return [_from_chat_exporter(data)]
    raise ValueError("Unrecognised thread data format")


def _from_chat_exporter(data: dict) -> Thread:
    """Normalise a DiscordChatExporter export into one Thread."""

    channel = data.get("channel") or {}
    guild = data.get("guild") or {}
    messages = [Message.from_dict(m) for m in data.get("messages") or []]
    messages.sort(key=lambda m: m.created_at or datetime.min.replace(tzinfo=timezone.utc))
    return Thread(
        id=str(channel.get("id") or ""),
        name=str(channel.get("name") or ""),
        guild_id=str(guild.get("id") or ""),
        guild_name=str(guild.get("name") or ""),
        parent_id=str(channel.get("categoryId") or ""),
        parent_name=str(channel.get("category") or ""),
        messages=messages,
    )
