"""Drop-box mode: tracking assignments with no access to their server."""

import unittest
from datetime import datetime, timedelta, timezone

from scriptcheck.config import Config
from scriptcheck.dropbox import (
    brief_title,
    collect_from_messages,
    looks_like_brief,
    synthesize_thread,
)
from scriptcheck.engine import build_assignment, build_assignments
from scriptcheck.models import Author, Message, Status
from scriptcheck.sources.discord_bot import message_attachments, message_text

NOW = datetime(2026, 9, 20, 19, 30, tzinfo=timezone.utc)
CONFIG = Config(
    my_user_ids=["111111111111111111"],
    my_names=["Josh"],
    my_roles=["SCRIPT"],
    default_timezone="America/New_York",
    preferred_timezones=["America/New_York"],
    dropbox_channel_patterns=["my-assignments"],
    overrides_file="/nonexistent-overrides.json",
)

ME = Author(id="111111111111111111", name="joshjrath", display_name="Josh")

BRIEF = """09-25-26 | VIDEO-001 | What If Sans Remembered Every RESET?

\U0001f4dd SCRIPT <@111111111111111111>

• Deadline:
  • \U0001f1fa\U0001f1f8 9/20/2026 @ 11:59 PM ET
    ◦ \U0001f1ee\U0001f1f3 9/21/2026 @ 9:29 AM IST
• Word Count: 5000 Words

Story Brief
Sans remembers every reset.
"""

DRIVE = "https://docs.google.com/document/d/abc/edit"


def msg(mid, content, minutes=0, author=ME):
    return Message(
        id=mid,
        author=author,
        content=content,
        created_at=NOW - timedelta(days=2) + timedelta(minutes=minutes),
        jump_url=f"https://discord.com/channels/9/9/{mid}",
    )


# --- stand-ins for discord.py objects ---------------------------------------


class FakeSnapshot:
    def __init__(self, content="", attachments=None, embeds=None):
        self.content = content
        self.attachments = attachments or []
        self.embeds = embeds or []


class FakeAttachment:
    def __init__(self, filename, url):
        self.filename = filename
        self.url = url


class FakeEmbed:
    def __init__(self, title="", description="", fields=()):
        self.title = title
        self.description = description
        self.fields = list(fields)


class FakeMessage:
    def __init__(self, content="", snapshots=(), embeds=(), attachments=()):
        self.content = content
        self.message_snapshots = list(snapshots)
        self.embeds = list(embeds)
        self.attachments = list(attachments)


class TestForwardedMessages(unittest.TestCase):
    """A forwarded message carries empty content; the text is in a snapshot."""

    def test_a_plain_message_reads_normally(self):
        self.assertEqual(message_text(FakeMessage(content="hello")), "hello")

    def test_a_forwarded_brief_is_not_blank(self):
        forwarded = FakeMessage(content="", snapshots=[FakeSnapshot(content=BRIEF)])
        text = message_text(forwarded)
        self.assertIn("SCRIPT", text)
        self.assertIn("9/20/2026 @ 11:59 PM ET", text)

    def test_a_comment_added_to_a_forward_is_kept_too(self):
        forwarded = FakeMessage(
            content="this one's mine", snapshots=[FakeSnapshot(content=BRIEF)]
        )
        text = message_text(forwarded)
        self.assertIn("this one's mine", text)
        self.assertIn("VIDEO-001", text)

    def test_embedded_text_is_read(self):
        message = FakeMessage(
            embeds=[FakeEmbed(title="Deadline", description="9/20/2026 @ 11:59 PM ET")]
        )
        self.assertIn("11:59 PM ET", message_text(message))

    def test_attachments_come_along_with_a_forward(self):
        forwarded = FakeMessage(
            snapshots=[
                FakeSnapshot(attachments=[FakeAttachment("s.docx", "https://drive.google.com/x")])
            ],
            attachments=[FakeAttachment("own.png", "https://example.com/own.png")],
        )
        urls = [a.url for a in message_attachments(forwarded)]
        self.assertIn("https://drive.google.com/x", urls)
        self.assertIn("https://example.com/own.png", urls)

    def test_nothing_at_all_is_empty_not_an_error(self):
        self.assertEqual(message_text(FakeMessage()), "")


class TestBriefDetection(unittest.TestCase):
    def test_a_real_brief_is_recognised(self):
        self.assertTrue(looks_like_brief(BRIEF, CONFIG))

    def test_a_brief_without_a_role_header_but_with_a_deadline_counts(self):
        text = "VIDEO-004 | Something\nDeadline: 9/25/2026 @ 11:59 PM ET\n5000 words"
        self.assertTrue(looks_like_brief(text, CONFIG))

    def test_chatter_is_not_an_assignment(self):
        for text in [
            "thanks!",
            "",
            "   ",
            "can you look at this when you get a sec",
            "https://docs.google.com/document/d/abc/edit",
        ]:
            self.assertFalse(looks_like_brief(text, CONFIG), text)

    def test_someone_elses_role_section_is_still_a_brief(self):
        # It parses as an assignment; the engine decides it is not mine.
        text = BRIEF.replace("111111111111111111", "999999999999999999")
        self.assertTrue(looks_like_brief(text, CONFIG))


