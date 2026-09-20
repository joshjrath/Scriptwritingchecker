"""Manual corrections that beat whatever the parser decided.

The parser will get things wrong. The point of this file is that it can only
get them wrong *once*: whatever you correct here sticks, is visible in the
report, and never silently reverts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .models import Assignment, Status, Submission

#: Keys an override entry may carry.
FIELDS = {"deadline", "status", "delivered_at", "links", "word_count", "note", "ignore"}


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"Override has an unreadable timestamp: {value!r}")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load(path: str | Path) -> dict[str, dict]:
    """Read the overrides file, keyed by thread ID. Missing file is fine."""

    path = Path(path)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be an object keyed by thread ID.")
    cleaned: dict[str, dict] = {}
    for thread_id, entry in data.items():
        if not isinstance(entry, dict):
            raise ValueError(f"Override for {thread_id} must be an object.")
        unknown = sorted(set(entry) - FIELDS)
        if unknown:
            raise ValueError(
                f"Override for {thread_id} has unknown keys: {', '.join(unknown)}. "
                f"Allowed: {', '.join(sorted(FIELDS))}"
            )
        cleaned[str(thread_id)] = entry
    return cleaned


def save(path: str | Path, table: dict[str, dict]) -> Path:
    """Write the overrides file, creating its directory if needed."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write beside the target and swap, so a crash mid-write cannot leave a
    # half-file that fails to parse and loses every correction.
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(table, indent=2, sort_keys=True))
    temp.replace(path)
    return path


def record_delivery(
    path: str | Path,
    thread_id: str,
    posted_at: Optional[datetime] = None,
    links: Optional[list] = None,
    note: str = "",
) -> dict:
    """Mark one assignment delivered, by hand, and persist it."""

    table = load(path)
    entry = dict(table.get(str(thread_id)) or {})
    entry["delivered_at"] = (posted_at or datetime.now(timezone.utc)).isoformat()
    if links:
        entry["links"] = [str(l) for l in links]
    entry["note"] = note or "marked delivered from the board"
    table[str(thread_id)] = entry
    save(path, table)
    return table


def clear_delivery(path: str | Path, thread_id: str) -> dict:
    """Undo a hand-marked delivery, leaving any other corrections alone."""

    table = load(path)
    entry = dict(table.get(str(thread_id)) or {})
    for key in ("delivered_at", "links"):
        entry.pop(key, None)
    if entry.get("note", "").startswith("marked delivered"):
        entry.pop("note", None)
    if entry:
        table[str(thread_id)] = entry
    else:
        table.pop(str(thread_id), None)
    save(path, table)
    return table


def apply(assignment: Assignment, entry: dict) -> Assignment:
    """Apply one override entry in place; record what it touched."""

    if entry.get("ignore"):
        assignment.status = Status.IGNORED
        assignment.overridden.append("status")

    if "deadline" in entry:
        assignment.deadline = _parse_dt(entry["deadline"])
        assignment.deadline_raw = "manual override"
        assignment.deadline_tz = ""
        assignment.overridden.append("deadline")

    if "word_count" in entry:
        assignment.word_count = int(entry["word_count"])
        assignment.overridden.append("word_count")

    if "delivered_at" in entry:
        posted = _parse_dt(entry["delivered_at"])
        links = [str(l) for l in entry.get("links") or []]
        assignment.submissions = [
            Submission(message_id="override", posted_at=posted, links=links)
        ]
        assignment.overridden.append("delivered_at")
    elif "links" in entry and assignment.submissions:
        assignment.submissions[0].links = [str(l) for l in entry["links"]]
        assignment.overridden.append("links")

    if "status" in entry:
        try:
            assignment.status = Status(str(entry["status"]).upper())
        except ValueError:
            raise ValueError(
                f"Unknown status in override: {entry['status']!r}. "
                f"Use one of: {', '.join(s.value for s in Status)}"
            )
        assignment.overridden.append("status")

    if entry.get("note"):
        assignment.warnings.append(f"Manual note: {entry['note']}")

    if assignment.overridden:
        assignment.warnings.append(
            "Corrected by hand: " + ", ".join(sorted(set(assignment.overridden)))
        )
    return assignment
