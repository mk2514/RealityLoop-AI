"""
Server-Sent Events endpoint for live sensor readings.

GET /api/v1/live/stream

- Requires a valid session cookie (same as all session_router endpoints).
- Streams newline-delimited text/event-stream events.
- Each event is a JSON object with at minimum:
    { "sensor_id": "...", "machine_id": "...", "organization_id": "...",
      "value": 0.0, "unit": "...", "quantity": "...",
      "event_time_utc": "...", "received_at_utc": "..." }
- A keepalive comment (": keepalive") is sent every 20 s when no data arrives.
- The browser EventSource API reconnects automatically on disconnect.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.routes.auth import Principal, get_current_principal
from app.telemetry.live_fanout import subscribe, unsubscribe

router = APIRouter()
logger = logging.getLogger(__name__)

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",        # disable nginx buffering
    "Connection": "keep-alive",
}


@router.get("/live/stream")
async def sse_live_stream(
    principal: Principal = Depends(get_current_principal),
) -> StreamingResponse:
    """
    Stream live sensor readings for the authenticated organization as SSE.

    The client connects with credentials (the session cookie is sent
    automatically by EventSource when withCredentials=true).  Each event
    is filtered to the caller's organization_id before being emitted so
    that readings from other organizations are never exposed.
    """
    org_id = str(principal.organization_id)
    q = subscribe()

    async def generate():
        try:
            while True:
                try:
                    data: dict = await asyncio.wait_for(q.get(), timeout=20.0)
                    # Only emit readings that belong to this organization
                    if data.get("organization_id") != org_id:
                        continue
                    yield f"data: {json.dumps(data, separators=(',', ':'))}\n\n"
                except asyncio.TimeoutError:
                    # Send a keepalive comment so proxies don't close the connection
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )

