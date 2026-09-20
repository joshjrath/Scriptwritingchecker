"""Generate tests/fixtures/sample_threads.json (a stand-in for a real fetch)."""

from __future__ import annotations

import json
from pathlib import Path

ME = {"id": "111111111111111111", "name": "joshjrath", "display_name": "Josh", "bot": False}
ASH = {"id": "222222222222222222", "name": "ash", "display_name": "Ash", "bot": False}
OTHER = {"id": "333333333333333333", "name": "maria", "display_name": "Maria", "bot": False}


def brief(title, deadline_us, deadline_in, words, writer="<@111111111111111111>", extra=""):
    lines = [
        title,
        "",
        "\U0001f4c1 Project",
        "TBD",
        "",
        "@ UTDR",
        "",
        "__________________",
        "",
        f"\U0001f4dd SCRIPT {writer}",
        "",
        "• Deadline:",
        "",
    ]
    if deadline_us:
        lines.append(f"  • \U0001f1fa\U0001f1f8 {deadline_us}")
    if deadline_in:
        lines.append(f"    ◦ \U0001f1ee\U0001f1f3 {deadline_in}")
    if not deadline_us and not deadline_in:
        lines.append("  • TBD")
    lines += [
        f"• Word Count: {words} Words",
        "",
        "Story Brief",
        "Rewrite the premise around one major change and keep the tone grounded.",
    ]
    if extra:
        lines += ["", extra]
    return "\n".join(lines)


def msg(mid, author, content, created, attachments=None, thread_id="0"):
    return {
        "id": mid,
        "author": author,
        "content": content,
        "created_at": created,
        "edited_at": None,
        "attachments": attachments or [],
        "jump_url": f"https://discord.com/channels/900/{thread_id}/{mid}",
    }


def thread(tid, name, messages, tags=None, archived=False):
    return {
        "id": tid,
        "name": name,
        "guild_id": "900",
        "guild_name": "Specular Industries",
        "parent_id": "901",
        "parent_name": "secondary-assignments-workflow",
        "created_at": "2026-09-10T12:00:00+00:00",
        "archived": archived,
        "locked": False,
        "tags": tags or [],
        "jump_url": f"https://discord.com/channels/900/{tid}",
        "messages": messages,
    }


DRIVE = "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit?usp=sharing"

