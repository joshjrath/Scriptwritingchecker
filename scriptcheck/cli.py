"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import __version__
from .config import Config
from .audit import render_audit, render_explain
from .dashboard import render_dashboard
from .engine import build_assignments
from .models import Status
from .report import render
from .overrides import load as load_overrides
from .sources.export_json import load_threads, save_threads


def _parse_now(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _load_config(args) -> Config:
    config = Config.load(args.config)
    if getattr(args, "timezone", None):
        config.display_timezone = args.timezone
    return config


def cmd_init(args) -> int:
    path = Path(args.config or "scriptcheck.config.json")
    if path.exists() and not args.force:
        print(f"{path} already exists (use --force to overwrite).")
        return 1
    sample = {
        "my_user_ids": ["YOUR_DISCORD_USER_ID"],
        "my_names": ["Josh"],
        "my_roles": ["SCRIPT"],
        "guild_ids": [],
        "channel_name_patterns": ["assignments", "workflow"],
        "default_timezone": "America/New_York",
        "preferred_timezones": ["America/New_York"],
        "display_timezone": "America/New_York",
        "due_soon_hours": 48,
        "submission_link_patterns": ["drive\\.google\\.com", "docs\\.google\\.com"],
        "data_file": "data/threads.json",
    }
    path.write_text(json.dumps(sample, indent=2) + "\n")
    print(f"Wrote {path}. Fill in your Discord user ID, then run `scriptcheck fetch`.")
    return 0


def cmd_fetch(args) -> int:
    from .sources.discord_bot import fetch_threads  # imported lazily

    config = _load_config(args)
    print("Connecting to Discord...", file=sys.stderr)
    threads = fetch_threads(config, token=args.token)
    out = Path(args.out or config.data_file)
    save_threads(threads, out)
    print(f"Saved {len(threads)} thread(s) to {out}")
    return 0


def _assignments(args, config: Config):
    threads = load_threads(args.input or config.data_file)
    now = _parse_now(args.now)
    items = build_assignments(threads, config, now=now, include_all=args.all)
    if getattr(args, "status", None):
        wanted = {s.strip().upper() for s in args.status.split(",")}
        items = [a for a in items if a.status.value in wanted]
    if getattr(args, "action_only", False):
        items = [a for a in items if a.status.needs_action]
    return items, now


def cmd_report(args) -> int:
    config = _load_config(args)
    items, now = _assignments(args, config)
    text = render(items, config, fmt=args.format, now=now)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
        print(f"Wrote {args.out}")
    else:
        print(text)
    if args.fail_on_missed and any(
        a.status in (Status.OVERDUE, Status.SUBMITTED_LATE) for a in items
    ):
        return 2
    return 0


def cmd_audit(args) -> int:
    config = _load_config(args)
    threads = load_threads(args.input or config.data_file)
    now = _parse_now(args.now)
    items = build_assignments(threads, config, now=now, include_all=args.all)
    print(render_audit(threads, items, config, now))
    if args.fail_on_review and any(a.needs_review for a in items):
        return 2
    return 0


def cmd_explain(args) -> int:
    config = _load_config(args)
    threads = load_threads(args.input or config.data_file)
    needle = args.thread.strip().lower()
    matches = [
        t for t in threads
        if t.id == args.thread.strip() or needle in t.name.lower()
    ]
    if not matches:
        names = "\n  ".join(t.name for t in threads[:15])
        raise ValueError(f"No thread matches {args.thread!r}. Threads found:\n  {names}")
    now = _parse_now(args.now)
    for thread in matches[:5]:
        print(render_explain(thread, config, now))
        print()
    if len(matches) > 5:
        print(f"({len(matches) - 5} more threads matched; narrow the search.)")
    return 0


def cmd_dashboard(args) -> int:
    config = _load_config(args)
    items, now = _assignments(args, config)
    fetched_at = ""
    source = Path(args.input or config.data_file)
    if source.is_file():
        try:
            fetched_at = json.loads(source.read_text()).get("fetched_at", "")
        except (json.JSONDecodeError, AttributeError):
            fetched_at = ""
    html = render_dashboard(
        items,
        config,
        now=now,
        fetched_at=fetched_at,
        banner=args.banner or "",
        redact_links=args.redact_links,
        fragment=args.fragment,
    )
    out = Path(args.out or "site/index.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out} ({len(items)} assignment(s), {len(html) // 1024} KB)")
    return 0


def cmd_notify(args) -> int:
    from .notify import send_webhook

    config = _load_config(args)
    items, now = _assignments(args, config)
    if args.only_if_action and not any(a.status.needs_action for a in items):
        print("Nothing needs action; no reminder sent.")
        return 0
    url = args.webhook or config.webhook_url
    body = render(items, config, fmt="md", now=now)
    sent = send_webhook(url, body)
    print(f"Sent {sent} message(s) to the webhook.")
    return 0


def cmd_check(args) -> int:
    code = cmd_fetch(args)
    if code:
        return code
    args.input = args.out or _load_config(args).data_file
    return cmd_report(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scriptcheck",
        description="Track script assignments and submissions across Discord threads.",
    )
    parser.add_argument("--version", action="version", version=f"scriptcheck {__version__}")
    parser.add_argument("-c", "--config", help="Path to a config JSON file.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Write a starter config file.")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    def add_report_args(p):
        p.add_argument("-i", "--input", help="Thread data file or directory.")
        p.add_argument(
            "-f", "--format", default="text", help="text, md, json or csv."
        )
        p.add_argument("--all", action="store_true", help="Include other people's roles.")
        p.add_argument("--action-only", action="store_true", help="Only what needs action.")
        p.add_argument("--status", help="Comma-separated statuses to keep, e.g. OVERDUE.")
        p.add_argument("--now", help="Evaluate as of this ISO timestamp (for testing).")
        p.add_argument("--timezone", help="Override the display timezone.")

    fetch = sub.add_parser("fetch", help="Pull threads from Discord with a bot token.")
    fetch.add_argument("--token", help="Bot token (else $DISCORD_BOT_TOKEN).")
    fetch.add_argument("-o", "--out", help="Where to save the thread data.")
    fetch.set_defaults(func=cmd_fetch)

    report = sub.add_parser("report", help="Print the submission status report.")
    add_report_args(report)
    report.add_argument("-o", "--out", help="Write the report to a file.")
    report.add_argument(
        "--fail-on-missed",
        action="store_true",
        help="Exit 2 if anything is overdue or was delivered late.",
    )
    report.set_defaults(func=cmd_report)

    check = sub.add_parser("check", help="Fetch from Discord, then report.")
    add_report_args(check)
    check.add_argument("--token")
    check.add_argument("-o", "--out", help="Where to save the thread data.")
    check.add_argument("--fail-on-missed", action="store_true")
    check.set_defaults(func=cmd_check)

    dashboard = sub.add_parser(
        "dashboard", help="Render a self-contained HTML dashboard."
    )
    add_report_args(dashboard)
    dashboard.add_argument("-o", "--out", help="Output file (default site/index.html).")
    dashboard.add_argument("--banner", help="Notice shown across the top of the page.")
    dashboard.add_argument(
        "--redact-links",
        action="store_true",
        help="Keep the fact of a delivery but hide Drive URLs and thread links "
        "(use when the page is hosted publicly).",
    )
    dashboard.add_argument(
        "--fragment",
        action="store_true",
        help="Emit the page without the <html>/<body> wrapper, for embedding.",
    )
    dashboard.set_defaults(func=cmd_dashboard)

    audit = sub.add_parser(
        "audit", help="Measure how much of the report was read vs assumed."
    )
    audit.add_argument("-i", "--input", help="Thread data file or directory.")
    audit.add_argument("--all", action="store_true", help="Include other people's roles.")
    audit.add_argument("--now", help="Evaluate as of this ISO timestamp.")
    audit.add_argument("--timezone", help="Override the display timezone.")
    audit.add_argument(
        "--fail-on-review",
        action="store_true",
        help="Exit 2 if anything needs a human look.",
    )
    audit.set_defaults(func=cmd_audit)

    explain = sub.add_parser(
        "explain", help="Show exactly what was parsed out of one thread."
    )
    explain.add_argument("thread", help="Thread ID, or part of its title.")
    explain.add_argument("-i", "--input", help="Thread data file or directory.")
    explain.add_argument("--now", help="Evaluate as of this ISO timestamp.")
    explain.add_argument("--timezone", help="Override the display timezone.")
    explain.set_defaults(func=cmd_explain)

    notify = sub.add_parser("notify", help="Post the digest to a Discord webhook.")
    add_report_args(notify)
    notify.add_argument("--webhook", help="Webhook URL (else config/$SCRIPTCHECK_WEBHOOK_URL).")
    notify.add_argument(
        "--only-if-action",
        action="store_true",
        help="Stay quiet unless something is due, overdue or unparsed.",
    )
    notify.set_defaults(func=cmd_notify)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
