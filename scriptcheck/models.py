"""Data models: raw Discord ingest shapes plus the parsed assignment view."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Optional


def _parse_dt(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


@dataclass
class Author:
    id: str = ""
    name: str = ""
    display_name: str = ""
    bot: bool = False

    @property
    def names(self) -> list[str]:
        return [n for n in (self.name, self.display_name) if n]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "bot": self.bot,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Author":
        data = data or {}
        name = str(data.get("name") or data.get("username") or "")
        return cls(
            id=str(data.get("id") or ""),
            name=name,
            # DiscordChatExporter calls the server nickname "nickname".
            display_name=str(
                data.get("display_name")
                or data.get("nickname")
                or data.get("global_name")
                or name
            ),
            bot=bool(data.get("bot") or data.get("isBot")),
        )


@dataclass
class Attachment:
    filename: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        return {"filename": self.filename, "url": self.url}

    @classmethod
    def from_dict(cls, data: dict) -> "Attachment":
        data = data or {}
        return cls(
            filename=str(data.get("filename") or data.get("fileName") or ""),
            url=str(data.get("url") or ""),
        )


@dataclass
class Message:
    id: str = ""
    author: Author = field(default_factory=Author)
    content: str = ""
    created_at: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    attachments: list[Attachment] = field(default_factory=list)
    jump_url: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "author": self.author.to_dict(),
            "content": self.content,
            "created_at": _iso(self.created_at),
            "edited_at": _iso(self.edited_at),
            "attachments": [a.to_dict() for a in self.attachments],
            "jump_url": self.jump_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(
            id=str(data.get("id") or ""),
            author=Author.from_dict(data.get("author") or {}),
            content=str(data.get("content") or ""),
            created_at=_parse_dt(data.get("created_at") or data.get("timestamp")),
            edited_at=_parse_dt(data.get("edited_at") or data.get("timestampEdited")),
            attachments=[Attachment.from_dict(a) for a in data.get("attachments") or []],
            jump_url=str(data.get("jump_url") or ""),
        )


@dataclass
class Thread:
    """One video assignment thread."""

    id: str = ""
    name: str = ""
    guild_id: str = ""
    guild_name: str = ""
    parent_id: str = ""
    parent_name: str = ""
    created_at: Optional[datetime] = None
    archived: bool = False
    locked: bool = False
    tags: list[str] = field(default_factory=list)
    jump_url: str = ""
    messages: list[Message] = field(default_factory=list)

    @property
    def opening_post(self) -> Optional[Message]:
        return self.messages[0] if self.messages else None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "guild_id": self.guild_id,
            "guild_name": self.guild_name,
            "parent_id": self.parent_id,
            "parent_name": self.parent_name,
            "created_at": _iso(self.created_at),
            "archived": self.archived,
            "locked": self.locked,
            "tags": list(self.tags),
            "jump_url": self.jump_url,
            "messages": [m.to_dict() for m in self.messages],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Thread":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            guild_id=str(data.get("guild_id") or ""),
            guild_name=str(data.get("guild_name") or ""),
            parent_id=str(data.get("parent_id") or ""),
            parent_name=str(data.get("parent_name") or ""),
            created_at=_parse_dt(data.get("created_at")),
            archived=bool(data.get("archived")),
            locked=bool(data.get("locked")),
            tags=[str(t) for t in data.get("tags") or []],
            jump_url=str(data.get("jump_url") or ""),
            messages=[Message.from_dict(m) for m in data.get("messages") or []],
        )


class Status(str, Enum):
    """Where an assignment stands, worst-to-best roughly in listing order."""

    OVERDUE = "OVERDUE"
    DUE_TODAY = "DUE_TODAY"
    DUE_SOON = "DUE_SOON"
    PENDING = "PENDING"
    NO_DEADLINE = "NO_DEADLINE"
    SUBMITTED_LATE = "SUBMITTED_LATE"
    SUBMITTED = "SUBMITTED"
    NOT_MINE = "NOT_MINE"
    IGNORED = "IGNORED"

    @property
    def is_submitted(self) -> bool:
        return self in (Status.SUBMITTED, Status.SUBMITTED_LATE)

    @property
    def needs_action(self) -> bool:
        return self in (
            Status.OVERDUE,
            Status.DUE_TODAY,
            Status.DUE_SOON,
            Status.NO_DEADLINE,
        )


#: Sort weight for reports: smaller sorts first.
STATUS_ORDER = {
    Status.OVERDUE: 0,
    Status.DUE_TODAY: 1,
    Status.DUE_SOON: 2,
    Status.NO_DEADLINE: 3,
    Status.PENDING: 4,
    Status.SUBMITTED_LATE: 5,
    Status.SUBMITTED: 6,
    Status.NOT_MINE: 7,
    Status.IGNORED: 8,
}

STATUS_LABEL = {
    Status.OVERDUE: "OVERDUE",
    Status.DUE_TODAY: "DUE TODAY",
    Status.DUE_SOON: "DUE SOON",
    Status.PENDING: "PENDING",
    Status.NO_DEADLINE: "NO DEADLINE FOUND",
    Status.SUBMITTED_LATE: "DELIVERED (LATE)",
    Status.SUBMITTED: "DELIVERED",
    Status.NOT_MINE: "NOT ASSIGNED TO ME",
    Status.IGNORED: "IGNORED",
}

STATUS_EMOJI = {
    Status.OVERDUE: "\U0001f534",
    Status.DUE_TODAY: "\U0001f7e0",
    Status.DUE_SOON: "\U0001f7e1",
    Status.PENDING: "⚪",
    Status.NO_DEADLINE: "❓",
    Status.SUBMITTED_LATE: "\U0001f7e2",
    Status.SUBMITTED: "✅",
    Status.NOT_MINE: "⚫",
    Status.IGNORED: "⚫",
}


@dataclass
class Submission:
    """A delivery: a message of mine carrying a submission link."""

    message_id: str = ""
    posted_at: Optional[datetime] = None
    links: list[str] = field(default_factory=list)
    jump_url: str = ""

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "posted_at": _iso(self.posted_at),
            "links": list(self.links),
            "jump_url": self.jump_url,
        }


class Confidence(str, Enum):
    """How much of the verdict was read, rather than assumed."""

    HIGH = "HIGH"      # assignee matched by user ID, deadline read from my section
    MEDIUM = "MEDIUM"  # matched by display name, or deadline read outside my section
    LOW = "LOW"        # something material had to be guessed

    @property
    def rank(self) -> int:
        return {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[self.value]


@dataclass
class Assignment:
    """A parsed thread plus the verdict on it."""

    thread_id: str = ""
    thread_name: str = ""
    channel: str = ""
    guild: str = ""
    jump_url: str = ""
    slate_date: Optional[datetime] = None
    slot: str = ""
    title: str = ""
    role: str = ""
    assignee_text: str = ""
    deadline: Optional[datetime] = None
    deadline_raw: str = ""
    deadline_tz: str = ""
    word_count: Optional[int] = None
    tags: list[str] = field(default_factory=list)
    archived: bool = False
    status: Status = Status.PENDING
    submissions: list[Submission] = field(default_factory=list)
    replies_after_delivery: int = 0
    warnings: list[str] = field(default_factory=list)
    confidence: Confidence = Confidence.HIGH
    #: Field name -> the text the value was read from, for `scriptcheck explain`.
    evidence: dict = field(default_factory=dict)
    #: Fields supplied by the overrides file rather than by parsing.
    overridden: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        """True when a human should look before trusting this row."""

        return (
            self.confidence is Confidence.LOW
            or self.status is Status.NO_DEADLINE
            or any(w.startswith("!") for w in self.warnings)
        )

    @property
    def first_submission(self) -> Optional[Submission]:
        return self.submissions[0] if self.submissions else None

    @property
    def latest_submission(self) -> Optional[Submission]:
        return self.submissions[-1] if self.submissions else None

    def hours_remaining(self, now: datetime) -> Optional[float]:
        if not self.deadline:
            return None
        return (self.deadline - now).total_seconds() / 3600.0

    def to_dict(self) -> dict:
        return {
            "thread_id": self.thread_id,
            "thread_name": self.thread_name,
            "channel": self.channel,
            "guild": self.guild,
            "jump_url": self.jump_url,
            "slate_date": _iso(self.slate_date),
            "slot": self.slot,
            "title": self.title,
            "role": self.role,
            "assignee_text": self.assignee_text,
            "deadline": _iso(self.deadline),
            "deadline_raw": self.deadline_raw,
            "deadline_tz": self.deadline_tz,
            "word_count": self.word_count,
            "tags": list(self.tags),
            "archived": self.archived,
            "status": self.status.value,
            "submissions": [s.to_dict() for s in self.submissions],
            "replies_after_delivery": self.replies_after_delivery,
            "warnings": list(self.warnings),
            "confidence": self.confidence.value,
            "evidence": dict(self.evidence),
            "overridden": list(self.overridden),
            "needs_review": self.needs_review,
        }


def sort_assignments(items: Iterable[Assignment]) -> list[Assignment]:
    """Most urgent first; within a status, earliest deadline first."""

    far_future = datetime.max.replace(tzinfo=timezone.utc)

    def key(a: Assignment):
        return (
            STATUS_ORDER.get(a.status, 99),
            a.deadline or far_future,
            a.thread_name,
        )

    return sorted(items, key=key)
