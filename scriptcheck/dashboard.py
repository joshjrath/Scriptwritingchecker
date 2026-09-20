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
) -> dict:
    now = now or datetime.now(timezone.utc)
    rows = []
    for item in assignments:
        row = item.to_dict()
        row["status_label"] = STATUS_LABEL[item.status]
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
        "assignments": rows,
    }


def render_dashboard(
    assignments: Iterable[Assignment],
    config: Config,
    now: Optional[datetime] = None,
    fetched_at: Optional[str] = None,
    banner: str = "",
    redact_links: bool = False,
    fragment: bool = False,
) -> str:
    payload = build_payload(
        assignments, config, now, fetched_at, banner, redact_links
    )
    data = json.dumps(payload, ensure_ascii=False)
    # </script> inside embedded JSON would close the tag early.
    data = data.replace("</", "<\\/")
    body = _template().replace("__REPORT_DATA__", data)
    if fragment:
        return body
    return STANDALONE_HEAD + body + STANDALONE_TAIL
