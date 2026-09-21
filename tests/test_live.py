"""The daemon's HTTP surface and state store, exercised without Discord."""

import asyncio
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from scriptcheck.config import Config
from scriptcheck.live import LiveBoard
from scriptcheck.models import Status, Thread
from scriptcheck.sources.export_json import load_threads
from scriptcheck.state import BoardState

FIXTURE = Path(__file__).parent / "fixtures" / "sample_threads.json"
NOW = datetime(2026, 9, 20, 19, 30, tzinfo=timezone.utc)
CONFIG = Config(
    my_user_ids=["111111111111111111"],
    my_roles=["SCRIPT"],
    display_timezone="America/New_York",
    overrides_file="/nonexistent-overrides.json",
)


class TestBoardState(unittest.TestCase):
    def setUp(self):
        self.state = BoardState(CONFIG)
        self.state.replace_all(load_threads(FIXTURE))

    def test_replace_all_records_a_sync_time(self):
        self.assertIsNotNone(self.state.last_sync)
        self.assertEqual(len(self.state.threads), 8)

    def test_assignments_are_derived_fresh(self):
        items = self.state.assignments(NOW)
        self.assertEqual(len(items), 7)
        self.assertEqual(items[0].status, Status.OVERDUE)

    def test_upsert_replaces_a_thread_and_changes_the_verdict(self):
        before = self.state.by_id(NOW)["1003"]
        self.assertEqual(before.status, Status.OVERDUE)

        thread = self.state.get("1003")
        thread.messages.append(
            type(thread.messages[0]).from_dict(
                {
                    "id": "7777",
                    "author": {"id": "111111111111111111", "display_name": "Josh"},
                    "content": "done: https://docs.google.com/document/d/x/edit",
                    "created_at": "2026-09-18T10:00:00+00:00",
                }
            )
        )
        self.state.upsert(thread)

        after = self.state.by_id(NOW)["1003"]
        self.assertEqual(after.status, Status.SUBMITTED)
        self.assertIsNotNone(self.state.last_event)

    def test_remove(self):
        self.assertTrue(self.state.remove("1001"))
        self.assertFalse(self.state.remove("1001"))
        self.assertFalse(self.state.knows("1001"))

    def test_payload_is_marked_live(self):
        payload = self.state.payload(NOW)
        self.assertTrue(payload["live"])
        self.assertEqual(payload["thread_count"], 8)
        self.assertTrue(payload["fetched_at"])

    def test_a_broken_overrides_file_does_not_take_the_board_down(self):
        config = Config(overrides_file=str(FIXTURE))  # valid JSON, wrong shape
        state = BoardState(config)
        self.assertEqual(state.overrides, {})


