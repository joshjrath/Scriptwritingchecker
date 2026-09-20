"""Push a digest to a Discord webhook (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

MAX_LEN = 1900


def chunk(text: str, limit: int = MAX_LEN) -> list[str]:
    """Split on line boundaries so each chunk fits a Discord message."""

    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines():
        line = line[:limit]
        if size + len(line) + 1 > limit and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return [c for c in chunks if c.strip()]


def send_webhook(url: str, content: str, username: str = "Script Check") -> int:
    """Post ``content`` to a Discord webhook. Returns the number of messages."""

    if not url:
        raise ValueError("No webhook URL configured.")
    sent = 0
    for part in chunk(content):
        payload = json.dumps(
            {"content": part, "username": username, "allowed_mentions": {"parse": []}}
        ).encode()
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status >= 300:  # pragma: no cover - urllib raises instead
                raise RuntimeError(f"Webhook returned {response.status}")
        sent += 1
    return sent
