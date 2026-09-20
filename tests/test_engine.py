import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scriptcheck.config import Config
from scriptcheck.engine import build_assignment, build_assignments
from scriptcheck.models import Status, Thread
from scriptcheck.report import render
from scriptcheck.sources.export_json import load_threads

FIXTURE = Path(__file__).parent / "fixtures" / "sample_threads.json"
NOW = datetime(2026, 9, 20, 19, 30, tzinfo=timezone.utc)  # Sun 3:30 PM ET

CONFIG = Config(
    my_user_ids=["111111111111111111"],
    my_names=["Josh", "joshjrath"],
    my_roles=["SCRIPT"],
    default_timezone="America/New_York",
    preferred_timezones=["America/New_York"],
    display_timezone="America/New_York",
)


def thread_by_name(threads, fragment):
    return next(t for t in threads if fragment in t.name)


class TestEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = load_threads(FIXTURE)
        cls.by_id = {t.id: t for t in cls.threads}

    def status_of(self, thread_id):
        return build_assignment(self.by_id[thread_id], CONFIG, NOW).status

    def test_due_today(self):
        assignment = build_assignment(self.by_id["1001"], CONFIG, NOW)
        self.assertEqual(assignment.status, Status.DUE_TODAY)
        self.assertEqual(assignment.word_count, 5000)
        self.assertEqual(assignment.role, "SCRIPT")
        self.assertEqual(
            assignment.deadline, datetime(2026, 9, 21, 3, 59, tzinfo=timezone.utc)
        )
        self.assertEqual(assignment.deadline_tz, "ET")

    def test_pending_far_out(self):
        self.assertEqual(self.status_of("1002"), Status.PENDING)

    def test_overdue_with_no_link(self):
        assignment = build_assignment(self.by_id["1003"], CONFIG, NOW)
        self.assertEqual(assignment.status, Status.OVERDUE)
        self.assertEqual(assignment.submissions, [])

    def test_delivered_on_time(self):
        assignment = build_assignment(self.by_id["1004"], CONFIG, NOW)
        self.assertEqual(assignment.status, Status.SUBMITTED)
        self.assertEqual(len(assignment.submissions), 1)
        self.assertIn("docs.google.com", assignment.submissions[0].links[0])
        self.assertEqual(assignment.replies_after_delivery, 1)

    def test_delivered_late(self):
        assignment = build_assignment(self.by_id["1005"], CONFIG, NOW)
        self.assertEqual(assignment.status, Status.SUBMITTED_LATE)
        self.assertGreater(
            assignment.submissions[0].posted_at, assignment.deadline
        )

    def test_someone_elses_script(self):
        self.assertEqual(self.status_of("1006"), Status.NOT_MINE)

    def test_missing_deadline_is_flagged_not_guessed(self):
        assignment = build_assignment(self.by_id["1007"], CONFIG, NOW)
        self.assertEqual(assignment.status, Status.NO_DEADLINE)
        self.assertIsNone(assignment.deadline)

    def test_slate_date_is_not_mistaken_for_a_deadline(self):
        # Thread 1007's title says 09-27-26 but its brief states no deadline.
        assignment = build_assignment(self.by_id["1007"], CONFIG, NOW)
        self.assertIsNone(assignment.deadline)
        self.assertEqual(assignment.slate_date.date(), datetime(2026, 9, 27).date())

    def test_done_tag_without_a_link_warns(self):
        assignment = build_assignment(self.by_id["1008"], CONFIG, NOW)
        self.assertEqual(assignment.status, Status.OVERDUE)
        self.assertTrue(
            any("tagged as delivered" in w for w in assignment.warnings), assignment.warnings
        )

    def test_a_chat_message_is_not_a_submission(self):
        # "on it, first draft tonight" carries no link.
        self.assertEqual(build_assignment(self.by_id["1008"], CONFIG, NOW).submissions, [])

    def test_someone_elses_link_does_not_count(self):
        thread = Thread.from_dict(json.loads(FIXTURE.read_text())["threads"][3])
        thread.messages[1].author.id = "999999999999999999"
        thread.messages[1].author.name = "someone"
        thread.messages[1].author.display_name = "Someone"
        assignment = build_assignment(thread, CONFIG, NOW)
        self.assertEqual(assignment.submissions, [])
        self.assertEqual(assignment.status, Status.OVERDUE)

    def test_matching_by_name_when_no_user_id_is_configured(self):
        config = Config(my_names=["Josh"], my_roles=["SCRIPT"])
        thread = self.by_id["1004"]
        self.assertEqual(build_assignment(thread, config, NOW).status, Status.SUBMITTED)

    def test_unresolvable_mention_is_not_assumed_to_be_someone_else(self):
        # Only names configured, brief mentions <@id>: keep it on the list.
        config = Config(my_names=["Josh"], my_roles=["SCRIPT"])
        assignment = build_assignment(self.by_id["1001"], config, NOW)
        self.assertEqual(assignment.status, Status.DUE_TODAY)

    def test_my_link_overrides_a_mention_of_someone_else(self):
        thread = Thread.from_dict(json.loads(FIXTURE.read_text())["threads"][5])
        thread.messages.append(
            self.by_id["1004"].messages[1]
        )  # a delivery of mine into someone else's brief
        assignment = build_assignment(thread, CONFIG, NOW)
        self.assertTrue(assignment.status.is_submitted)
        self.assertTrue(any("posted a link here" in w for w in assignment.warnings))

    def test_ordering_and_filtering(self):
        items = build_assignments(self.threads, CONFIG, now=NOW)
        self.assertEqual(items[0].status, Status.OVERDUE)
        self.assertNotIn(Status.NOT_MINE, [i.status for i in items])
        self.assertEqual(len(items), 7)

        everything = build_assignments(self.threads, CONFIG, now=NOW, include_all=True)
        self.assertEqual(len(everything), 8)

    def test_ignore_tag_drops_a_thread(self):
        config = Config(
            my_user_ids=["111111111111111111"], my_roles=["SCRIPT"], ignore_tags=["Active"]
        )
        assignment = build_assignment(self.by_id["1001"], config, NOW)
        self.assertEqual(assignment.status, Status.IGNORED)

    def test_due_soon_window(self):
        earlier = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(
            build_assignment(self.by_id["1001"], CONFIG, earlier).status, Status.DUE_SOON
        )


class TestReports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = build_assignments(load_threads(FIXTURE), CONFIG, now=NOW)

    def test_text_report_mentions_every_bucket(self):
        text = render(self.items, CONFIG, "text", NOW)
        for expected in ("OVERDUE", "DUE TODAY", "DELIVERED", "NO DEADLINE FOUND"):
            self.assertIn(expected, text)

    def test_json_report_round_trips(self):
        payload = json.loads(render(self.items, CONFIG, "json", NOW))
        self.assertEqual(len(payload["assignments"]), len(self.items))
        self.assertIn("summary", payload)

    def test_csv_has_a_row_per_assignment(self):
        rows = render(self.items, CONFIG, "csv", NOW).strip().splitlines()
        self.assertEqual(len(rows), len(self.items) + 1)

    def test_markdown_links_threads(self):
        md = render(self.items, CONFIG, "md", NOW)
        self.assertIn("https://discord.com/channels/900/1003", md)


class TestNotifyChunking(unittest.TestCase):
    def test_long_digests_are_split(self):
        from scriptcheck.notify import chunk

        parts = chunk("\n".join(f"line {i} " + "x" * 80 for i in range(100)))
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= 1900 for p in parts))


if __name__ == "__main__":
    unittest.main()
