"""Deciding what is worth interrupting someone about.

A live connection makes it possible to ping *before* a deadline rather than
after, which is the only reason real-time is worth a running process. It also
makes it possible to spam, so every alert fires at most once per assignment per
deadline value, and a restart never replays history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from .models import Assignment, Status

NEW = "new_assignment"
DUE_IN = "due_in"
OVERDUE = "overdue"
DELIVERED = "delivered"
DEADLINE_CHANGED = "deadline_changed"
NEEDS_REVIEW = "needs_review"

ALL_KINDS = [NEW, DUE_IN, OVERDUE, DELIVERED, DEADLINE_CHANGED, NEEDS_REVIEW]


@dataclass(frozen=True)
class Alert:
    kind: str
    thread_id: str
    title: str
    text: str
    url: str = ""

    def line(self) -> str:
        name = f"[{self.title}]({self.url})" if self.url else f"**{self.title}**"
        return f"{self.text} - {name}"


def _snapshot(assignment: Assignment) -> tuple:
    return (
        assignment.status.value,
        assignment.deadline.isoformat() if assignment.deadline else "",
        len(assignment.submissions),
    )


def _span(seconds: float) -> str:
    seconds = abs(int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class AlertTracker:
    """Turns successive board states into a short list of things to say."""

    def __init__(
        self,
        lead_hours: Iterable[float] = (24, 2),
        kinds: Optional[Iterable[str]] = None,
    ):
        # Longest first, so the earliest warning is considered first.
        self.lead_hours = sorted({float(h) for h in lead_hours}, reverse=True)
        self.kinds = set(kinds) if kinds is not None else set(ALL_KINDS)
        self.previous: dict[str, tuple] = {}
        self.fired: set[tuple] = set()
        self.primed = False

    def _wants(self, kind: str) -> bool:
        return kind in self.kinds

    def prime(self, assignments: Iterable[Assignment], now: datetime) -> None:
        """Seed the baseline without alerting, so a restart is silent."""

        for assignment in assignments:
            self.previous[assignment.thread_id] = _snapshot(assignment)
            deadline_key = assignment.deadline.isoformat() if assignment.deadline else ""
            # Anything already inside a reminder window has had its chance.
            if assignment.deadline:
                remaining = (assignment.deadline - now).total_seconds()
                for lead in self.lead_hours:
                    if remaining <= lead * 3600:
                        self.fired.add((assignment.thread_id, deadline_key, f"lead{lead}"))
            if assignment.status is Status.OVERDUE:
                self.fired.add((assignment.thread_id, deadline_key, OVERDUE))
        self.primed = True

    def scan(self, assignments: Iterable[Assignment], now: datetime) -> list[Alert]:
        assignments = list(assignments)
        if not self.primed:
            self.prime(assignments, now)
            return []

        alerts: list[Alert] = []
        seen: set[str] = set()

        for assignment in assignments:
            seen.add(assignment.thread_id)
            key = assignment.thread_id
            deadline_key = assignment.deadline.isoformat() if assignment.deadline else ""
            before = self.previous.get(key)
            now_snap = _snapshot(assignment)
            title = assignment.title or assignment.thread_name

            def make(kind: str, text: str) -> Alert:
                return Alert(kind, key, title, text, assignment.jump_url)

            if before is None:
                if self._wants(NEW) and assignment.status not in (
                    Status.NOT_MINE,
                    Status.IGNORED,
                ):
                    due = (
                        f"due in {_span((assignment.deadline - now).total_seconds())}"
                        if assignment.deadline
                        else "no deadline in the brief"
                    )
                    alerts.append(make(NEW, f"\U0001f4dd New script assigned, {due}"))
                    # The announcement already states the timing, so do not
                    # follow it a second later with "due in ...".
                    if assignment.deadline:
                        remaining = (assignment.deadline - now).total_seconds()
                        for lead in self.lead_hours:
                            if remaining <= lead * 3600:
                                self.fired.add((key, deadline_key, f"lead{lead}"))
            else:
                was_status, was_deadline, was_subs = before

                if (
                    self._wants(DELIVERED)
                    and now_snap[2] > was_subs
                    and assignment.status.is_submitted
                ):
                    when = (
                        "on time"
                        if assignment.status is Status.SUBMITTED
                        else "late"
                    )
                    alerts.append(make(DELIVERED, f"✅ Delivered {when}"))

                if (
                    self._wants(DEADLINE_CHANGED)
                    and deadline_key
                    and was_deadline
                    and deadline_key != was_deadline
                ):
                    alerts.append(
                        make(
                            DEADLINE_CHANGED,
                            f"\U0001f504 Deadline moved to {assignment.deadline:%b %d, %H:%M UTC}",
                        )
                    )

                if (
                    self._wants(NEEDS_REVIEW)
                    and assignment.needs_review
                    and was_status != now_snap[0]
                    and assignment.status is Status.NO_DEADLINE
                ):
                    alerts.append(
                        make(NEEDS_REVIEW, "❓ No readable deadline - check the brief")
                    )

            # Time-based reminders, independent of whether anything changed.
            if assignment.deadline and not assignment.status.is_submitted:
                remaining = (assignment.deadline - now).total_seconds()

                if remaining < 0:
                    stamp = (key, deadline_key, OVERDUE)
                    if self._wants(OVERDUE) and stamp not in self.fired:
                        self.fired.add(stamp)
                        alerts.append(make(OVERDUE, "\U0001f534 Deadline passed, nothing delivered"))
                else:
                    for lead in self.lead_hours:
                        stamp = (key, deadline_key, f"lead{lead}")
                        if remaining > lead * 3600 or stamp in self.fired:
                            continue
                        # Fire the tightest window that applies; mark the wider
                        # ones spent so a cold start does not send a burst.
                        for wider in self.lead_hours:
                            if wider >= lead:
                                self.fired.add((key, deadline_key, f"lead{wider}"))
                        if self._wants(DUE_IN):
                            alerts.append(
                                make(DUE_IN, f"⏳ Due in {_span(remaining)}")
                            )
                        break

            self.previous[key] = now_snap

        for gone in set(self.previous) - seen:
            self.previous.pop(gone, None)

        return alerts


def format_digest(alerts: list[Alert]) -> str:
    """One webhook message for a batch of alerts."""

    if not alerts:
        return ""
    if len(alerts) == 1:
        return alerts[0].line()
    return "**Script board update**\n" + "\n".join(f"- {a.line()}" for a in alerts)
