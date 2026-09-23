import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scriptcheck.config import Config
from scriptcheck.dashboard import build_payload, render_dashboard
from scriptcheck.engine import build_assignments
from scriptcheck.sources.export_json import load_threads

FIXTURE = Path(__file__).parent / "fixtures" / "sample_threads.json"
NOW = datetime(2026, 9, 20, 19, 30, tzinfo=timezone.utc)
CONFIG = Config(
    my_user_ids=["111111111111111111"],
    my_roles=["SCRIPT"],
    display_timezone="America/New_York",
)


class TestDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = build_assignments(load_threads(FIXTURE), CONFIG, now=NOW)

    def embedded(self, html):
        match = re.search(
            r'<script id="report-data" type="application/json">(.*?)</script>',
            html,
            re.S,
        )
        self.assertIsNotNone(match, "data block missing")
        return json.loads(match.group(1).replace("<\\/", "</"))

    def test_standalone_page_is_a_whole_document(self):
        html = render_dashboard(self.items, CONFIG, now=NOW)
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("</html>", html)
        self.assertIn("<title>Script Board</title>", html)

    def test_fragment_has_no_document_wrapper(self):
        html = render_dashboard(self.items, CONFIG, now=NOW, fragment=True)
        self.assertNotIn("<!doctype", html.lower())
        self.assertNotIn("<body", html.lower())
        self.assertTrue(html.startswith("<title>"))

    def test_every_assignment_is_embedded(self):
        payload = self.embedded(render_dashboard(self.items, CONFIG, now=NOW))
        self.assertEqual(len(payload["assignments"]), len(self.items))
        self.assertEqual(payload["timezone"], "America/New_York")
        self.assertEqual(payload["due_soon_hours"], CONFIG.due_soon_hours)

    def test_closing_script_tag_in_data_cannot_break_out(self):
        items = list(self.items)
        items[0].thread_name = 'x </script><script>alert(1)</script>'
        html = render_dashboard(items, CONFIG, now=NOW)
        self.assertNotIn("</script><script>alert(1)", html)
        payload = self.embedded(html)
        self.assertIn("alert(1)", payload["assignments"][0]["thread_name"])

    def test_redaction_hides_urls_but_keeps_the_delivery(self):
        payload = build_payload(self.items, CONFIG, NOW, redact_links=True)
        delivered = [a for a in payload["assignments"] if a["submissions"]]
        self.assertTrue(delivered)
        for row in delivered:
            self.assertEqual(row["jump_url"], "")
            for submission in row["submissions"]:
                self.assertTrue(submission["posted_at"])
                self.assertTrue(all("google.com" not in l for l in submission["links"]))

    def test_banner_is_carried_through(self):
        payload = build_payload(self.items, CONFIG, NOW, banner="Sample data")
        self.assertEqual(payload["banner"], "Sample data")


if __name__ == "__main__":
    unittest.main()


class TestBranding(unittest.TestCase):
    """A logo and a name can be set without touching the code."""

    def test_defaults_carry_the_drawn_mark(self):
        payload = build_payload([], CONFIG)
        self.assertEqual(payload["logo_url"], "")
        self.assertEqual(payload["board_title"], "Script Board")

    def test_a_logo_and_title_reach_the_page(self):
        config = Config(logo_url="https://cdn.example/logo.png", board_title="Specular Scripts")
        html = render_dashboard([], config)
        self.assertIn("https://cdn.example/logo.png", html)
        self.assertIn("Specular Scripts", html)

    def test_environment_variables_set_them(self):
        import os

        saved = {k: os.environ.get(k) for k in ("SCRIPTCHECK_LOGO_URL", "SCRIPTCHECK_BOARD_TITLE")}
        os.environ["SCRIPTCHECK_LOGO_URL"] = "https://cdn.example/x.png"
        os.environ["SCRIPTCHECK_BOARD_TITLE"] = "My Board"
        try:
            config = Config.load()
            self.assertEqual(config.logo_url, "https://cdn.example/x.png")
            self.assertEqual(config.board_title, "My Board")
        finally:
            for key, value in saved.items():
                os.environ.pop(key, None)
                if value is not None:
                    os.environ[key] = value

    def test_a_title_with_markup_cannot_break_out_of_the_data_block(self):
        config = Config(board_title='</script><script>alert(1)</script>')
        html = render_dashboard([], config)
        self.assertNotIn("</script><script>alert(1)", html)


