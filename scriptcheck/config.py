"""Configuration loading."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import time
from pathlib import Path
from typing import Any, Optional

from .parsing import DEFAULT_LINK_PATTERNS, DEFAULT_ROLES

DEFAULT_CONFIG_PATHS = [
    Path("scriptcheck.config.json"),
    Path("config.json"),
    Path.home() / ".config" / "scriptcheck" / "config.json",
]


@dataclass
class Config:
    # --- who am I -----------------------------------------------------------
    #: Discord user IDs that count as me (the reliable match).
    my_user_ids: list[str] = field(default_factory=list)
    #: Usernames / nicknames that count as me (fallback for pasted exports).
    my_names: list[str] = field(default_factory=lambda: ["Josh"])
    #: Role sections I am responsible for.
    my_roles: list[str] = field(default_factory=lambda: ["SCRIPT"])
    #: Roles recognised when splitting an opening post into sections.
    known_roles: list[str] = field(default_factory=lambda: list(DEFAULT_ROLES))

    # --- where to look ------------------------------------------------------
    guild_ids: list[str] = field(default_factory=list)
    channel_ids: list[str] = field(default_factory=list)
    #: Regexes matched against channel names when channel_ids is empty.
    channel_name_patterns: list[str] = field(default_factory=list)
    include_archived: bool = True
    max_messages_per_thread: int = 300

    # --- time ---------------------------------------------------------------
    default_timezone: str = "America/New_York"
    preferred_timezones: list[str] = field(default_factory=lambda: ["America/New_York"])
    display_timezone: str = "America/New_York"
    #: Time of day assumed when a deadline gives a date but no clock time.
    assume_time: str = "23:59"
    date_order: str = "MDY"
    due_soon_hours: float = 48.0

    # --- what counts as a submission ---------------------------------------
    submission_link_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_LINK_PATTERNS)
    )
    #: Accept a submission posted by anyone, not just me (off by default).
    accept_any_author: bool = False

    # --- forum tags ---------------------------------------------------------
    done_tags: list[str] = field(
        default_factory=lambda: ["Delivered", "Submitted", "Complete", "Completed", "Done"]
    )
    ignore_tags: list[str] = field(
        default_factory=lambda: ["Cancelled", "Canceled", "Dropped", "On Hold"]
    )

    # --- output -------------------------------------------------------------
    webhook_url: str = ""
    data_file: str = "data/threads.json"
    #: Hand corrections that beat the parser, keyed by thread ID.
    overrides_file: str = "overrides.json"

    @property
    def assume_time_obj(self) -> time:
        match = re.match(r"^(\d{1,2}):(\d{2})$", self.assume_time.strip())
        if not match:
            return time(23, 59)
        return time(int(match.group(1)) % 24, int(match.group(2)) % 60)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        known = {f for f in cls.__dataclass_fields__}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"Unknown config keys: {', '.join(unknown)}")
        return cls(**data)

    @classmethod
    def load(cls, path: Optional[str | Path] = None) -> "Config":
        candidates = [Path(path)] if path else DEFAULT_CONFIG_PATHS
        for candidate in candidates:
            if candidate.is_file():
                config = cls.from_dict(json.loads(candidate.read_text()))
                config._apply_env()
                return config
        if path:
            raise FileNotFoundError(f"Config file not found: {path}")
        config = cls()
        config._apply_env()
        return config

    def _apply_env(self) -> None:
        webhook = os.environ.get("SCRIPTCHECK_WEBHOOK_URL")
        if webhook:
            self.webhook_url = webhook
        user_id = os.environ.get("SCRIPTCHECK_MY_USER_ID")
        if user_id and user_id not in self.my_user_ids:
            self.my_user_ids.append(user_id)

    def to_dict(self) -> dict:
        return asdict(self)

    def channel_matches(self, name: str, channel_id: str) -> bool:
        if self.channel_ids:
            return str(channel_id) in {str(c) for c in self.channel_ids}
        if self.channel_name_patterns:
            return any(
                re.search(p, name or "", re.IGNORECASE) for p in self.channel_name_patterns
            )
        return True
