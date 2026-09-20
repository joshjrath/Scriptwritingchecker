"""Rendering: terminal text, Markdown digest, JSON and CSV."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from .config import Config
from .models import STATUS_EMOJI, STATUS_LABEL, Assignment, Status


def _local(dt: Optional[datetime], tz: str) -> str:
    if not dt:
        return "-"
    try:
        zone = ZoneInfo(tz)
    except Exception:  # pragma: no cover - bad config falls back to UTC
        zone = timezone.utc
    return dt.astimezone(zone).strftime("%a %b %d, %Y %I:%M %p %Z").replace(" 0", " ")


def human_delta(dt: Optional[datetime], now: datetime) -> str:
    if not dt:
        return ""
    seconds = (dt - now).total_seconds()
    late = seconds < 0
    seconds = abs(seconds)
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        amount = f"{days}d {hours}h"
    elif hours:
        amount = f"{hours}h {minutes}m"
    else:
        amount = f"{minutes}m"
    return f"{amount} overdue" if late else f"in {amount}"


def delivery_margin(assignment) -> str:
    """How far before/after the deadline a delivery landed."""

    first = assignment.first_submission
    if not first or not first.posted_at or not assignment.deadline:
        return ""
    seconds = (assignment.deadline - first.posted_at).total_seconds()
    early = seconds >= 0
    days, remainder = divmod(int(abs(seconds)), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        amount = f"{days}d {hours}h"
    elif hours:
        amount = f"{hours}h {minutes}m"
    else:
        amount = f"{minutes}m"
    return f"{amount} early" if early else f"{amount} LATE"


def summarize(assignments: Iterable[Assignment]) -> Counter:
    return Counter(a.status for a in assignments)


def render_text(
    assignments: list[Assignment], config: Config, now: Optional[datetime] = None
) -> str:
    now = now or datetime.now(timezone.utc)
    tz = config.display_timezone
    counts = summarize(assignments)
    out: list[str] = []
    out.append("=" * 72)
    out.append(f"SCRIPT SUBMISSION CHECK  -  {_local(now, tz)}")
    out.append("=" * 72)

    tally = "  ".join(
        f"{STATUS_LABEL[s]}: {counts[s]}"
        for s in (
            Status.OVERDUE,
            Status.DUE_TODAY,
            Status.DUE_SOON,
            Status.PENDING,
            Status.NO_DEADLINE,
            Status.SUBMITTED_LATE,
            Status.SUBMITTED,
        )
        if counts[s]
    )
    out.append(tally or "Nothing to report.")
    out.append("")

    current: Optional[Status] = None
    for item in assignments:
        if item.status is not current:
            current = item.status
            out.append("")
            out.append(f"--- {STATUS_LABEL[current]} ({counts[current]}) " + "-" * 24)
        out.append("")
        out.append(f"{STATUS_EMOJI[item.status]} {item.thread_name}")
        meta = []
        if item.channel:
            meta.append(f"#{item.channel}")
        if item.word_count:
            meta.append(f"{item.word_count:,} words")
        if item.role:
            meta.append(item.role)
        if meta:
            out.append("   " + " | ".join(meta))
        first = item.first_submission
        if item.deadline:
            suffix = "" if first else f"  ({human_delta(item.deadline, now)})"
            out.append(f"   Deadline: {_local(item.deadline, tz)}{suffix}")
        else:
            out.append("   Deadline: not found in the brief")
        if first:
            margin = delivery_margin(item)
            out.append(
                f"   Delivered: {_local(first.posted_at, tz)}"
                + (f"  ({margin})" if margin else "")
            )
            for link in first.links[:3]:
                out.append(f"     {link}")
            if len(item.submissions) > 1:
                out.append(f"   (+{len(item.submissions) - 1} later link post(s))")
        elif item.status.needs_action:
            out.append("   Delivered: NO DRIVE LINK FROM ME IN THIS THREAD")
        for warning in item.warnings:
            out.append(f"   ! {warning}")
        if item.jump_url:
            out.append(f"   {item.jump_url}")
    out.append("")
    return "\n".join(out)


def render_markdown(
    assignments: list[Assignment], config: Config, now: Optional[datetime] = None
) -> str:
    now = now or datetime.now(timezone.utc)
    tz = config.display_timezone
    counts = summarize(assignments)
    lines = [f"**Script submission check** - {_local(now, tz)}", ""]

    headline = [
        f"{STATUS_EMOJI[s]} {STATUS_LABEL[s]}: **{counts[s]}**"
        for s in (
            Status.OVERDUE,
            Status.DUE_TODAY,
            Status.DUE_SOON,
            Status.PENDING,
            Status.NO_DEADLINE,
            Status.SUBMITTED_LATE,
            Status.SUBMITTED,
        )
        if counts[s]
    ]
    lines.append(" | ".join(headline) if headline else "_Nothing to report._")

    current: Optional[Status] = None
    for item in assignments:
        if item.status is not current:
            current = item.status
            lines.append("")
            lines.append(f"__{STATUS_LABEL[current]}__")
        bits = []
        first = item.first_submission
        if item.deadline:
            when = f"due {_local(item.deadline, tz)}"
            if not first:
                when += f" ({human_delta(item.deadline, now)})"
            bits.append(when)
        else:
            bits.append("no deadline found")
        if item.word_count:
            bits.append(f"{item.word_count:,} words")
        if first:
            margin = delivery_margin(item)
            bits.append(
                f"delivered {_local(first.posted_at, tz)}" + (f" - {margin}" if margin else "")
            )
        name = f"[{item.thread_name}]({item.jump_url})" if item.jump_url else item.thread_name
        lines.append(f"{STATUS_EMOJI[item.status]} {name} - " + "; ".join(bits))
        for warning in item.warnings:
            lines.append(f"   - _{warning}_")
    lines.append("")
    return "\n".join(lines)


def render_json(
    assignments: list[Assignment], config: Config, now: Optional[datetime] = None
) -> str:
    now = now or datetime.now(timezone.utc)
    counts = summarize(assignments)
    payload = {
        "generated_at": now.isoformat(),
        "summary": {STATUS_LABEL[s]: counts[s] for s in Status if counts[s]},
        "assignments": [a.to_dict() for a in assignments],
    }
    return json.dumps(payload, indent=2)


def render_csv(
    assignments: list[Assignment], config: Config, now: Optional[datetime] = None
) -> str:
    now = now or datetime.now(timezone.utc)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "status", "thread", "slot", "channel", "role", "deadline_utc",
            "deadline_local", "word_count", "delivered_utc", "links",
            "warnings", "url",
        ]
    )
    for a in assignments:
        first = a.first_submission
        writer.writerow(
            [
                a.status.value,
                a.thread_name,
                a.slot,
                a.channel,
                a.role,
                a.deadline.isoformat() if a.deadline else "",
                _local(a.deadline, config.display_timezone) if a.deadline else "",
                a.word_count or "",
                first.posted_at.isoformat() if first and first.posted_at else "",
                " ".join(first.links) if first else "",
                " | ".join(a.warnings),
                a.jump_url,
            ]
        )
    return buffer.getvalue()


RENDERERS = {
    "text": render_text,
    "md": render_markdown,
    "markdown": render_markdown,
    "json": render_json,
    "csv": render_csv,
}


def render(
    assignments: list[Assignment],
    config: Config,
    fmt: str = "text",
    now: Optional[datetime] = None,
) -> str:
    try:
        renderer = RENDERERS[fmt.lower()]
    except KeyError:
        raise SystemExit(f"Unknown format: {fmt} (choose from {', '.join(sorted(RENDERERS))})")
    return renderer(assignments, config, now)
