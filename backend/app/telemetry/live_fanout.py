"""
Thread-safe fanout from the Paho MQTT consumer thread to asyncio SSE generators.

Paho runs its own thread (client.loop_start).  FastAPI handlers live on
asyncio.  The two cannot share an asyncio.Queue directly.

Pattern used here:
  - call set_event_loop() once from the FastAPI lifespan (on the asyncio thread)
  - call fanout() from the Paho consumer thread
  - fanout() uses loop.call_soon_threadsafe() to safely put items on each
    subscriber's asyncio.Queue without crossing the thread boundary unsafely
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Set once from the asyncio thread during lifespan startup
_loop: asyncio.AbstractEventLoop | None = None

# All active SSE subscriber queues (manipulated only from asyncio thread via
# call_soon_threadsafe, so no lock needed for _subscribers itself)
_subscribers: set[asyncio.Queue] = set()


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Register the running asyncio event loop. Call from lifespan on startup."""
    global _loop
    _loop = loop


def fanout(payload: dict[str, Any]) -> None:
    """
    Broadcast a payload to every active SSE subscriber.
    Safe to call from any thread (including the Paho MQTT consumer thread).
    Drops the message for any subscriber whose queue is full rather than
    blocking the MQTT ingest pipeline.
    """
    loop = _loop
    if loop is None or not loop.is_running():
        return

    def _put_all() -> None:
        dead: set[asyncio.Queue] = set()
        for q in list(_subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.add(q)
        _subscribers.difference_update(dead)

    loop.call_soon_threadsafe(_put_all)


def subscribe() -> asyncio.Queue:
    """
    Create and register a new subscriber queue.
    Must be called from the asyncio thread (i.e., inside a FastAPI endpoint).
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Remove a subscriber queue. Safe to call from asyncio (e.g., generator finally)."""
    _subscribers.discard(q)

