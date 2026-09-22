"""Render the report as a self-contained web page.

The page carries its own data, so the output file can be dropped on any static
host - GitHub Pages, S3, a folder on your laptop - with nothing to run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import resources
from typing import Iterable, Optional

from .config import Config
from .models import STATUS_LABEL, Assignment, Status

#: Reproduces the reset the Artifact host injects, so the standalone file and
#: an embedded fragment render identically.
STANDALONE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<!-- The check alone: the full mark's ruled lines smudge at tab size. -->
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3ClinearGradient id='g' x1='0' y1='0' x2='0' y2='64' gradientUnits='userSpaceOnUse'%3E%3Cstop offset='0' stop-color='%237C5CFF'/%3E%3Cstop offset='1' stop-color='%234B2FE0'/%3E%3C/linearGradient%3E%3Crect width='64' height='64' rx='15' fill='url(%23g)'/%3E%3Cpath d='M15 33.5 26 44.5 49 18' fill='none' stroke='%23fff' stroke-width='8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; font: 14px system-ui, sans-serif; }
  img { max-width: 100%; }
  [hidden] { display: none !important; }
</style>
</head>
<body>
"""

STANDALONE_TAIL = "\n</body>\n</html>\n"


def _template() -> str:
    return resources.files("scriptcheck.templates").joinpath("dashboard.html").read_text(
        encoding="utf-8"
    )


def build_payload(
    assignments: Iterable[Assignment],
    config: Config,
    now: Optional[datetime] = None,
    fetched_at: Optional[str] = None,
    banner: str = "",
    redact_links: bool = False,
    live: bool = False,
    can_edit: bool = True,
) -> dict:
    now = now or datetime.now(timezone.utc)
    rows = []
    for item in assignments:
        row = item.to_dict()
        row["status_label"] = STATUS_LABEL[item.status]
        if not can_edit:
            # See without_briefs(): a read-only viewer never receives the
            # brief text, only what the parser made of it.
            row.pop("brief_text", None)
        if redact_links:
            # Keep the fact of delivery, drop the URL itself.
            for submission in row["submissions"]:
                submission["links"] = ["(link hidden)" for _ in submission["links"]]
            row["jump_url"] = ""
        rows.append(row)
    return {
        "generated_at": now.isoformat(),
        "fetched_at": fetched_at or "",
        "timezone": config.display_timezone,
        "due_soon_hours": config.due_soon_hours,
        "banner": banner,
        "roles": list(config.my_roles),
        "logo_url": config.logo_url,
        "board_title": config.board_title,
        "live": live,
        "can_edit": can_edit,
        "assignments": rows,
    }


def without_briefs(payload: dict) -> dict:
    """A copy of the payload with the forwarded brief text removed.

    /audit and /explain are owner-only because a brief quoted in full is more
    than a status board should hand out, and the same applies to a read-only
    share link. The text is absent from the JSON rather than hidden in the UI,
    so it is not sitting in the page source waiting to be read.
    """

    out = dict(payload)
    out["assignments"] = [
        {key: value for key, value in row.items() if key != "brief_text"}
        for row in payload.get("assignments", [])
    ]
    return out


def render_dashboard(
    assignments: Iterable[Assignment],
    config: Config,
    now: Optional[datetime] = None,
    fetched_at: Optional[str] = None,
    banner: str = "",
    redact_links: bool = False,
    fragment: bool = False,
    live: bool = False,
    can_edit: bool = True,
) -> str:
    payload = build_payload(
        assignments, config, now, fetched_at, banner, redact_links, live, can_edit
    )
    data = json.dumps(payload, ensure_ascii=False)
    # </script> inside embedded JSON would close the tag early.
    data = data.replace("</", "<\\/")
    body = _template().replace("__REPORT_DATA__", data)
    if fragment:
        return body
    return STANDALONE_HEAD + body + STANDALONE_TAIL
