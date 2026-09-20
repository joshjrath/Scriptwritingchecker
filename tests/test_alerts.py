import unittest
from datetime import datetime, timedelta, timezone

from scriptcheck.alerts import (
    ALL_KINDS,
    DELIVERED,
    DUE_IN,
    NEW,
    OVERDUE,
    AlertTracker,
    format_digest,
)
from scriptcheck.models import Assignment, Status, Submission

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def item(thread_id="1", status=Status.PENDING, hours=None, subs=0, title="A Script"):
    """`hours` is the deadline's offset from NOW, not from the scan time.

    Time passing is modelled by scanning with a later `now`, the way the daemon
    actually works - moving the deadline instead would look like a real
    schedule change, which is a different alert.
    """

    return Assignment(
        thread_id=thread_id,
        thread_name=title,
        title=title,
        status=status,
        deadline=NOW + timedelta(hours=hours) if hours is not None else None,
        submissions=[Submission(message_id=str(i)) for i in range(subs)],
        jump_url=f"https://discord.com/channels/1/{thread_id}",
    )


def later(hours):
    return NOW + timedelta(hours=hours)


def kinds(alerts):
    return [a.kind for a in alerts]


class TestPriming(unittest.TestCase):
    def test_the_first_scan_never_alerts(self):
        tracker = AlertTracker()
        self.assertEqual(tracker.scan([item(hours=1), item("2", Status.OVERDUE, -5)], NOW), [])

    def test_a_restart_does_not_replay_a_window_already_passed(self):
        tracker = AlertTracker(lead_hours=[24, 2])
        tracker.prime([item(hours=1)], NOW)
        # Still inside both windows a minute later; nothing should fire.
        self.assertEqual(tracker.scan([item(hours=1)], NOW + timedelta(minutes=1)), [])

    def test_an_overdue_item_present_at_startup_is_not_re_announced(self):
        tracker = AlertTracker()
        tracker.prime([item("1", Status.OVERDUE, -3)], NOW)
        self.assertEqual(tracker.scan([item("1", Status.OVERDUE, -3)], NOW), [])


class TestTransitions(unittest.TestCase):
    def setUp(self):
        self.tracker = AlertTracker(lead_hours=[24, 2])
        self.tracker.prime([item(hours=100)], NOW)

    def test_a_new_thread_announces_itself(self):
        alerts = self.tracker.scan([item(hours=100), item("2", hours=72)], NOW)
        self.assertEqual(kinds(alerts), [NEW])
        self.assertIn("New script assigned", alerts[0].text)
        self.assertIn("due in 3d", alerts[0].text)

    def test_a_delivery_announces_itself(self):
        alerts = self.tracker.scan(
            [item(hours=100, status=Status.SUBMITTED, subs=1)], NOW
        )
        self.assertEqual(kinds(alerts), [DELIVERED])
        self.assertIn("on time", alerts[0].text)

    def test_a_late_delivery_says_late(self):
        alerts = self.tracker.scan(
            [item(hours=100, status=Status.SUBMITTED_LATE, subs=1)], NOW
        )
        self.assertIn("late", alerts[0].text)

    def test_a_removed_thread_is_forgotten(self):
        self.tracker.scan([], NOW)
        self.assertNotIn("1", self.tracker.previous)


class TestDeadlineReminders(unittest.TestCase):
    """The deadline is fixed 100h out; the clock is what moves."""

    def setUp(self):
        self.tracker = AlertTracker(lead_hours=[24, 2])
        self.tracker.prime([item(hours=100)], NOW)

    def test_the_24h_window_fires_once(self):
        first = self.tracker.scan([item(hours=100)], later(80))  # 20h remaining
        self.assertEqual(kinds(first), [DUE_IN])
        self.assertIn("Due in 20h", first[0].text)
        # Twelve minutes later, still inside the same window: silence.
        self.assertEqual(self.tracker.scan([item(hours=100)], later(80.2)), [])

    def test_the_tighter_window_fires_separately(self):
        self.tracker.scan([item(hours=100)], later(80))
        alerts = self.tracker.scan([item(hours=100)], later(98.5))  # 1h30 left
        self.assertEqual(kinds(alerts), [DUE_IN])
        self.assertIn("1h 30m", alerts[0].text)

    def test_arriving_inside_both_windows_sends_one_alert_not_two(self):
        alerts = self.tracker.scan([item(hours=100)], later(99))  # 1h left
        self.assertEqual(len(alerts), 1)
        self.assertIn("1h", alerts[0].text)

    def test_passing_the_deadline_alerts_once(self):
        self.assertEqual(
            kinds(self.tracker.scan([item(hours=100)], later(100.1))), [OVERDUE]
        )
        self.assertEqual(self.tracker.scan([item(hours=100)], later(102)), [])

    def test_a_delivered_item_stops_nagging(self):
        alerts = self.tracker.scan(
            [item(hours=100, status=Status.SUBMITTED, subs=1)], later(105)
        )
        self.assertNotIn(OVERDUE, kinds(alerts))

    def test_a_moved_deadline_re_arms_the_reminders(self):
        self.tracker.scan([item(hours=100)], later(80))       # fires the 24h window
        moved = self.tracker.scan([item(hours=130)], later(80))  # pushed out 30h
        self.assertIn("deadline_changed", kinds(moved))
        # The new deadline earns its own reminder when it comes around.
        again = self.tracker.scan([item(hours=130)], later(110))
        self.assertIn(DUE_IN, kinds(again))

    def test_a_new_assignment_does_not_also_send_a_due_in(self):
        alerts = self.tracker.scan(
            [item(hours=100), item("2", hours=101)], later(100)  # brand new, 1h out
        )
        self.assertEqual(kinds([a for a in alerts if a.thread_id == "2"]), [NEW])


class TestKindFiltering(unittest.TestCase):
    def test_only_requested_kinds_are_emitted(self):
        tracker = AlertTracker(lead_hours=[24], kinds=[OVERDUE])
        tracker.prime([item(hours=100)], NOW)
        alerts = tracker.scan([item(hours=100), item("2", hours=10)], NOW)
        self.assertEqual(alerts, [])
        self.assertEqual(kinds(tracker.scan([item("1", hours=-1)], NOW)), [OVERDUE])

    def test_the_default_is_everything(self):
        self.assertEqual(set(AlertTracker().kinds), set(ALL_KINDS))


class TestDigest(unittest.TestCase):
    def test_one_alert_is_a_bare_line(self):
        tracker = AlertTracker()
        tracker.prime([], NOW)
        alerts = tracker.scan([item(hours=5)], NOW)
        self.assertEqual(len(alerts), 1)
        text = format_digest(alerts)
        self.assertNotIn("Script board update", text)
        self.assertIn("A Script", text)
        self.assertIn("https://discord.com/channels/1/1", text)

    def test_several_alerts_are_bulleted(self):
        tracker = AlertTracker()
        tracker.prime([], NOW)
        alerts = tracker.scan([item(hours=5), item("2", hours=6)], NOW)
        text = format_digest(alerts)
        self.assertIn("Script board update", text)
        self.assertEqual(text.count("\n- "), 2)

    def test_nothing_to_say(self):
        self.assertEqual(format_digest([]), "")


if __name__ == "__main__":
    unittest.main()