class TestTimezonePicker(unittest.TestCase):
    """Viewers pick their own zone, so nothing may be formatted server-side."""

    @classmethod
    def setUpClass(cls):
        cls.items = build_assignments(load_threads(FIXTURE), CONFIG, now=NOW)
        cls.html = render_dashboard(cls.items, CONFIG, now=NOW)

    def test_the_picker_is_in_the_subline(self):
        self.assertIn('id="tzpick"', self.html)
        self.assertIn('id="sub-roles"', self.html)

    def test_no_stale_subline_element_remains(self):
        # The picker replaced a single text node; a leftover write to the old
        # id throws and takes the whole render down with it.
        self.assertNotIn('getElementById("subline")', self.html)

    def test_the_board_zone_is_offered_and_preselected(self):
        payload = build_payload(self.items, CONFIG, now=NOW)
        self.assertEqual(payload["timezone"], "America/New_York")

    def test_the_choice_is_remembered_per_viewer(self):
        self.assertIn("scriptcheck.tz", self.html)
        self.assertIn("localStorage", self.html)

    def test_switching_zones_rebuilds_every_formatter(self):
        # Each of these renders a visible time; one left out of the rebuild
        # would silently keep showing the old zone.
        for name in ("dateFmt", "timeFmt", "dayFmt", "dayLongFmt", "dayKeyFmt"):
            self.assertRegex(self.html, r"\b%s\s*=" % name)

    def test_deadlines_reach_the_page_as_instants(self):
        payload = build_payload(self.items, CONFIG, now=NOW)
        deadlines = [i["deadline"] for i in payload["assignments"] if i.get("deadline")]
        self.assertTrue(deadlines, "fixture should carry deadlines")
        for value in deadlines:
            # An ISO instant can be re-zoned in the browser; "Sep 18, 11:59 PM
            # EDT" cannot.
            self.assertRegex(value, r"(Z|[+\-]\d{2}:\d{2})$")
            datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestMotion(unittest.TestCase):
    """The board rebuilds its whole DOM every 60s, which constrains animation."""

    @classmethod
    def setUpClass(cls):
        cls.items = build_assignments(load_threads(FIXTURE), CONFIG, now=NOW)
        cls.html = render_dashboard(cls.items, CONFIG, now=NOW)
        # The page ships a small base block plus the main one; take them all.
        cls.css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", cls.html, re.S))

    def _looping_rules(self):
        """Every rule declaring an infinite animation, as (selector, body)."""
        out = []
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", self.css):
            body = match.group(2)
            if "infinite" in body:
                out.append((match.group(1).strip(), body))
        return out

    def test_every_looping_animation_is_phase_synced(self):
        # A rebuilt element whose loop restarts at 0 reads as a stutter. The
        # fix is a negative animation-delay carrying the elapsed phase, so any
        # new infinite animation needs one too - except the page background,
        # which is static markup and never re-rendered.
        exempt = ("blob", "b1", "b2", "b3")
        for selector, body in self._looping_rules():
            if any(name in selector for name in exempt):
                continue
            self.assertIn(
                "--phase", body,
                "%s loops forever but is not phase-synced; it will restart "
                "mid-cycle on the next render" % selector,
            )

    def test_looping_rules_exist_at_all(self):
        # Guards the test above from passing vacuously.
        self.assertGreaterEqual(len(self._looping_rules()), 5)

    def test_entrances_are_gated_rather_than_replayed(self):
        self.assertIn("entered[key]", self.html)
        self.assertIn("lastChartKey", self.html)
        self.assertIn("lastHeroId", self.html)

    def test_only_owed_statuses_pulse(self):
        # Due soon, pending and undated stay still, so movement keeps meaning
        # "this is owed now" rather than just "this is on the board".
        self.assertIn('item.live === "OVERDUE" || item.live === "DUE_TODAY"', self.html)

    def test_reduced_motion_switches_everything_off(self):
        blocks = re.findall(
            r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*?)\n  \}",
            self.css, re.S,
        )
        self.assertTrue(blocks, "no reduced-motion block")
        joined = " ".join(blocks)
        for name in ("rise-in", "bar-breathe", "card-sweep", "rule-sweep",
                     "stack-rise", "col-breathe"):
            # named in a keyframes rule, so it must also be switched off
            self.assertIn(name, self.css)
        self.assertIn("animation: none", joined)

    def test_the_sheen_mixes_against_the_card_tone(self):
        # A custom property's var()s resolve against the element that declares
        # it, so a :root-level --sheen holding var(--tone) would silently come
        # out as the accent colour on every card.
        self.assertNotIn("--sheen:", self.css)
        # only the strength is a token; both themes set one
        self.assertEqual(self.css.count("--sheen-strength:"), 3)
        # and the mix happens in the rule that uses it, where --tone is in scope
        sweep = self.css.split(".card.pulsing:not(.gentle)::after", 1)[1].split("}", 1)[0]
        self.assertIn("var(--tone", sweep)
        self.assertIn("var(--sheen-strength", sweep)