class TestTitles(unittest.TestCase):
    def test_the_title_line_becomes_the_thread_name(self):
        self.assertEqual(
            brief_title(BRIEF, CONFIG),
            "09-25-26 | VIDEO-001 | What If Sans Remembered Every RESET?",
        )

    def test_a_brief_without_a_title_line_uses_its_first_line(self):
        self.assertEqual(brief_title("Some Notes\n\nDeadline: tbd", CONFIG), "Some Notes")

    def test_decoration_is_stripped(self):
        self.assertEqual(brief_title("### **Heading**", CONFIG), "**Heading**")

    def test_thread_names_stay_within_discord_limits(self):
        self.assertLessEqual(len(brief_title("x" * 400, CONFIG)), 100)

    def test_an_empty_brief_falls_back(self):
        self.assertEqual(brief_title("", CONFIG, fallback="Assignment"), "Assignment")


class TestCollecting(unittest.TestCase):
    def test_a_brief_plus_a_threaded_delivery_becomes_one_assignment(self):
        brief = msg("100", BRIEF)
        delivery = msg("200", f"done - {DRIVE}", minutes=30)
        threads = collect_from_messages(
            [brief],
            CONFIG,
            thread_messages={"100": [delivery]},
            thread_names={"100": "09-25-26 | VIDEO-001 | What If Sans..."},
            channel_name="my-assignments",
        )
        self.assertEqual(len(threads), 1)
        assignment = build_assignment(threads[0], CONFIG, NOW)
        self.assertEqual(assignment.status, Status.SUBMITTED)
        self.assertEqual(assignment.word_count, 5000)
        self.assertEqual(
            assignment.deadline, datetime(2026, 9, 21, 3, 59, tzinfo=timezone.utc)
        )

    def test_a_delivery_posted_as_a_reply_counts_too(self):
        brief = msg("100", BRIEF)
        reply = msg("201", f"here you go {DRIVE}", minutes=40)
        threads = collect_from_messages(
            [brief, reply], CONFIG, replies_to={"201": "100"}, channel_name="my-assignments"
        )
        assignment = build_assignment(threads[0], CONFIG, NOW)
        self.assertEqual(assignment.status, Status.SUBMITTED)

    def test_an_unrelated_link_does_not_attach_itself(self):
        brief = msg("100", BRIEF)
        loose = msg("202", f"unrelated {DRIVE}", minutes=50)  # replies to nothing
        threads = collect_from_messages([brief, loose], CONFIG, channel_name="my-assignments")
        self.assertEqual(len(threads), 1)
        assignment = build_assignment(threads[0], CONFIG, NOW)
        self.assertEqual(assignment.submissions, [])
        self.assertEqual(assignment.status, Status.DUE_TODAY)

    def test_several_briefs_become_several_assignments(self):
        second = BRIEF.replace("VIDEO-001", "VIDEO-002").replace(
            "9/20/2026 @ 11:59 PM ET", "9/28/2026 @ 11:59 PM ET"
        ).replace("9/21/2026 @ 9:29 AM IST", "9/29/2026 @ 9:29 AM IST")
        threads = collect_from_messages(
            [msg("100", BRIEF), msg("101", second, minutes=5), msg("102", "thanks!", minutes=6)],
            CONFIG,
            channel_name="my-assignments",
        )
        self.assertEqual(len(threads), 2)
        items = build_assignments(threads, CONFIG, now=NOW, overrides={})
        self.assertEqual(
            sorted(a.status.value for a in items), ["DUE_TODAY", "PENDING"]
        )

    def test_a_forwarded_brief_survives_the_whole_pipeline(self):
        # What actually happens: forward the brief, then post the link.
        forwarded = FakeMessage(content="", snapshots=[FakeSnapshot(content=BRIEF)])
        brief = msg("100", message_text(forwarded))
        threads = collect_from_messages(
            [brief], CONFIG, thread_messages={"100": [msg("200", DRIVE, minutes=10)]}
        )
        assignment = build_assignment(threads[0], CONFIG, NOW)
        self.assertEqual(assignment.status, Status.SUBMITTED)
        self.assertEqual(assignment.slot, "VIDEO-001")

    def test_the_brief_itself_is_never_counted_as_a_delivery(self):
        brief = msg("100", BRIEF + f"\nreference doc: {DRIVE}")
        threads = collect_from_messages([brief], CONFIG)
        assignment = build_assignment(threads[0], CONFIG, NOW)
        self.assertEqual(assignment.submissions, [])

    def test_synthesized_threads_order_followups_by_time(self):
        brief = msg("100", BRIEF)
        thread = synthesize_thread(
            brief, [msg("b", "second", minutes=20), msg("a", "first", minutes=10)], CONFIG
        )
        self.assertEqual([m.id for m in thread.messages], ["100", "a", "b"])


if __name__ == "__main__":
    unittest.main()


class TestChannelScoping(unittest.TestCase):
    def test_dropbox_mode_does_not_also_scan_every_other_channel(self):
        config = Config(dropbox_channel_patterns=["my-assignments"])
        self.assertTrue(config.dropbox_matches("my-assignments", "1"))
        # Personal servers have other channels; none of them are assignments.
        self.assertFalse(config.channel_matches("general", "2"))
        self.assertFalse(config.channel_matches("random", "3"))

    def test_an_explicit_thread_filter_still_wins(self):
        config = Config(
            dropbox_channel_patterns=["my-assignments"],
            channel_name_patterns=["workflow"],
        )
        self.assertTrue(config.channel_matches("their-workflow", "2"))
        self.assertFalse(config.channel_matches("general", "3"))

    def test_without_dropbox_an_empty_filter_still_means_everything(self):
        self.assertTrue(Config().channel_matches("anything", "1"))
