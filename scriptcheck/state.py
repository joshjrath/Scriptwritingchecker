"""In-memory board state, updated by gateway events.

The daemon keeps raw threads here and re-derives assignments on demand, so a
single incoming message never has to be reconciled against a cached verdict -
the verdict is just recomputed. At a few hundred threads that is microseconds
and removes a whole class of staleness bug.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Iterable, Optional

from .config import Config
from .dashboard import build_payload
from .engine import build_assignments
from .models import Assignment, Thread
from .overrides import load as load_overrides


class BoardState:
    def __init__(self, config: Config):
        self.config = config
        self._threads: dict[str, Thread] = {}
        self._lock = threading.RLock()
        self.last_sync: Optional[datetime] = None
        self.last_event: Optional[datetime] = None
        self.overrides: dict = {}
        self.reload_overrides()

    # --- mutation ------------------------------------------------------------

    def reload_overrides(self) -> None:
        try:
            self.overrides = load_overrides(self.config.overrides_file)
        except (ValueError, OSError):
            # A malformed overrides file must not take the daemon down; the
            # board keeps running on parsed values alone.
            self.overrides = {}

    def replace_all(self, threads: Iterable[Thread]) -> None:
        with self._lock:
            self._threads = {t.id: t for t in threads}
            self.last_sync = datetime.now(timezone.utc)
        self.reload_overrides()

    def upsert(self, thread: Thread) -> None:
        with self._lock:
            self._threads[thread.id] = thread
            self.last_event = datetime.now(timezone.utc)

    def remove(self, thread_id: str) -> bool:
        with self._lock:
            existed = self._threads.pop(str(thread_id), None) is not None
            if existed:
                self.last_event = datetime.now(timezone.utc)
            return existed

    def get(self, thread_id: str) -> Optional[Thread]:
        with self._lock:
            return self._threads.get(str(thread_id))

    def knows(self, thread_id: str) -> bool:
        with self._lock:
            return str(thread_id) in self._threads

    # --- derivation ----------------------------------------------------------

    @property
    def threads(self) -> list[Thread]:
        with self._lock:
            return list(self._threads.values())

    def assignments(
        self, now: Optional[datetime] = None, include_all: bool = False
    ) -> list[Assignment]:
        return build_assignments(
            self.threads,
            self.config,
            now=now or datetime.now(timezone.utc),
            include_all=include_all,
            overrides=self.overrides,
        )

    def by_id(self, now: Optional[datetime] = None) -> dict[str, Assignment]:
        return {a.thread_id: a for a in self.assignments(now, include_all=True)}

    def payload(self, now: Optional[datetime] = None, banner: str = "") -> dict:
        now = now or datetime.now(timezone.utc)
        data = build_payload(
            self.assignments(now),
            self.config,
            now=now,
            fetched_at=self.last_sync.isoformat() if self.last_sync else "",
            banner=banner,
        )
        data["live"] = True
        data["last_event"] = self.last_event.isoformat() if self.last_event else ""
        data["thread_count"] = len(self._threads)
        return data
