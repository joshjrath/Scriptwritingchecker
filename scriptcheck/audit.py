"""Measure how well the parser actually read your threads.

The report tells you what the tool believes. This tells you how much of that
belief was read off the page versus assumed - which is the number that decides
whether the board can be trusted.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Iterable, Optional

from .config import Config
from .engine import build_assignment
from .models import Assignment, Confidence, Status, Thread
from .parsing import _normalise_role, discover_role_headers, split_role_sections


def coverage(threads: list[Thread], assignments: list[Assignment], config: Config) -> dict:
    """Counts of what could and could not be read."""

    total = len(assignments)
    by_confidence = Counter(a.confidence.value for a in assignments)
    return {
        "threads_fetched": len(threads),
        "assignments": total,
        "role_section_found": sum(1 for a in assignments if a.role),
        "assignee_resolved": sum(1 for a in assignments if a.evidence.get("assignee", "").startswith(("user ID", "display name"))),
        "assignee_by_user_id": sum(1 for a in assignments if a.evidence.get("assignee", "").startswith("user ID")),
        "deadline_found": sum(1 for a in assignments if a.deadline),
        "deadline_with_timezone": sum(1 for a in assignments if a.deadline_tz),
        "word_count_found": sum(1 for a in assignments if a.word_count),
        "needs_review": sum(1 for a in assignments if a.needs_review),
        "by_confidence": dict(by_confidence),
        "overridden": sum(1 for a in assignments if a.overridden),
    }


def unparsed_roles(threads: Iterable[Thread], config: Config) -> Counter:
    """Role headers seen in the posts that aren't in `known_roles`.

    A brief that says "WRITER" when the config says "SCRIPT" is invisible to
    the tracker; this is how that gets noticed instead of silently dropping.
    """

    seen: Counter = Counter()
    for thread in threads:
        opening = thread.opening_post
        if not opening:
            continue
        for header in discover_role_headers(opening.content):
            seen[_normalise_role(header)] += 1
    return seen


def pct(part: int, whole: int) -> str:
    if not whole:
        return "  n/a"
    return f"{100.0 * part / whole:5.1f}%"


def render_audit(
    threads: list[Thread],
    assignments: list[Assignment],
    config: Config,
    now: Optional[datetime] = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    stats = coverage(threads, assignments, config)
    total = stats["assignments"]
    out: list[str] = []

    out.append("=" * 72)
    out.append("PARSE AUDIT")
    out.append("=" * 72)
    out.append(f"Threads fetched:        {stats['threads_fetched']}")
    out.append(f"Assignments considered: {total}")
    out.append("")
    out.append("What could be read off the page:")
    for label, key in [
        ("role section found", "role_section_found"),
        ("assignee resolved", "assignee_resolved"),
        ("  ... by user ID", "assignee_by_user_id"),
        ("deadline found", "deadline_found"),
        ("  ... with a timezone", "deadline_with_timezone"),
        ("word count found", "word_count_found"),
    ]:
        out.append(f"  {label:<24} {stats[key]:>4} / {total:<4} {pct(stats[key], total)}")

    out.append("")
    out.append("Confidence:")
    for level in (Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW):
        n = stats["by_confidence"].get(level.value, 0)
        out.append(f"  {level.value:<24} {n:>4} / {total:<4} {pct(n, total)}")
    if stats["overridden"]:
        out.append(f"  corrected by hand        {stats['overridden']:>4}")

    roles = unparsed_roles(threads, config)
    known = {r.strip().upper() for r in config.known_roles}
    unknown = {r: n for r, n in roles.items() if r not in known}
    out.append("")
    out.append("Role headers seen in the briefs:")
    for role, n in roles.most_common():
        flag = "" if role in known else "   <- not in known_roles"
        out.append(f"  {role:<24} {n:>4}{flag}")
    if not roles:
        out.append("  (none found - check that briefs really use role headers)")

    review = [a for a in assignments if a.needs_review]
    out.append("")
    out.append(f"--- Needs a human look ({len(review)}) " + "-" * 30)
    if not review:
        out.append("Nothing. Every assignment parsed cleanly.")
    for item in review:
        out.append("")
        out.append(f"  {item.thread_name}")
        out.append(f"    confidence: {item.confidence.value}   status: {item.status.value}")
        for warning in item.warnings:
            out.append(f"    - {warning.lstrip('! ')}")
        if item.jump_url:
            out.append(f"    {item.jump_url}")

    out.append("")
    out.append("Run `scriptcheck explain <thread id or text>` to see exactly what was")
    out.append("matched in one thread, and correct it in overrides.json if it is wrong.")
    out.append("")
    return "\n".join(out)


def render_explain(thread: Thread, config: Config, now: Optional[datetime] = None) -> str:
    """Show every step the parser took on one thread."""

    now = now or datetime.now(timezone.utc)
    assignment = build_assignment(thread, config, now)
    opening = thread.opening_post
    sections = split_role_sections(opening.content if opening else "", config.known_roles)

    out: list[str] = []
    out.append("=" * 72)
    out.append(thread.name)
    out.append("=" * 72)
    out.append(f"thread id : {thread.id}")
    out.append(f"channel   : #{thread.parent_name}")
    out.append(f"tags      : {', '.join(thread.tags) or '(none)'}")
    out.append(f"messages  : {len(thread.messages)}")
    out.append("")

    out.append("TITLE")
    out.append(f"  slot        : {assignment.slot or '(not parsed)'}")
    out.append(f"  title       : {assignment.title}")
    out.append(
        f"  publish date: {assignment.slate_date.date() if assignment.slate_date else '(not parsed)'}"
        "   (never used as a deadline)"
    )
    out.append("")

    out.append(f"ROLE SECTIONS IN THE OPENING POST ({len(sections)})")
    for section in sections:
        mark = "->" if assignment.role and section.role == assignment.role else "  "
        who = ", ".join(section.mention_names + [f"<@{i}>" for i in section.mention_ids])
        out.append(f"  {mark} {section.role:<14} assignee: {who or '(nobody named)'}")
    if not sections:
        out.append("     (none - no role headers matched `known_roles`)")
    out.append("")

    out.append("VERDICT")
    out.append(f"  status     : {assignment.status.value}")
    out.append(f"  confidence : {assignment.confidence.value}")
    out.append(f"  assignee   : {assignment.evidence.get('assignee', '(unresolved)')}")
    if assignment.deadline:
        out.append(f"  deadline   : {assignment.deadline.isoformat()}")
        out.append(f"    read from: {assignment.evidence.get('deadline', '?')!r}")
        out.append(f"    found in : {assignment.evidence.get('deadline_source', '?')}")
        out.append(f"    timezone : {assignment.deadline_tz or '(assumed ' + config.default_timezone + ')'}")
    else:
        out.append("  deadline   : NOT FOUND")
    out.append(f"  word count : {assignment.word_count or '(not found)'}")
    out.append("")

    out.append(f"SUBMISSIONS ({len(assignment.submissions)})")
    for submission in assignment.submissions:
        out.append(f"  {submission.posted_at.isoformat() if submission.posted_at else '?'}")
        for link in submission.links:
            out.append(f"    {link}")
    if not assignment.submissions:
        out.append("  (no message from me in this thread carries a matching link)")
    out.append("")

    if assignment.warnings:
        out.append("FLAGS")
        for warning in assignment.warnings:
            out.append(f"  - {warning}")
        out.append("")

    if opening:
        out.append("OPENING POST AS FETCHED")
        out.append("-" * 72)
        for line in opening.content.splitlines():
            out.append(f"  {line}")
        out.append("-" * 72)
    return "\n".join(out)
