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
