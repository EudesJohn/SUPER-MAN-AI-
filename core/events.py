"""Event bus: in-process pub/sub with a bounded journal.

Event sourcing (section 28): every significant action is recorded so the
reasoning history can be replayed. For the MVP everything is in-process;
the interface is deliberately simple to swap for Redis Streams later.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

from core.models import EventKind, utc_now_iso

logger = logging.getLogger(__name__)

MAX_JOURNAL = 10_000


class EventBus:
    """Publish/subscribe with a bounded in-memory journal.

    Subscribers are async callables receiving (kind, payload, meta).
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[str, dict, dict], Awaitable[None]]]] = defaultdict(list)
        self.journal: list[dict[str, Any]] = []
        # Optional synchronous sink for every event (used for persistence).
        self.persist_hook: Callable[[dict[str, Any]], None] | None = None

    def subscribe(self, kind: str | EventKind, handler: Callable[[str, dict, dict], Awaitable[None]]) -> None:
        key = kind.value if isinstance(kind, EventKind) else kind
        self._subscribers[key].append(handler)

    async def publish(self, kind: str | EventKind, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        key = kind.value if isinstance(kind, EventKind) else kind
        event = {"kind": key, "payload": payload or {}, "timestamp": utc_now_iso()}
        self.journal.append(event)
        if len(self.journal) > MAX_JOURNAL:
            del self.journal[: len(self.journal) - MAX_JOURNAL]
        if self.persist_hook is not None:
            try:
                self.persist_hook(event)
            except Exception:  # noqa: BLE001 - persistence must not break publishing
                logger.exception("event persist hook failed for kind=%s", key)
        for handler in self._subscribers.get(key, []):
            try:
                await handler(key, event["payload"], event)
            except Exception:  # noqa: BLE001 - subscriber errors must not break publishers
                logger.exception("event subscriber failed for kind=%s", key)
        return event

    def publish_sync(self, kind: str | EventKind, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Synchronous publish for sync callers (e.g. CalculationEngine.run).

        Journal and persistence happen immediately; async subscribers are
        scheduled on the running loop when one exists.
        """
        key = kind.value if isinstance(kind, EventKind) else kind
        event = {"kind": key, "payload": payload or {}, "timestamp": utc_now_iso()}
        self.journal.append(event)
        if len(self.journal) > MAX_JOURNAL:
            del self.journal[: len(self.journal) - MAX_JOURNAL]
        if self.persist_hook is not None:
            try:
                self.persist_hook(event)
            except Exception:  # noqa: BLE001
                logger.exception("event persist hook failed for kind=%s", key)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        for handler in self._subscribers.get(key, []):
            if loop is not None:
                loop.create_task(self._safe_notify(handler, key, event))
        return event

    @staticmethod
    async def _safe_notify(handler: Callable[[str, dict, dict], Awaitable[None]], key: str, event: dict) -> None:
        try:
            await handler(key, event["payload"], event)
        except Exception:  # noqa: BLE001
            logger.exception("event subscriber failed for kind=%s", key)

    def recent(self, n: int = 50) -> list[dict[str, Any]]:
        return self.journal[-n:]
