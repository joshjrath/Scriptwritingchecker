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