class TestHttpSurface(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.board = LiveBoard(CONFIG, token="x", host="127.0.0.1", port=0)
        self.client = TestClient(TestServer(self.board.build_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_health_is_503_until_the_first_sync(self):
        response = await self.client.get("/healthz")
        self.assertEqual(response.status, 503)
        body = await response.json()
        self.assertFalse(body["ok"])
        self.assertFalse(body["gateway_connected"])

    async def test_health_is_200_once_synced(self):
        self.board.state.replace_all(load_threads(FIXTURE))
        # is_ready() is what the gateway would provide; stand in for it.
        self.board.client = type("C", (), {"is_ready": staticmethod(lambda: True)})()
        response = await self.client.get("/healthz")
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["threads"], 8)

    async def test_report_json_carries_the_assignments(self):
        self.board.state.replace_all(load_threads(FIXTURE))
        response = await self.client.get("/report.json")
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(len(payload["assignments"]), 7)
        self.assertTrue(payload["live"])

    async def test_index_serves_the_board_in_live_mode(self):
        self.board.state.replace_all(load_threads(FIXTURE))
        response = await self.client.get("/")
        self.assertEqual(response.status, 200)
        html = await response.text()
        self.assertIn("<title>Script Board</title>", html)
        self.assertIn('"live": true', html.replace('"live":true', '"live": true'))

    async def test_the_event_stream_opens_with_the_current_board(self):
        self.board.state.replace_all(load_threads(FIXTURE))
        response = await self.client.get("/events")
        self.assertEqual(response.status, 200)
        self.assertIn("text/event-stream", response.headers["Content-Type"])

        chunk = await asyncio.wait_for(response.content.readuntil(b"\n\n"), timeout=5)
        text = chunk.decode()
        self.assertTrue(text.startswith("event: board\ndata: "))
        payload = json.loads(text.split("data: ", 1)[1].strip())
        self.assertEqual(len(payload["assignments"]), 7)
        response.close()

    async def test_a_publish_reaches_an_open_stream(self):
        self.board.state.replace_all(load_threads(FIXTURE))
        response = await self.client.get("/events")
        await asyncio.wait_for(response.content.readuntil(b"\n\n"), timeout=5)

        # Drop a thread, then push: the stream should carry the new board.
        self.board.state.remove("1001")
        await self.board.publish()

        chunk = await asyncio.wait_for(response.content.readuntil(b"\n\n"), timeout=5)
        payload = json.loads(chunk.decode().split("data: ", 1)[1].strip())
        self.assertEqual(len(payload["assignments"]), 6)
        response.close()

    async def test_subscribers_are_released_when_a_client_leaves(self):
        response = await self.client.get("/events")
        await asyncio.wait_for(response.content.readuntil(b"\n\n"), timeout=5)
        self.assertEqual(len(self.board.subscribers), 1)
        response.close()
        await asyncio.sleep(0.1)
        await self.board.publish()
        await asyncio.sleep(0.1)
        self.assertEqual(len(self.board.subscribers), 0)


if __name__ == "__main__":
    unittest.main()


class TestAccessToken(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        config = Config(
            my_user_ids=["111111111111111111"],
            my_roles=["SCRIPT"],
            access_token="s3cret",
            overrides_file="/nonexistent-overrides.json",
        )
        self.board = LiveBoard(config, token="x", host="127.0.0.1", port=0)
        self.board.state.replace_all(load_threads(FIXTURE))
        self.client = TestClient(TestServer(self.board.build_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_no_token_looks_like_nothing_is_there(self):
        response = await self.client.get("/")
        self.assertEqual(response.status, 404)

    async def test_a_wrong_token_is_refused(self):
        self.assertEqual((await self.client.get("/?k=nope")).status, 404)
        self.assertEqual((await self.client.get("/report.json?k=nope")).status, 404)

    async def test_the_right_token_opens_it_and_is_remembered(self):
        response = await self.client.get("/?k=s3cret")
        self.assertEqual(response.status, 200)
        self.assertIn("scriptcheck", response.cookies)
        # The cookie carries the later requests, including the event stream.
        self.assertEqual((await self.client.get("/report.json")).status, 200)
        stream = await self.client.get("/events")
        self.assertEqual(stream.status, 200)
        stream.close()

    async def test_health_probes_stay_open(self):
        self.assertIn((await self.client.get("/healthz")).status, (200, 503))


class TestDiagnosticRoutes(unittest.IsolatedAsyncioTestCase):
    """Calibration has to be possible from a phone, not just a terminal."""

    async def asyncSetUp(self):
        self.board = LiveBoard(CONFIG, token="x", host="127.0.0.1", port=0)
        self.board.state.replace_all(load_threads(FIXTURE))
        self.client = TestClient(TestServer(self.board.build_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_audit_renders_as_plain_text(self):
        response = await self.client.get("/audit")
        self.assertEqual(response.status, 200)
        self.assertIn("text/plain", response.headers["Content-Type"])
        text = await response.text()
        self.assertIn("PARSE AUDIT", text)
        self.assertIn("Needs a human look", text)

    async def test_explain_without_a_query_lists_the_threads(self):
        text = await (await self.client.get("/explain")).text()
        self.assertIn("1001", text)
        self.assertIn("What If Sans Remembered Every RESET?", text)

    async def test_explain_traces_a_thread_by_title(self):
        text = await (await self.client.get("/explain?q=Sans")).text()
        self.assertIn("9/20/2026 @ 11:59 PM ET", text)
        self.assertIn("OPENING POST AS FETCHED", text)

    async def test_explain_traces_a_thread_by_id(self):
        text = await (await self.client.get("/explain?q=1007")).text()
        self.assertIn("Gojo", text)
        self.assertIn("NOT FOUND", text)

    async def test_a_miss_says_so(self):
        response = await self.client.get("/explain?q=nothing-like-this")
        self.assertEqual(response.status, 404)
        self.assertIn("No thread matches", await response.text())

    async def test_the_diagnostics_are_behind_the_access_token(self):
        config = Config(access_token="s3cret", overrides_file="/nonexistent-overrides.json")
        board = LiveBoard(config, token="x", host="127.0.0.1", port=0)
        board.state.replace_all(load_threads(FIXTURE))
        client = TestClient(TestServer(board.build_app()))
        await client.start_server()
        try:
            self.assertEqual((await client.get("/audit")).status, 404)
            self.assertEqual((await client.get("/explain?q=Sans")).status, 404)
            self.assertEqual((await client.get("/audit?k=s3cret")).status, 200)
        finally:
            await client.close()


class TestMarkDelivered(unittest.IsolatedAsyncioTestCase):
    """Drop-box mode delivers where the bot cannot see, so you say so here."""

    async def asyncSetUp(self):
        import tempfile

        self.overrides = Path(tempfile.mkdtemp()) / "overrides.json"
        config = Config(
            my_user_ids=["111111111111111111"],
            my_roles=["SCRIPT"],
            display_timezone="America/New_York",
            overrides_file=str(self.overrides),
        )
        self.board = LiveBoard(config, token="x", host="127.0.0.1", port=0)
        self.board.state.replace_all(load_threads(FIXTURE))
        self.client = TestClient(TestServer(self.board.build_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    def status_of(self, thread_id):
        return self.board.state.by_id(NOW)[thread_id].status

    async def test_marking_flips_the_status_and_persists(self):
        self.assertEqual(self.status_of("1003"), Status.OVERDUE)

        response = await self.client.post("/mark", json={"thread_id": "1003"})
        self.assertEqual(response.status, 200)
        self.assertTrue((await response.json())["ok"])

        self.assertTrue(self.board.state.by_id(NOW)["1003"].status.is_submitted)
        # Written to disk, so a restart keeps it.
        self.assertIn("1003", json.loads(self.overrides.read_text()))

    async def test_a_link_can_be_recorded_with_it(self):
        await self.client.post(
            "/mark", json={"thread_id": "1003", "link": "https://drive.google.com/x"}
        )
        assignment = self.board.state.by_id(NOW)["1003"]
        self.assertEqual(assignment.submissions[0].links, ["https://drive.google.com/x"])

    async def test_undo_puts_it_back(self):
        await self.client.post("/mark", json={"thread_id": "1003"})
        self.assertTrue(self.board.state.by_id(NOW)["1003"].status.is_submitted)

        response = await self.client.post("/mark", json={"thread_id": "1003", "undo": True})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.status_of("1003"), Status.OVERDUE)
        self.assertEqual(json.loads(self.overrides.read_text()), {})

    async def test_marking_is_visible_as_a_hand_correction(self):
        await self.client.post("/mark", json={"thread_id": "1003"})
        assignment = self.board.state.by_id(NOW)["1003"]
        self.assertIn("delivered_at", assignment.overridden)
        self.assertTrue(any("Corrected by hand" in w for w in assignment.warnings))

    async def test_an_unknown_thread_is_refused(self):
        response = await self.client.post("/mark", json={"thread_id": "does-not-exist"})
        self.assertEqual(response.status, 404)

    async def test_a_missing_thread_id_is_refused(self):
        self.assertEqual((await self.client.post("/mark", json={})).status, 400)

    async def test_junk_is_refused(self):
        response = await self.client.post(
            "/mark", data=b"not json", headers={"Content-Type": "application/json"}
        )
        self.assertEqual(response.status, 400)

    async def test_an_unwritable_path_explains_itself(self):
        self.board.config.overrides_file = "/proc/cannot/write/here.json"
        response = await self.client.post("/mark", json={"thread_id": "1003"})
        self.assertEqual(response.status, 500)
        self.assertIn("volume", (await response.json())["error"])

    async def test_marking_pushes_the_new_board_to_open_clients(self):
        stream = await self.client.get("/events")
        await asyncio.wait_for(stream.content.readuntil(b"\n\n"), timeout=5)

        await self.client.post("/mark", json={"thread_id": "1003"})

        chunk = await asyncio.wait_for(stream.content.readuntil(b"\n\n"), timeout=5)
        payload = json.loads(chunk.decode().split("data: ", 1)[1].strip())
        row = [a for a in payload["assignments"] if a["thread_id"] == "1003"][0]
        self.assertIn("delivered_at", row["overridden"])
        stream.close()

    async def test_marking_needs_the_access_token_too(self):
        config = Config(access_token="s3cret", overrides_file=str(self.overrides))
        board = LiveBoard(config, token="x", host="127.0.0.1", port=0)
        board.state.replace_all(load_threads(FIXTURE))
        client = TestClient(TestServer(board.build_app()))
        await client.start_server()
        try:
            self.assertEqual((await client.post("/mark", json={"thread_id": "1003"})).status, 404)
        finally:
            await client.close()


class TestShareLink(unittest.IsolatedAsyncioTestCase):
    """A view token lets the team look without touching anything."""

    async def asyncSetUp(self):
        import tempfile

        self.overrides = Path(tempfile.mkdtemp()) / "overrides.json"
        config = Config(
            my_user_ids=["111111111111111111"],
            my_roles=["SCRIPT"],
            access_token="owner-secret",
            view_token="team-link",
            overrides_file=str(self.overrides),
        )
        self.board = LiveBoard(config, token="x", host="127.0.0.1", port=0)
        self.board.state.replace_all(load_threads(FIXTURE))
        self.client = TestClient(TestServer(self.board.build_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_the_view_token_opens_the_board(self):
        response = await self.client.get("/?k=team-link")
        self.assertEqual(response.status, 200)
        self.assertIn("Script Board", await response.text())

    async def test_a_viewer_cannot_mark_anything_delivered(self):
        response = await self.client.post(
            "/mark?k=team-link", json={"thread_id": "1003"}
        )
        self.assertEqual(response.status, 404)
        self.assertFalse(self.overrides.exists())

    async def test_a_viewer_cannot_read_the_briefs_back_in_full(self):
        # /audit and /explain quote the whole opening post.
        self.assertEqual((await self.client.get("/audit?k=team-link")).status, 404)
        self.assertEqual((await self.client.get("/explain?k=team-link&q=Sans")).status, 404)

    async def test_the_owner_keeps_everything(self):
        self.assertEqual((await self.client.get("/audit?k=owner-secret")).status, 200)
        response = await self.client.post(
            "/mark?k=owner-secret", json={"thread_id": "1003"}
        )
        self.assertEqual(response.status, 200)

    async def test_the_payload_says_which_role_it_is_for(self):
        owner = await (await self.client.get("/report.json?k=owner-secret")).json()
        self.assertTrue(owner["can_edit"])
        viewer = await (await self.client.get("/report.json?k=team-link")).json()
        self.assertFalse(viewer["can_edit"])
        # Same assignments either way; only the permissions differ.
        self.assertEqual(len(owner["assignments"]), len(viewer["assignments"]))

    async def test_a_pushed_update_keeps_each_stream_in_its_own_role(self):
        viewer = await self.client.get("/events?k=team-link")
        first = await asyncio.wait_for(viewer.content.readuntil(b"\n\n"), timeout=5)
        self.assertFalse(json.loads(first.decode().split("data: ", 1)[1])["can_edit"])

        self.board.state.remove("1001")
        await self.board.publish()

        pushed = await asyncio.wait_for(viewer.content.readuntil(b"\n\n"), timeout=5)
        payload = json.loads(pushed.decode().split("data: ", 1)[1])
        self.assertFalse(payload["can_edit"], "a viewer must not be handed edit rights")
        self.assertEqual(len(payload["assignments"]), 6)
        viewer.close()

    async def test_a_wrong_token_still_reveals_nothing(self):
        self.assertEqual((await self.client.get("/?k=guessing")).status, 404)
        self.assertEqual((await self.client.get("/")).status, 404)


class TestFavicon(unittest.IsolatedAsyncioTestCase):
    async def test_the_tab_icon_does_not_log_a_404(self):
        board = LiveBoard(CONFIG, token="x", host="127.0.0.1", port=0)
        client = TestClient(TestServer(board.build_app()))
        await client.start_server()
        try:
            self.assertEqual((await client.get("/favicon.ico")).status, 204)
        finally:
            await client.close()

    async def test_it_is_answered_even_behind_a_token(self):
        config = Config(access_token="s3cret", overrides_file="/nonexistent-overrides.json")
        board = LiveBoard(config, token="x", host="127.0.0.1", port=0)
        client = TestClient(TestServer(board.build_app()))
        await client.start_server()
        try:
            # The browser asks for it without the token in the URL.
            self.assertEqual((await client.get("/favicon.ico")).status, 204)
            self.assertEqual((await client.get("/")).status, 404)
        finally:
            await client.close()


class TestMarkResponseCarriesTheBoard(unittest.IsolatedAsyncioTestCase):
    """The clicking page must update from the reply, not from the stream."""

    async def asyncSetUp(self):
        import tempfile

        config = Config(
            my_user_ids=["111111111111111111"],
            my_roles=["SCRIPT"],
            overrides_file=str(Path(tempfile.mkdtemp()) / "overrides.json"),
        )
        self.board = LiveBoard(config, token="x", host="127.0.0.1", port=0)
        self.board.state.replace_all(load_threads(FIXTURE))
        self.client = TestClient(TestServer(self.board.build_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_the_reply_contains_the_updated_row(self):
        response = await self.client.post("/mark", json={"thread_id": "1003"})
        body = await response.json()
        self.assertIn("board", body)
        row = [a for a in body["board"]["assignments"] if a["thread_id"] == "1003"][0]
        self.assertIn("delivered_at", row["overridden"])
        self.assertTrue(row["submissions"])

    async def test_undo_is_reflected_in_its_own_reply(self):
        await self.client.post("/mark", json={"thread_id": "1003"})
        body = await (await self.client.post(
            "/mark", json={"thread_id": "1003", "undo": True}
        )).json()
        row = [a for a in body["board"]["assignments"] if a["thread_id"] == "1003"][0]
        self.assertEqual(row["overridden"], [])
        self.assertEqual(row["submissions"], [])
        self.assertEqual(row["status"], "OVERDUE")

    async def test_the_reply_respects_the_viewer_role(self):
        config = Config(
            access_token="mine",
            view_token="theirs",
            my_roles=["SCRIPT"],
            overrides_file=self.board.config.overrides_file,
        )
        board = LiveBoard(config, token="x", host="127.0.0.1", port=0)
        board.state.replace_all(load_threads(FIXTURE))
        client = TestClient(TestServer(board.build_app()))
        await client.start_server()
        try:
            body = await (await client.post(
                "/mark?k=mine", json={"thread_id": "1003"}
            )).json()
            self.assertTrue(body["board"]["can_edit"])
        finally:
            await client.close()
