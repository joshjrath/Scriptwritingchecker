"""Tests for the parts that keep the tracker from being confidently wrong."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scriptcheck import overrides as ov
from scriptcheck.audit import coverage, render_audit, render_explain, unparsed_roles
from scriptcheck.config import Config
from scriptcheck.engine import build_assignment, build_assignments
from scriptcheck.models import Attachment, Author, Confidence, Message, Status, Thread
from scriptcheck.parsing import looks_like_deadline_change
from scriptcheck.sources.export_json import load_threads

FIXTURE = Path(__file__).parent / "fixtures" / "sample_threads.json"
NOW = datetime(2026, 9, 20, 19, 30, tzinfo=timezone.utc)
CONFIG = Config(
    my_user_ids=["111111111111111111"],
    my_names=["Josh", "joshjrath"],
    my_roles=["SCRIPT"],
    default_timezone="America/New_York",
    preferred_timezones=["America/New_York"],
    overrides_file="/nonexistent-overrides.json",
)

ME = Author(id="111111111111111111", name="joshjrath", display_name="Josh")
ASH = Author(id="222222222222222222", name="ash", display_name="Ash")


def raw(index):
    return json.loads(FIXTURE.read_text())["threads"][index]


class TestDeadlineChangeDetection(unittest.TestCase):
    def test_phrases_that_mean_a_schedule_moved(self):
        for text in [
            "new deadline is 9/23/2026 @ 11:59 PM ET",
            "take an extra day on this one",
            "pushed to Monday",
            "extension granted",
            "moving this to 9/25",
            "can we push this back? more time would help",
        ]:
            self.assertTrue(looks_like_deadline_change(text), text)

    def test_ordinary_chat_is_not_a_schedule_change(self):
        for text in [
            "on it, first draft tonight",
            "received, thank you!",
            "I moved to Chicago last year",
            "any update on this one?",
            "the character moves to the next scene",
        ]:
            self.assertFalse(looks_like_deadline_change(text), text)

    def test_a_change_in_the_thread_is_flagged_not_applied(self):
        thread = Thread.from_dict(raw(0))
        thread.messages.append(
            Message(
                id="9001",
                author=ASH,
                content="hey, take an extra day - new deadline 9/22/2026 @ 11:59 PM ET",
                created_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            )
        )
        assignment = build_assignment(thread, CONFIG, NOW)
        # The brief's deadline still governs...
        self.assertEqual(
            assignment.deadline, datetime(2026, 9, 21, 3, 59, tzinfo=timezone.utc)
        )
        # ...but the row is marked as needing eyes rather than trusted.
        self.assertTrue(any("changed the deadline" in w for w in assignment.warnings))
        self.assertEqual(assignment.confidence, Confidence.LOW)
        self.assertTrue(assignment.needs_review)

    def test_my_own_message_does_not_trigger_it(self):
        thread = Thread.from_dict(raw(0))
        thread.messages.append(
            Message(
                id="9002",
                author=ME,
                content="can I take an extra day?",
                created_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            )
        )
        assignment = build_assignment(thread, CONFIG, NOW)
        self.assertFalse(any("changed the deadline" in w for w in assignment.warnings))


class TestDeliveryAmbiguity(unittest.TestCase):
    def test_link_edited_in_after_the_deadline_is_flagged(self):
        thread = Thread.from_dict(raw(3))  # delivered on time
        thread.messages[1].edited_at = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
        assignment = build_assignment(thread, CONFIG, NOW)
        self.assertTrue(any("edited after the deadline" in w for w in assignment.warnings))
        self.assertEqual(assignment.confidence, Confidence.LOW)

    def test_an_edit_before_the_deadline_is_not_flagged(self):
        thread = Thread.from_dict(raw(3))
        thread.messages[1].edited_at = datetime(2026, 9, 17, 21, 0, tzinfo=timezone.utc)
        assignment = build_assignment(thread, CONFIG, NOW)
        self.assertFalse(any("edited after" in w for w in assignment.warnings))

    def test_a_drive_link_in_an_attachment_url_counts(self):
        thread = Thread.from_dict(raw(2))  # overdue, no link
        thread.messages.append(
            Message(
                id="9003",
                author=ME,
                content="here",
                created_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
                attachments=[
                    Attachment(filename="script.docx", url="https://drive.google.com/file/d/x/view")
                ],
            )
        )
        assignment = build_assignment(thread, CONFIG, NOW)
        self.assertTrue(assignment.submissions)


class TestFetchCompleteness(unittest.TestCase):
    def test_hitting_the_message_cap_is_reported(self):
        config = Config(
            my_user_ids=["111111111111111111"],
            my_roles=["SCRIPT"],
            max_messages_per_thread=2,
            overrides_file="/nonexistent-overrides.json",
        )
        thread = Thread.from_dict(raw(2))  # two messages
        assignment = build_assignment(thread, config, NOW)
        self.assertTrue(any("fetch cap" in w for w in assignment.warnings))
        self.assertEqual(assignment.confidence, Confidence.LOW)


class TestConfidence(unittest.TestCase):
    def test_user_id_match_is_high(self):
        self.assertEqual(
            build_assignment(Thread.from_dict(raw(0)), CONFIG, NOW).confidence,
            Confidence.HIGH,
        )

    def test_name_only_match_is_medium(self):
        config = Config(
            my_names=["Josh"], my_roles=["SCRIPT"], overrides_file="/nonexistent-overrides.json"
        )
        assignment = build_assignment(Thread.from_dict(raw(0)), config, NOW)
        self.assertEqual(assignment.confidence, Confidence.MEDIUM)

    def test_deadline_outside_a_role_section_is_low(self):
        thread = Thread.from_dict(raw(0))
        # Strip the role header, leaving the dates adrift in the post.
        thread.messages[0].content = thread.messages[0].content.replace(
            "\U0001f4dd SCRIPT <@111111111111111111>", "Notes"
        )
        assignment = build_assignment(thread, CONFIG, NOW)
        self.assertEqual(assignment.confidence, Confidence.LOW)
        self.assertTrue(assignment.needs_review)

    def test_a_missing_timezone_lowers_confidence(self):
        thread = Thread.from_dict(raw(0))
        thread.messages[0].content = thread.messages[0].content.replace(
            "9/20/2026 @ 11:59 PM ET", "9/20/2026 @ 11:59 PM"
        ).replace("9/21/2026 @ 9:29 AM IST", "")
        assignment = build_assignment(thread, CONFIG, NOW)
        self.assertEqual(assignment.confidence, Confidence.MEDIUM)
        self.assertTrue(any("names no timezone" in w for w in assignment.warnings))

    def test_an_unreadable_deadline_line_names_the_text(self):
        assignment = build_assignment(Thread.from_dict(raw(6)), CONFIG, NOW)
        self.assertEqual(assignment.status, Status.NO_DEADLINE)
        self.assertTrue(any("TBD" in w for w in assignment.warnings), assignment.warnings)


class TestOverrides(unittest.TestCase):
    def setUp(self):
        self.threads = load_threads(FIXTURE)

    def build(self, table):
        return {
            a.thread_id: a
            for a in build_assignments(
                self.threads, CONFIG, now=NOW, include_all=True, overrides=table
            )
        }

    def test_a_corrected_deadline_redecides_the_status(self):
        items = self.build({"1003": {"deadline": "2026-09-25T23:59:00-04:00"}})
        self.assertEqual(items["1003"].status, Status.PENDING)  # was OVERDUE
        self.assertIn("deadline", items["1003"].overridden)
        self.assertTrue(any("Corrected by hand" in w for w in items["1003"].warnings))

    def test_a_manual_delivery_marks_it_submitted(self):
        items = self.build(
            {"1008": {"delivered_at": "2026-09-19T20:00:00-04:00", "links": ["https://x"]}}
        )
        self.assertEqual(items["1008"].status, Status.SUBMITTED)
        self.assertEqual(items["1008"].submissions[0].links, ["https://x"])

    def test_an_explicit_status_wins_outright(self):
        items = self.build({"1003": {"status": "IGNORED", "note": "cancelled by Ash"}})
        self.assertEqual(items["1003"].status, Status.IGNORED)
        self.assertTrue(any("cancelled by Ash" in w for w in items["1003"].warnings))

    def test_ignore_shortcut(self):
        self.assertEqual(self.build({"1001": {"ignore": True}})["1001"].status, Status.IGNORED)

    def test_typos_are_rejected_loudly(self):
        with self.assertRaises(ValueError) as ctx:
            ov.load(self._write({"1001": {"deadlien": "2026-09-25"}}))
        self.assertIn("deadlien", str(ctx.exception))

    def test_an_unreadable_timestamp_is_rejected(self):
        from scriptcheck.models import Assignment

        with self.assertRaises(ValueError):
            ov.apply(Assignment(), {"deadline": "next tuesday sometime"})

    def test_a_missing_file_is_not_an_error(self):
        self.assertEqual(ov.load("/nonexistent-overrides.json"), {})

    def _write(self, data):
        import tempfile

        path = Path(tempfile.mkdtemp()) / "overrides.json"
        path.write_text(json.dumps(data))
        return path


class TestAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = load_threads(FIXTURE)
        cls.items = build_assignments(cls.threads, CONFIG, now=NOW)

    def test_coverage_counts(self):
        stats = coverage(self.threads, self.items, CONFIG)
        self.assertEqual(stats["threads_fetched"], 8)
        self.assertEqual(stats["role_section_found"], len(self.items))
        self.assertEqual(stats["assignee_by_user_id"], len(self.items))
        self.assertEqual(stats["deadline_found"], len(self.items) - 1)
        self.assertEqual(stats["needs_review"], 1)

    def test_role_headers_the_config_does_not_know_are_surfaced(self):
        thread = Thread.from_dict(raw(0))
        thread.messages[0].content += (
            "\n\nSTORYBOARD <@444444444444444444>\n\u2022 Deadline: 9/26/2026"
        )
        seen = unparsed_roles([thread], CONFIG)
        self.assertIn("STORYBOARD", seen)
        self.assertNotIn("STORYBOARD", {r.upper() for r in CONFIG.known_roles})

    def test_audit_report_names_what_needs_a_look(self):
        text = render_audit(self.threads, self.items, CONFIG, NOW)
        self.assertIn("PARSE AUDIT", text)
        self.assertIn("Needs a human look (1)", text)
        self.assertIn("Gojo", text)

    def test_explain_shows_the_line_a_deadline_came_from(self):
        thread = next(t for t in self.threads if t.id == "1001")
        text = render_explain(thread, CONFIG, NOW)
        self.assertIn("9/20/2026 @ 11:59 PM ET", text)
        self.assertIn("SCRIPT", text)
        self.assertIn("OPENING POST AS FETCHED", text)
        self.assertIn("never used as a deadline", text)


if __name__ == "__main__":
    unittest.main()
