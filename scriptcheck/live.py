"""The real-time daemon: one gateway connection, one small web server.

Discord pushes events, so nothing here polls. A message lands, the affected
thread is re-read, the board is recomputed, and every open browser is updated
over SSE - usually inside a second. A slow periodic resync runs anyway, because
gateway events can be missed during a reconnect and a board that is quietly
wrong is worse than one that is briefly late.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from .alerts import AlertTracker, format_digest
from .audit import render_audit, render_explain
from .config import Config
from .dashboard import render_dashboard
from .models import Attachment, Author, Message, Thread
from .state import BoardState

log = logging.getLogger("scriptcheck.live")

#: Coalesce a burst of messages in one thread into a single refresh.
DEBOUNCE_SECONDS = 1.5

#: Where the access token is remembered once supplied as ?k=...
COOKIE = "scriptcheck"


def _require():
    from .sources.discord_bot import _require_discord

    import aiohttp
    from aiohttp import web

    return _require_discord(), web, aiohttp


class LiveBoard:
    def __init__(self, config: Config, token: str, host: str, port: int):
        self.config = config
        self.token = token
        self.host = host
        self.port = port
        self.state = BoardState(config)
        self.tracker = AlertTracker(
            lead_hours=config.reminder_lead_hours, kinds=config.alert_kinds
        )
        self.subscribers: set = set()
        self.access_token = config.access_token or os.environ.get(
            "SCRIPTCHECK_ACCESS_TOKEN", ""
        )
        self._pending: dict[str, asyncio.Task] = {}
        self.dc, self.web, self.aiohttp = _require()
        self.client = None
        self.started_at = datetime.now(timezone.utc)

    # --- Discord -------------------------------------------------------------

    def _watched(self, thread) -> bool:
        parent = getattr(thread, "parent", None)
        name = getattr(parent, "name", "") or ""
        parent_id = str(getattr(thread, "parent_id", "") or "")
        if self.config.guild_ids:
            guild_id = str(getattr(getattr(thread, "guild", None), "id", ""))
            if guild_id not in {str(g) for g in self.config.guild_ids}:
                return False
        return self.config.channel_matches(name, parent_id)

    async def _read_thread(self, thread) -> Optional[Thread]:
        from .sources.discord_bot import _convert_message

        try:
            messages = [
                _convert_message(m)
                async for m in thread.history(
                    limit=self.config.max_messages_per_thread, oldest_first=True
                )
            ]
        except self.dc.Forbidden:
            log.warning("no access to thread %s", thread.id)
            return None
        parent = getattr(thread, "parent", None)
        guild = getattr(thread, "guild", None)
        return Thread(
            id=str(thread.id),
            name=thread.name,
            guild_id=str(getattr(guild, "id", "")),
            guild_name=getattr(guild, "name", ""),
            parent_id=str(getattr(thread, "parent_id", "") or ""),
            parent_name=getattr(parent, "name", ""),
            created_at=thread.created_at,
            archived=bool(getattr(thread, "archived", False)),
            locked=bool(getattr(thread, "locked", False)),
            tags=[t.name for t in getattr(thread, "applied_tags", [])],
            jump_url=thread.jump_url,
            messages=messages,
        )

    def _dropbox_channel(self, obj):
        """The drop-box channel behind a message, if there is one."""

        if obj is None:
            return None
        if isinstance(obj, self.dc.Thread):
            parent = getattr(obj, "parent", None)
            if parent is not None and self.config.dropbox_matches(
                getattr(parent, "name", ""), str(parent.id)
            ):
                return parent
            return None
        name = getattr(obj, "name", "")
        channel_id = str(getattr(obj, "id", "") or "")
        if self.config.dropbox_matches(name, channel_id):
            return obj
        return None

    def schedule_channel_refresh(self, channel) -> None:
        """Debounced re-read of a drop-box channel."""

        from .sources.discord_bot import collect_dropbox

        key = f"channel:{channel.id}"
        existing = self._pending.pop(key, None)
        if existing:
            existing.cancel()

        async def later():
            try:
                await asyncio.sleep(DEBOUNCE_SECONDS)
                found = await collect_dropbox(
                    channel.guild,
                    channel,
                    self.config,
                    create_threads=self.config.auto_thread,
                )
                for thread in found:
                    self.state.upsert(thread)
                if found:
                    await self.publish()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("drop-box refresh failed for %s", key)
            finally:
                self._pending.pop(key, None)

        self._pending[key] = asyncio.create_task(later())

    def route(self, channel) -> None:
        """Send an event to whichever refresh path owns that channel."""

        dropbox = self._dropbox_channel(channel)
        if dropbox is not None:
            self.schedule_channel_refresh(dropbox)
        elif isinstance(channel, self.dc.Thread):
            self.schedule_refresh(channel)

    def schedule_refresh(self, thread) -> None:
        """Debounced re-read of one thread."""

        if thread is None or not self._watched(thread):
            return
        key = str(thread.id)
        existing = self._pending.pop(key, None)
        if existing:
            existing.cancel()

        async def later():
            try:
                await asyncio.sleep(DEBOUNCE_SECONDS)
                updated = await self._read_thread(thread)
                if updated:
                    self.state.upsert(updated)
                    await self.publish()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("refresh failed for %s", key)
            finally:
                self._pending.pop(key, None)

        self._pending[key] = asyncio.create_task(later())

    async def full_resync(self) -> None:
        from .sources.discord_bot import _collect_threads

        try:
            threads = await _collect_threads(self.client, self.config)
        except Exception:
            log.exception("full resync failed")
            return
        self.state.replace_all(threads)
        log.info("resynced %d threads", len(threads))
        await self.publish()

    # --- fan-out -------------------------------------------------------------

    async def publish(self) -> None:
        payload = self.state.payload()
        data = json.dumps(payload, ensure_ascii=False)
        dead = []
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            self.subscribers.discard(queue)

    async def send_alerts(self, alerts) -> None:
        body = format_digest(alerts)
        url = self.config.webhook_url or os.environ.get("SCRIPTCHECK_WEBHOOK_URL", "")
        if not body:
            return
        log.info("alerting: %s", body.replace("\n", " | ")[:200])
        if not url:
            return
        try:
            async with self.aiohttp.ClientSession() as session:
                await session.post(
                    url,
                    json={
                        "content": body[:1900],
                        "username": "Script Check",
                        "allowed_mentions": {"parse": []},
                    },
                    timeout=self.aiohttp.ClientTimeout(total=20),
                )
        except Exception:
            log.exception("webhook post failed")

    async def tick(self) -> None:
        """Once a minute: let deadlines cross, and push the clock forward."""

        while True:
            try:
                await asyncio.sleep(60)
                now = datetime.now(timezone.utc)
                alerts = self.tracker.scan(self.state.assignments(now), now)
                if alerts:
                    await self.send_alerts(alerts)
                await self.publish()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("tick failed")

    async def resync_loop(self) -> None:
        minutes = max(1, int(self.config.resync_minutes))
        while True:
            try:
                await asyncio.sleep(minutes * 60)
                await self.full_resync()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("resync loop failed")

    # --- HTTP ---------------------------------------------------------------

    async def handle_index(self, request):
        html = render_dashboard(
            self.state.assignments(),
            self.config,
            fetched_at=self.state.last_sync.isoformat() if self.state.last_sync else "",
            live=True,
        )
        return self.web.Response(text=html, content_type="text/html")

    async def handle_report(self, request):
        return self.web.json_response(self.state.payload())

    async def handle_audit(self, request):
        """The parse audit as plain text, readable on a phone."""

        text = render_audit(
            self.state.threads, self.state.assignments(), self.config
        )
        return self.web.Response(text=text, content_type="text/plain", charset="utf-8")

    async def handle_explain(self, request):
        """Full parse trace for one thread: /explain?q=<id or part of the title>."""

        needle = (request.query.get("q") or "").strip()
        if not needle:
            names = "\n  ".join(
                f"{t.id}  {t.name}" for t in sorted(self.state.threads, key=lambda t: t.name)
            )
            body = (
                "Add ?q=<thread id or part of the title> to trace one thread.\n\n"
                f"Threads being watched ({len(self.state.threads)}):\n  {names}\n"
            )
            return self.web.Response(text=body, content_type="text/plain", charset="utf-8")

        lowered = needle.lower()
        matches = [
            t for t in self.state.threads if t.id == needle or lowered in t.name.lower()
        ]
        if not matches:
            return self.web.Response(
                text=f"No thread matches {needle!r}. Open /explain for the list.",
                content_type="text/plain",
                charset="utf-8",
                status=404,
            )
        body = "\n\n".join(
            render_explain(thread, self.config) for thread in matches[:5]
        )
        if len(matches) > 5:
            body += f"\n\n({len(matches) - 5} more matched; narrow the search.)"
        return self.web.Response(text=body, content_type="text/plain", charset="utf-8")

    async def handle_health(self, request):
        ready = bool(self.client and self.client.is_ready())
        body = {
            "ok": ready and self.state.last_sync is not None,
            "gateway_connected": ready,
            "threads": len(self.state.threads),
            "last_sync": self.state.last_sync.isoformat() if self.state.last_sync else None,
            "last_event": self.state.last_event.isoformat() if self.state.last_event else None,
            "started_at": self.started_at.isoformat(),
            "subscribers": len(self.subscribers),
        }
        return self.web.json_response(body, status=200 if body["ok"] else 503)

    async def handle_events(self, request):
        response = self.web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
        await response.prepare(request)
        queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        self.subscribers.add(queue)
        try:
            await response.write(
                b"event: board\ndata: "
                + json.dumps(self.state.payload(), ensure_ascii=False).encode()
                + b"\n\n"
            )
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=25)
                    chunk = b"event: board\ndata: " + data.encode() + b"\n\n"
                except asyncio.TimeoutError:
                    chunk = b": keep-alive\n\n"  # keeps proxies from hanging up
                await response.write(chunk)
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            self.subscribers.discard(queue)
        return response

    def _auth_middleware(self):
        web = self.web

        @web.middleware
        async def guard(request, handler):
            if not self.access_token:
                return await handler(request)
            # Health probes must work without the secret, and they expose
            # nothing but liveness.
            if request.path == "/healthz":
                return await handler(request)
            supplied = request.query.get("k") or request.cookies.get(COOKIE)
            if supplied != self.access_token:
                # Say "not found" rather than "forbidden": an unauthenticated
                # visitor learns nothing about what is here.
                return web.Response(status=404, text="Not found")
            response = await handler(request)
            if request.query.get("k") and not response.prepared:
                response.set_cookie(
                    COOKIE,
                    self.access_token,
                    httponly=True,
                    samesite="Lax",
                    max_age=60 * 60 * 24 * 365,
                )
            return response

        return guard

    def build_app(self):
        app = self.web.Application(middlewares=[self._auth_middleware()])
        app.router.add_get("/", self.handle_index)
        app.router.add_get("/report.json", self.handle_report)
        app.router.add_get("/audit", self.handle_audit)
        app.router.add_get("/explain", self.handle_explain)
        app.router.add_get("/events", self.handle_events)
        app.router.add_get("/healthz", self.handle_health)
        return app

    # --- wiring --------------------------------------------------------------

    def build_client(self):
        intents = self.dc.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.guild_messages = True
        client = self.dc.Client(intents=intents)

        @client.event
        async def on_ready():
            log.info("connected as %s", client.user)
            await self.full_resync()
            now = datetime.now(timezone.utc)
            self.tracker.prime(self.state.assignments(now), now)

        @client.event
        async def on_message(message):
            self.route(message.channel)

        @client.event
        async def on_message_edit(before, after):
            self.route(after.channel)

        @client.event
        async def on_message_delete(message):
            self.route(message.channel)

        @client.event
        async def on_thread_create(thread):
            self.route(thread)

        @client.event
        async def on_thread_update(before, after):
            self.route(after)

        @client.event
        async def on_thread_delete(thread):
            if self.state.remove(str(thread.id)):
                await self.publish()

        return client

    async def run(self) -> None:
        self.client = self.build_client()
        app = self.build_app()
        runner = self.web.AppRunner(app)
        await runner.setup()
        site = self.web.TCPSite(runner, self.host, self.port)
        await site.start()
        if self.access_token:
            log.info("board on http://%s:%s/?k=<your token>", self.host, self.port)
        else:
            log.warning(
                "board on http://%s:%s - NO ACCESS TOKEN SET, anyone with the URL "
                "can read your assignments. Set SCRIPTCHECK_ACCESS_TOKEN.",
                self.host,
                self.port,
            )

        tasks = [
            asyncio.create_task(self.client.start(self.token)),
            asyncio.create_task(self.tick()),
            asyncio.create_task(self.resync_loop()),
        ]
        try:
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_EXCEPTION
            )
            for task in done:
                task.result()  # re-raise whatever stopped us
        finally:
            for task in tasks:
                task.cancel()
            await self.client.close()
            await runner.cleanup()


def serve(config: Config, token: Optional[str] = None, host: str = "", port: int = 0) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )
    token = token or os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("No bot token. Set DISCORD_BOT_TOKEN or pass --token.")
    if (
        not config.channel_ids
        and not config.channel_name_patterns
        and not config.dropbox_channel_patterns
    ):
        logging.getLogger("scriptcheck.live").warning(
            "No channel_ids or channel_name_patterns set, so every channel in "
            "the server will be read. Set channel_name_patterns (e.g. "
            '["assignments", "workflow"]) to keep this fast and quiet.'
        )
    board = LiveBoard(
        config,
        token,
        host or config.serve_host,
        int(port or os.environ.get("PORT") or config.serve_port),
    )
    try:
        asyncio.run(board.run())
    except KeyboardInterrupt:
        return 0
    return 0