threads = [
    # Due tonight, nothing delivered yet.
    thread(
        "1001",
        "09-25-26 | VIDEO-001 | What If Sans Remembered Every RESET?",
        [
            msg(
                "2001",
                ASH,
                brief(
                    "09-25-26 | VIDEO-001 | What If Sans Remembered Every RESET?",
                    "9/20/2026 @ 11:59 PM ET",
                    "9/21/2026 @ 9:29 AM IST",
                    5000,
                ),
                "2026-09-19T23:55:00+00:00",
                thread_id="1001",
            )
        ],
        tags=["Being Written", "Active"],
    ),
    # Comfortably ahead.
    thread(
        "1002",
        "10-03-26 | VIDEO-008 | What If Deadpool Joined The Avengers?",
        [
            msg(
                "2002",
                ASH,
                brief(
                    "10-03-26 | VIDEO-008 | What If Deadpool Joined The Avengers?",
                    "9/28/2026 @ 11:59 PM ET",
                    "9/29/2026 @ 9:29 AM IST",
                    4500,
                ),
                "2026-09-18T18:00:00+00:00",
                thread_id="1002",
            )
        ],
        tags=["Being Written", "Active"],
    ),
    # Missed: deadline passed, no link.
    thread(
        "1003",
        "09-23-26 | VIDEO-006 | What If Beyonder Fought The Living Tribunal?",
        [
            msg(
                "2003",
                ASH,
                brief(
                    "09-23-26 | VIDEO-006 | What If Beyonder Fought The Living Tribunal?",
                    "9/18/2026 @ 11:59 PM ET",
                    "9/19/2026 @ 9:29 AM IST",
                    5000,
                ),
                "2026-09-12T15:00:00+00:00",
                thread_id="1003",
            ),
            msg("2103", ASH, "any update on this one?", "2026-09-19T14:00:00+00:00", thread_id="1003"),
        ],
        tags=["Being Written", "Active"],
    ),
    # Delivered on time.
    thread(
        "1004",
        "09-22-26 | VIDEO-001 | How Does Goku Actually Train?",
        [
            msg(
                "2004",
                ASH,
                brief(
                    "09-22-26 | VIDEO-001 | How Does Goku Actually Train?",
                    "9/17/2026 @ 11:59 PM ET",
                    "9/18/2026 @ 9:29 AM IST",
                    5000,
                ),
                "2026-09-10T15:00:00+00:00",
                thread_id="1004",
            ),
            msg("2104", ME, f"Script is done, here you go: {DRIVE}", "2026-09-17T20:12:00+00:00", thread_id="1004"),
            msg("2204", ASH, "received, thank you!", "2026-09-17T21:00:00+00:00", thread_id="1004"),
        ],
        tags=["Delivered"],
        archived=True,
    ),
    # Delivered, but after the deadline.
    thread(
        "1005",
        "09-21-26 | VIDEO-002 | How Do Spider-Man's Webs Work?",
        [
            msg(
                "2005",
                ASH,
                brief(
                    "09-21-26 | VIDEO-002 | How Do Spider-Man's Webs Work?",
                    "9/15/2026 @ 11:59 PM ET",
                    "9/16/2026 @ 9:29 AM IST",
                    4000,
                ),
                "2026-09-08T15:00:00+00:00",
                thread_id="1005",
            ),
            msg("2105", ME, f"sorry for the delay - {DRIVE}", "2026-09-16T18:30:00+00:00", thread_id="1005"),
            msg("2205", ASH, "can you tighten the intro?", "2026-09-16T19:30:00+00:00", thread_id="1005"),
        ],
        tags=["Delivered"],
    ),
    # Someone else's script.
    thread(
        "1006",
        "09-30-26 | VIDEO-007 | What If YOU Were The Last Human?",
        [
            msg(
                "2006",
                ASH,
                brief(
                    "09-30-26 | VIDEO-007 | What If YOU Were The Last Human?",
                    "9/24/2026 @ 11:59 PM ET",
                    "9/25/2026 @ 9:29 AM IST",
                    5000,
                    writer="<@333333333333333333>",
                ),
                "2026-09-15T15:00:00+00:00",
                thread_id="1006",
            )
        ],
        tags=["Being Written"],
    ),
    # Brief never states a deadline.
    thread(
        "1007",
        "09-27-26 | VIDEO-009 | What If Gojo Never Lost?",
        [
            msg(
                "2007",
                ASH,
                brief(
                    "09-27-26 | VIDEO-009 | What If Gojo Never Lost?",
                    "",
                    "",
                    5000,
                ),
                "2026-09-16T15:00:00+00:00",
                thread_id="1007",
            )
        ],
        tags=["Being Written", "Active"],
    ),
    # Tagged delivered, but no link of mine is in the thread.
    thread(
        "1008",
        "09-25-26 | VIDEO-003 | How I'd Survive A Zombie Outbreak",
        [
            msg(
                "2008",
                ASH,
                brief(
                    "09-25-26 | VIDEO-003 | How I'd Survive A Zombie Outbreak",
                    "9/19/2026 @ 11:59 PM ET",
                    "9/20/2026 @ 9:29 AM IST",
                    3500,
                ),
                "2026-09-11T15:00:00+00:00",
                thread_id="1008",
            ),
            msg("2108", ME, "on it, first draft tonight", "2026-09-18T15:00:00+00:00", thread_id="1008"),
        ],
        tags=["Delivered"],
    ),
]

payload = {"version": 1, "fetched_at": "2026-09-20T19:30:00+00:00", "threads": threads}
out = Path(__file__).parent / "fixtures" / "sample_threads.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
print(f"wrote {out} with {len(threads)} threads")