class TestPostingDate(unittest.TestCase):
    """The first date in the brief title: when the video actually goes out."""

    @classmethod
    def setUpClass(cls):
        cls.items = build_assignments(load_threads(FIXTURE), CONFIG, now=NOW)
        cls.html = render_dashboard(cls.items, CONFIG, now=NOW)

    def test_it_reaches_the_payload_as_a_plain_calendar_date(self):
        payload = build_payload(self.items, CONFIG, now=NOW)
        dates = [i["slate_date"] for i in payload["assignments"] if i.get("slate_date")]
        self.assertTrue(dates, "fixture should carry posting dates")
        for value in dates:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            # Midnight UTC, because a posting date is a day, not a moment.
            self.assertEqual((parsed.hour, parsed.minute), (0, 0))

    def test_it_is_parsed_from_the_leading_date_in_the_title(self):
        for item in self.items:
            if item.slate_date and "|" in item.thread_name:
                lead = item.thread_name.split("|")[0].strip()
                month, day, _ = lead.split("-")
                self.assertEqual(item.slate_date.month, int(month))
                self.assertEqual(item.slate_date.day, int(day))

    def test_the_table_has_its_own_column(self):
        self.assertIn(">Posts</th>", self.html)

    def test_the_empty_row_spans_every_column(self):
        # Adding a column and forgetting the colSpan leaves the "nothing
        # matches" row short, which looks like a broken table.
        headers = re.findall(r'<th scope="col">', self.html)
        span = re.search(r"td\.colSpan = (\d+);", self.html)
        self.assertIsNotNone(span)
        self.assertEqual(int(span.group(1)), len(headers))

    def test_it_is_formatted_in_utc_so_the_day_never_slips(self):
        # Rendering a midnight-UTC date in a behind-UTC zone would show the
        # previous day, which is the whole reason this formatter is pinned.
        fmt_decl = re.search(r"slateLongFmt = new Intl\.DateTimeFormat\([^)]*\)",
                             self.html, re.S)
        self.assertIsNotNone(fmt_decl)
        self.assertIn('timeZone: "UTC"', fmt_decl.group(0))
        self.assertIn("weekday", fmt_decl.group(0))

    def test_it_is_not_tangled_into_the_deadline_run(self):
        # It used to be an "airs Sep 23" fragment in the same grey line as the
        # deadline; it now has its own chip so the two are never confused.
        self.assertNotIn('"airs "', self.html)
        self.assertIn('"postdate"', self.html)


