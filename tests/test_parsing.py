import unittest
from datetime import datetime, time, timezone

from scriptcheck.parsing import (
    choose_deadline,
    deadline_text,
    extract_datetimes,
    find_links,
    mentions,
    parse_thread_title,
    parse_word_count,
    split_role_sections,
)

BRIEF = """09-25-26 | VIDEO-001 | What If Sans Remembered Every RESET?

\U0001f4c1 Project
TBD

@ UTDR

__________________

\U0001f4dd SCRIPT <@111111111111111111>

• Deadline:

  • \U0001f1fa\U0001f1f8 9/20/2026 @ 11:59 PM ET
    ◦ \U0001f1ee\U0001f1f3 9/21/2026 @ 9:29 AM IST
• Word Count: 5000 Words

Story Brief
Rewrite Undertale around one major change: Sans remembers every reset.

\U0001f3a4 VOICE OVER <@333333333333333333>

• Deadline:
  • 9/24/2026 @ 11:59 PM ET
"""


class TestTitles(unittest.TestCase):
    def test_full_title(self):
        info = parse_thread_title("09-25-26 | VIDEO-001 | What If Sans Remembered Every RESET?")
        self.assertEqual(info.slot, "VIDEO-001")
        self.assertEqual(info.title, "What If Sans Remembered Every RESET?")
        self.assertEqual(info.slate_date.date(), datetime(2026, 9, 25).date())

    def test_dash_separators_keep_slot_intact(self):
        info = parse_thread_title("09-22-26 - VIDEO 002 - How Does Goku Train?")
        self.assertEqual(info.slot, "VIDEO-002")
        self.assertEqual(info.title, "How Does Goku Train?")

    def test_unstructured_name_survives(self):
        info = parse_thread_title("general chatter")
        self.assertEqual(info.title, "general chatter")
        self.assertIsNone(info.slate_date)


class TestDeadlines(unittest.TestCase):
    def test_us_and_india_lines_are_the_same_instant(self):
        found = extract_datetimes(
            "\U0001f1fa\U0001f1f8 9/20/2026 @ 11:59 PM ET\n\U0001f1ee\U0001f1f3 9/21/2026 @ 9:29 AM IST",
            default_tz="America/New_York",
        )
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0].dt, found[1].dt)
        self.assertEqual(found[0].dt, datetime(2026, 9, 21, 3, 59, tzinfo=timezone.utc))

    def test_preferred_timezone_wins_the_quote(self):
        found = extract_datetimes(
            "9/20/2026 @ 11:59 PM ET / 9/21/2026 @ 9:29 AM IST",
            default_tz="America/New_York",
        )
        chosen = choose_deadline(found, ["America/New_York"])
        self.assertEqual(chosen.tz_label, "ET")
        chosen_in = choose_deadline(found, ["Asia/Kolkata"])
        self.assertEqual(chosen_in.tz_label, "IST")

    def test_disagreeing_deadlines_pick_the_earlier(self):
        found = extract_datetimes("9/22/2026 11:59 PM ET or 9/20/2026 11:59 PM ET")
        chosen = choose_deadline(found, [])
        self.assertEqual(chosen.dt.date(), datetime(2026, 9, 21).date())

    def test_discord_timestamp_is_exact_and_wins(self):
        found = extract_datetimes("Due <t:1790000000:F> (9/25/2026 @ 5:00 PM ET)")
        chosen = choose_deadline(found, ["America/New_York"])
        self.assertTrue(chosen.exact)
        self.assertEqual(chosen.dt, datetime.fromtimestamp(1790000000, tz=timezone.utc))

    def test_date_without_time_uses_assumed_end_of_day(self):
        found = extract_datetimes(
            "Deadline: 9/20/2026", default_tz="America/New_York", assume_time=time(23, 59)
        )
        self.assertEqual(found[0].dt, datetime(2026, 9, 21, 3, 59, tzinfo=timezone.utc))

    def test_month_name_and_iso_forms(self):
        self.assertEqual(
            extract_datetimes("due Sept 20, 2026 11:59 pm ET")[0].dt,
            datetime(2026, 9, 21, 3, 59, tzinfo=timezone.utc),
        )
        self.assertEqual(
            extract_datetimes("due 2026-09-20 23:59 ET")[0].dt,
            datetime(2026, 9, 21, 3, 59, tzinfo=timezone.utc),
        )

    def test_am_pm_is_not_read_as_a_timezone(self):
        found = extract_datetimes("9/20/2026 @ 11:59 PM", default_tz="America/New_York")
        self.assertEqual(found[0].tz_label, "")
        self.assertEqual(found[0].dt, datetime(2026, 9, 21, 3, 59, tzinfo=timezone.utc))

    def test_no_dates_found(self):
        self.assertEqual(extract_datetimes("Deadline: TBD"), [])
        self.assertIsNone(choose_deadline([]))


class TestSections(unittest.TestCase):
    def setUp(self):
        self.sections = split_role_sections(BRIEF)
        self.by_role = {s.role: s for s in self.sections}

    def test_roles_are_found(self):
        self.assertIn("SCRIPT", self.by_role)
        self.assertIn("VOICE OVER", self.by_role)

    def test_assignees_are_attached_to_their_section(self):
        self.assertEqual(self.by_role["SCRIPT"].mention_ids, ["111111111111111111"])
        self.assertEqual(self.by_role["VOICE OVER"].mention_ids, ["333333333333333333"])

    def test_section_deadline_is_scoped(self):
        script_text = deadline_text(self.by_role["SCRIPT"].text)
        found = extract_datetimes(script_text, default_tz="America/New_York")
        self.assertTrue(all(f.dt.date().day in (20, 21) for f in found))
        vo_text = deadline_text(self.by_role["VOICE OVER"].text)
        self.assertIn("9/24/2026", vo_text)

    def test_deadline_text_stops_before_word_count(self):
        self.assertNotIn("Word Count", deadline_text(self.by_role["SCRIPT"].text))

    def test_word_count(self):
        self.assertEqual(parse_word_count(BRIEF), 5000)
        self.assertEqual(parse_word_count("Word Count: 4,500 Words"), 4500)
        self.assertEqual(parse_word_count("around 3500 words please"), 3500)
        self.assertIsNone(parse_word_count("no numbers here"))

    def test_plain_at_names(self):
        ids, names = mentions("\U0001f4dd SCRIPT @Josh")
        self.assertEqual(ids, [])
        self.assertEqual(names, ["Josh"])


class TestLinks(unittest.TestCase):
    def test_drive_links_are_found(self):
        text = "here you go https://docs.google.com/document/d/abc123/edit?usp=sharing thanks"
        self.assertEqual(
            find_links(text),
            ["https://docs.google.com/document/d/abc123/edit?usp=sharing"],
        )

    def test_other_links_are_ignored(self):
        self.assertEqual(find_links("see https://youtube.com/watch?v=x"), [])

    def test_trailing_punctuation_is_trimmed(self):
        self.assertEqual(
            find_links("done: https://drive.google.com/file/d/xyz/view."),
            ["https://drive.google.com/file/d/xyz/view"],
        )


if __name__ == "__main__":
    unittest.main()
