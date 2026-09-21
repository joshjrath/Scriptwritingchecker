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


def load_dotenv(path: str | Path = ".env", override: bool = False) -> list[str]:
    """Read a .env file into the environment. Returns the names it set.

    Small enough not to be worth a dependency, and it means `serve` works
    straight after filling in .env, with no `export` or `source` step to
    forget - which is exactly where a first run usually goes wrong.
    """

    path = Path(path)
    if not path.is_file():
        return []

    applied: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        # Strip one matching pair of surrounding quotes, and nothing else.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value
            applied.append(key)
    return applied


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
    #: Channels in YOUR OWN server where you forward briefs. Each brief posted
    #: there becomes an assignment - no access to anyone else's server needed.
    dropbox_channel_patterns: list[str] = field(default_factory=list)
    #: Open a thread on each brief so deliveries have somewhere to go.
    auto_thread: bool = True
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
    #: Your own logo, as a URL the browser can reach. Uploading the image to a
    #: Discord channel and copying its link is the easiest way to get one.
    logo_url: str = ""
    #: What the board calls itself, in the header and the browser tab.
    board_title: str = "Script Board"
    webhook_url: str = ""
    data_file: str = "data/threads.json"
    #: Hand corrections that beat the parser, keyed by thread ID.
    overrides_file: str = "overrides.json"

    # --- live mode ----------------------------------------------------------
    #: Shared secret for the live board. Empty means anyone with the URL can
    #: read it; set it here or as $SCRIPTCHECK_ACCESS_TOKEN.
    access_token: str = ""
    #: A second token that can look but not touch. Share this one with the
    #: team; keep access_token for yourself.
    view_token: str = ""
    serve_host: str = "0.0.0.0"
    serve_port: int = 8080
    #: Safety net for events missed during a gateway reconnect.
    resync_minutes: int = 15
    #: Ping this long before a deadline. Only the tightest window that applies
    #: fires, so a restart never sends a burst.
    reminder_lead_hours: list[float] = field(default_factory=lambda: [24, 2])
    #: Which alert kinds to send; see scriptcheck.alerts.ALL_KINDS.
    alert_kinds: list[str] = field(
        default_factory=lambda: [
            "new_assignment",
            "due_in",
            "overdue",
            "delivered",
            "deadline_changed",
            "needs_review",
        ]
    )

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
        # A browser-only deploy (Railway, Render, Fly) has no way to edit a
        # file in the image, so the whole config can arrive as one variable.
        inline = os.environ.get("SCRIPTCHECK_CONFIG", "").strip()
        if inline and not path:
            try:
                data = json.loads(inline)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"SCRIPTCHECK_CONFIG is not valid JSON: {exc}. It must be a "
                    'single-line object, e.g. {"my_user_ids": ["123"], '
                    '"channel_name_patterns": ["workflow"]}'
                ) from exc
            config = cls.from_dict(data)
            config._apply_env()
            return config

        env_path = os.environ.get("SCRIPTCHECK_CONFIG_FILE", "").strip()
        if env_path and not path:
            path = env_path

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
        token = os.environ.get("SCRIPTCHECK_ACCESS_TOKEN")
        if token:
            self.access_token = token
        view = os.environ.get("SCRIPTCHECK_VIEW_TOKEN")
        if view:
            self.view_token = view
        logo = os.environ.get("SCRIPTCHECK_LOGO_URL")
        if logo:
            self.logo_url = logo
        title = os.environ.get("SCRIPTCHECK_BOARD_TITLE")
        if title:
            self.board_title = title
        user_id = os.environ.get("SCRIPTCHECK_MY_USER_ID")
        if user_id and user_id not in self.my_user_ids:
            self.my_user_ids.append(user_id)

    def to_dict(self) -> dict:
        return asdict(self)

    def dropbox_matches(self, name: str, channel_id: str) -> bool:
        if not self.dropbox_channel_patterns:
            return False
        return any(
            re.search(p, name or "", re.IGNORECASE)
            for p in self.dropbox_channel_patterns
        )

    def channel_matches(self, name: str, channel_id: str) -> bool:
        if self.channel_ids:
            return str(channel_id) in {str(c) for c in self.channel_ids}
        if self.channel_name_patterns:
            return any(
                re.search(p, name or "", re.IGNORECASE) for p in self.channel_name_patterns
            )
        # Drop-box mode names exactly the channels it wants. Without this, an
        # empty filter would also walk every other channel in your own server.
        if self.dropbox_channel_patterns:
            return False
        return True