class TestBriefs(unittest.TestCase):
    """The forwarded brief, shown as received - and only to the owner."""

    @classmethod
    def setUpClass(cls):
        cls.items = build_assignments(load_threads(FIXTURE), CONFIG, now=NOW)

    def test_the_forwarded_text_is_captured(self):
        texts = [i.brief_text for i in self.items if i.brief_text]
        self.assertTrue(texts, "no brief text captured at all")
        # It is the opening message verbatim, so the title line is still in it.
        item = next(i for i in self.items if i.brief_text and i.thread_name)
        self.assertIn(item.thread_name.strip(), item.brief_text)

    def test_the_owner_payload_carries_it(self):
        payload = build_payload(self.items, CONFIG, now=NOW, can_edit=True)
        self.assertTrue(any(r.get("brief_text") for r in payload["assignments"]))

    def test_a_read_only_viewer_never_receives_it(self):
        # Absent from the JSON, not merely hidden in the UI: /audit and
        # /explain are owner-only for the same reason.
        payload = build_payload(self.items, CONFIG, now=NOW, can_edit=False)
        for row in payload["assignments"]:
            self.assertNotIn("brief_text", row)

    def test_it_is_absent_from_the_html_a_viewer_is_served(self):
        body = next(i.brief_text for i in self.items if i.brief_text)
        needle = max((line.strip() for line in body.splitlines()), key=len)
        self.assertGreater(len(needle), 20, "need a distinctive probe line")
        self.assertIn(needle, render_dashboard(self.items, CONFIG, now=NOW, can_edit=True))
        self.assertNotIn(needle, render_dashboard(self.items, CONFIG, now=NOW, can_edit=False))

    def test_stripping_does_not_mutate_the_original(self):
        from scriptcheck.dashboard import without_briefs

        payload = build_payload(self.items, CONFIG, now=NOW, can_edit=True)
        stripped = without_briefs(payload)
        self.assertFalse(any("brief_text" in r for r in stripped["assignments"]))
        self.assertTrue(any("brief_text" in r for r in payload["assignments"]))

    def test_a_brief_cannot_break_out_of_the_data_block(self):
        from scriptcheck.models import Assignment

        hostile = Assignment(
            thread_id="1",
            thread_name="09-25-26 | VIDEO-001 | Test",
            brief_text='</script><script>alert("x")</script>',
        )
        html = render_dashboard([hostile], CONFIG, now=NOW, can_edit=True)
        self.assertNotIn('</script><script>alert("x")', html)

    def test_the_tab_exists_and_starts_on_the_board(self):
        html = render_dashboard(self.items, CONFIG, now=NOW, can_edit=True)
        self.assertIn('id="tab-briefs"', html)
        self.assertIn('id="tab-briefs-btn"', html)
        self.assertIn('id="tab-board"', html)
        # The wrapper has to carry main's column layout or the sections
        # underneath it all collapse together.
        self.assertIn("#tab-board { display: flex;", html)


class TestBriefGrouping(unittest.TestCase):
    """Briefs sit under a day heading; which day is the user's choice."""

    @classmethod
    def setUpClass(cls):
        items = build_assignments(load_threads(FIXTURE), CONFIG, now=NOW)
        cls.html = render_dashboard(items, CONFIG, now=NOW, can_edit=True)

    def test_due_date_is_the_default_grouping(self):
        self.assertIn('briefGroup: "deadline"', self.html)
        # and it is the first option, so the select shows it unset
        options = re.findall(r'<option value="(\w+)">Group: ([^<]+)</option>', self.html)
        self.assertEqual(options[0], ("deadline", "due date"))

    def test_all_three_groupings_are_offered(self):
        for value in ("deadline", "slate", "forwarded"):
            self.assertIn('<option value="%s">Group:' % value, self.html)
            self.assertRegex(self.html, r"%s:\s*\{ field:" % value)

    def test_each_grouping_reads_the_right_field(self):
        spec = self.html.split("var BRIEF_GROUPS", 1)[1].split("};", 1)[0]
        self.assertIn('field: "deadline"', spec)
        self.assertIn('field: "slate_date"', spec)
        self.assertIn('field: "assigned_at"', spec)

    def test_only_the_inbox_reads_newest_first(self):
        spec = self.html.split("var BRIEF_GROUPS", 1)[1].split("};", 1)[0]
        # A schedule of work reads forwards; only "forwarded" is an inbox.
        self.assertEqual(spec.count("newestFirst: true"), 1)
        self.assertEqual(spec.count("newestFirst: false"), 2)

    def test_a_posting_date_is_bucketed_in_utc_and_the_rest_by_the_viewers_day(self):
        # A posting date is a bare calendar day pinned to midnight UTC, so
        # reading it back in a behind-UTC zone would move every brief a day.
        # A deadline is a real instant and should move with the zone.
        body = self.html.split("function groupBriefs", 1)[1].split("\n  }", 1)[0]
        self.assertIn('mode === "slate" ? date.toISOString().slice(0, 10)', body)
        self.assertIn("dayKey(date)", body)


