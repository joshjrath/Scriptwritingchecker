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
        # A different script, so a different title - sharing a title would
        # (correctly) be read as the same brief forwarded twice.
        second = BRIEF.replace(
            "VIDEO-001 | What If Sans Remembered Every RESET?",
            "VIDEO-002 | How Do Spider-Man's Webs Work?",
        ).replace(
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


class TestProjectParsing(unittest.TestCase):
    """Video numbers restart per channel, so the project is the identifier."""

    def test_the_show_tag_is_picked_up(self):
        from scriptcheck.parsing import parse_project

        self.assertEqual(parse_project("\U0001f4c1 Project\nTBD\n\n@ UTDR\n"), "UTDR")

    def test_a_decorated_tag_line_still_counts(self):
        from scriptcheck.parsing import parse_project

        # These briefs prefix everything with an emoji.
        self.assertEqual(parse_project("\U0001f4fa @ UTDR\n"), "UTDR")

    def test_a_person_mention_is_not_a_project(self):
        from scriptcheck.parsing import parse_project

        self.assertEqual(parse_project("@Josh\n"), "")
        self.assertEqual(parse_project("\u2022 @Maria\n"), "")

    def test_a_named_project_beats_the_tag(self):
        from scriptcheck.parsing import parse_project

        text = "Project: Undertale Deep Dives\n\n@ UTDR\n"
        self.assertEqual(parse_project(text), "Undertale Deep Dives")

    def test_a_label_on_its_own_line_takes_the_next_line(self):
        from scriptcheck.parsing import parse_project

        self.assertEqual(parse_project("\U0001f4c1 Project\nMarvel Explained\n"), "Marvel Explained")

    def test_placeholders_are_not_a_project(self):
        from scriptcheck.parsing import parse_project

        self.assertEqual(parse_project("Project\nTBD\n"), "")
        self.assertEqual(parse_project("Channel: N/A"), "")

    def test_other_labels_work_too(self):
        from scriptcheck.parsing import parse_project

        for text in ["Show: Sci Explained", "Channel - Sci Explained", "Series: Sci Explained"]:
            self.assertEqual(parse_project(text), "Sci Explained")

    def test_nothing_found_is_empty(self):
        from scriptcheck.parsing import parse_project

        self.assertEqual(parse_project("just a note about the script"), "")
        self.assertEqual(parse_project(""), "")

    def test_the_assignment_carries_project_and_start(self):
        brief = msg("100", "\U0001f4c1 Project\nUndertale\n\n" + BRIEF)
        threads = collect_from_messages([brief], CONFIG)
        assignment = build_assignment(threads[0], CONFIG, NOW)
        self.assertEqual(assignment.project, "Undertale")
        self.assertEqual(assignment.assigned_at, brief.created_at)


class TestDuplicateForwards(unittest.TestCase):
    """Forwarding the same brief twice must not become two assignments."""

    def two_forwards(self, second_text=None, delivered_in=None, minutes=60):
        first = msg("100", BRIEF)
        second = msg("200", second_text or BRIEF, minutes=minutes)
        threads = collect_from_messages([first], CONFIG) + collect_from_messages(
            [second], CONFIG
        )
        if delivered_in is not None:
            threads[delivered_in].messages.append(
                msg("900", "done " + DRIVE, minutes=minutes + 5)
            )
        return build_assignments(threads, CONFIG, now=NOW, include_all=True, overrides={})

    def test_the_second_copy_is_flagged_not_counted(self):
        items = self.two_forwards()
        statuses = sorted(a.status.value for a in items)
        self.assertEqual(statuses, ["DUE_TODAY", "DUPLICATE"])

    def test_the_duplicate_points_at_the_copy_being_tracked(self):
        items = self.two_forwards()
        dupe = next(a for a in items if a.status is Status.DUPLICATE)
        kept = next(a for a in items if a.status is not Status.DUPLICATE)
        self.assertEqual(dupe.duplicate_of, kept.thread_id)
        self.assertTrue(any("Same script as" in w for w in dupe.warnings))
        self.assertTrue(any("Forwarded 2 times" in w for w in kept.warnings))

    def test_the_newest_forward_wins_when_neither_is_delivered(self):
        items = self.two_forwards()
        kept = next(a for a in items if a.status is not Status.DUPLICATE)
        self.assertEqual(kept.thread_id, "200")

    def test_the_copy_holding_the_delivery_wins(self):
        # The older forward has the Drive link in its thread, so it is the one
        # that matters even though a newer copy exists.
        items = self.two_forwards(delivered_in=0)
        kept = next(a for a in items if a.status is not Status.DUPLICATE)
        self.assertEqual(kept.thread_id, "100")
        self.assertTrue(kept.status.is_submitted)

    def test_a_changed_deadline_is_called_out_loudly(self):
        revised = BRIEF.replace("9/20/2026 @ 11:59 PM ET", "9/24/2026 @ 11:59 PM ET")
        items = self.two_forwards(second_text=revised)
        dupe = next(a for a in items if a.status is Status.DUPLICATE)
        self.assertTrue(any("different deadlines" in w for w in dupe.warnings))
        self.assertTrue(dupe.needs_review)

    def test_different_scripts_are_left_alone(self):
        other = BRIEF.replace(
            "VIDEO-001 | What If Sans Remembered Every RESET?",
            "VIDEO-002 | How Do Spider-Man's Webs Work?",
        )
        items = self.two_forwards(second_text=other)
        self.assertFalse([a for a in items if a.status is Status.DUPLICATE])

    def test_the_same_title_on_a_different_show_is_not_a_duplicate(self):
        other_show = BRIEF.replace("@ UTDR", "@ MARVEL")
        items = self.two_forwards(second_text="\U0001f4c1 Project\nMarvel\n\n" + other_show)
        self.assertFalse([a for a in items if a.status is Status.DUPLICATE])

    def test_case_and_punctuation_do_not_defeat_it(self):
        shouty = BRIEF.replace(
            "What If Sans Remembered Every RESET?", "WHAT IF SANS REMEMBERED EVERY RESET"
        )
        items = self.two_forwards(second_text=shouty)
        self.assertEqual(len([a for a in items if a.status is Status.DUPLICATE]), 1)

    def test_three_forwards_leave_one_live(self):
        threads = []
        for i, mid in enumerate(["100", "200", "300"]):
            threads += collect_from_messages([msg(mid, BRIEF, minutes=i * 30)], CONFIG)
        items = build_assignments(threads, CONFIG, now=NOW, include_all=True, overrides={})
        live = [a for a in items if a.status is not Status.DUPLICATE]
        self.assertEqual(len(live), 1)
        self.assertEqual(len(items) - len(live), 2)
        self.assertTrue(any("Forwarded 3 times" in w for w in live[0].warnings))

    def test_duplicates_do_not_raise_their_own_alerts(self):
        from scriptcheck.alerts import AlertTracker

        items = self.two_forwards()
        tracker = AlertTracker()
        tracker.prime([], NOW)
        alerts = tracker.scan(items, NOW)
        # One new assignment announced, not two.
        self.assertEqual(len(alerts), 1)
