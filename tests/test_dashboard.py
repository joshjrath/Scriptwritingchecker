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
        for name in ("dateFmt", "timeFmt", "dayFmt", "dayKeyFmt"):
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