class TestPastBriefs(unittest.TestCase):
    """Delivered briefs are reference, not work: they sit in a disclosure."""

    @classmethod
    def setUpClass(cls):
        items = build_assignments(load_threads(FIXTURE), CONFIG, now=NOW)
        cls.html = render_dashboard(items, CONFIG, now=NOW, can_edit=True)

    def test_delivered_briefs_are_split_out(self):
        self.assertIn("function isDelivered", self.html)
        self.assertIn("items.filter(isDelivered)", self.html)
        self.assertIn('items.filter(function (i) { return !isDelivered(i); })', self.html)

    def test_it_starts_collapsed(self):
        # No open attribute on the details element.
        block = self.html.split('id="past-briefs"', 1)[1].split(">", 1)[0]
        self.assertNotIn("open", block)

    def test_the_disclosure_outlives_the_list_it_sits_beside(self):
        # #briefs is emptied on every 60s render. A <details> nested inside it
        # would be destroyed and snap shut; it has to be a sibling, with only
        # its inner list rebuilt.
        host = self.html.index('<div class="briefs" id="briefs"></div>')
        details = self.html.index('id="past-briefs"')
        self.assertLess(host, details, "the disclosure must not precede/nest in #briefs")
        self.assertIn('id="past-list"', self.html[details:])
        self.assertIn('renderBriefDays(document.getElementById("past-list")', self.html)

    def test_the_tab_badge_counts_only_what_is_still_open(self):
        self.assertIn('if (open.length) button.appendChild(el("span", "n", String(open.length)))',
                      self.html)

    def test_a_delivered_day_is_not_called_overdue(self):
        # The deadline has passed but nothing is owed, so the past section
        # must not borrow the overdue wording or colour.
        self.assertIn('var owed = grouping.mode === "deadline" && !isPast;', self.html)
        self.assertIn('renderBriefDays(document.getElementById("past-list"), past, now, true)',
                      self.html)


class TestBriefCopy(unittest.TestCase):
    """One click puts the whole forwarded brief on the clipboard."""

    @classmethod
    def setUpClass(cls):
        items = build_assignments(load_threads(FIXTURE), CONFIG, now=NOW)
        cls.html = render_dashboard(items, CONFIG, now=NOW, can_edit=True)

    def test_it_copies_the_whole_brief(self):
        self.assertIn("copyText(item.brief_text)", self.html)

    def test_the_control_is_an_icon_but_still_labelled(self):
        block = self.html.split("function copyButton", 1)[1].split("\n  }", 1)[0]
        self.assertIn('setAttribute("aria-label", "Copy brief")', block)
        self.assertIn('svgIcon("copy")', block)
        # no visible word on the button
        self.assertNotIn('el("button", "brief-copy", ', self.html)

    def test_there_is_a_fallback_outside_a_secure_context(self):
        # navigator.clipboard is undefined on plain http and in older mobile
        # browsers, where the button would otherwise do nothing at all.
        self.assertIn("navigator.clipboard && navigator.clipboard.writeText", self.html)
        self.assertIn('document.execCommand("copy")', self.html)
        # and the scratch textarea is always removed, success or not
        block = self.html.split("function copyText", 1)[1].split("\n  }", 1)[0]
        self.assertEqual(block.count("document.body.removeChild(area)"), 1)
        self.assertLess(block.index("document.body.removeChild(area)"),
                        block.index("if (ok) resolve()"))

    def test_the_outcome_is_announced_not_only_coloured(self):
        self.assertIn('id="live-note"', self.html)
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn("announce(message)", self.html)

    def test_the_page_never_assigns_innerhtml(self):
        # This page renders brief text it did not write. Building every node
        # through textContent/createElement is what keeps that safe, so the
        # icons are built as SVG nodes rather than markup strings.
        for pattern in (r"\.innerHTML\s*=", r"\.outerHTML\s*=", r"insertAdjacentHTML"):
            self.assertIsNone(
                re.search(pattern, self.html),
                "%s writes markup from a string; build nodes instead" % pattern,
            )
        self.assertIn("createElementNS", self.html)
