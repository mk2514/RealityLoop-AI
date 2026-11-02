import argparse
import asyncio
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from asyncua import Client
from asyncua.ua.uaerrors import UaError

from app.core.config import get_settings
from app.telemetry.edge_buffer import DurableEdgeBuffer, RestEdgePublisher

logger = logging.getLogger(__name__)


class ReadOnlyOpcUaClient(Protocol):
    async def connect(self) -> None: ...

    async def read_data_value(self, node_id: str) -> Any: ...

    async def disconnect(self) -> None: ...


@dataclass(frozen=True)
class OpcUaSensorMap:
    node_id: str
    sensor_id: str
    unit: str
    scale: float
    offset: float

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "OpcUaSensorMap":
        required = {"node_id", "sensor_id", "unit", "scale", "offset"}
        if set(value) != required:
            raise ValueError(
                "Each OPC UA mapping must explicitly provide node_id, sensor_id, unit, scale, and offset."
            )
        if not all(isinstance(value[key], str) and value[key] for key in ("node_id", "sensor_id", "unit")):
            raise ValueError("OPC UA node, sensor, and unit mappings must be non-empty strings.")
        scale = value["scale"]
        offset = value["offset"]
        if (
            isinstance(scale, bool)
            or isinstance(offset, bool)
            or not isinstance(scale, (int, float))
            or not isinstance(offset, (int, float))
            or not math.isfinite(float(scale))
            or not math.isfinite(float(offset))
        ):
            raise ValueError("OPC UA scale and offset must be finite numeric values.")
        return cls(
            node_id=value["node_id"],
            sensor_id=value["sensor_id"],
            unit=value["unit"],
            scale=float(scale),
            offset=float(offset),
        )


def _utc_timestamp(value: datetime | None) -> str:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("OPC UA DataValue has no timezone-aware source or server timestamp.")
    return value.astimezone(UTC).isoformat()


def _quality(status_code: Any) -> str:
    name = getattr(status_code, "name", None)
    if not isinstance(name, str):
        raise ValueError("OPC UA DataValue has no recognized quality code.")
    if name.startswith("Good"):
        return "good"
    if name.startswith("Uncertain"):
        return "uncertain"
    if name.startswith("Bad"):
        return "bad"
    raise ValueError(f"Unrecognized OPC UA quality code {name!r}.")


def mapped_reading(
    sensor_map: OpcUaSensorMap,
    data_value: Any,
) -> dict[str, Any]:
    variant = getattr(data_value, "Value", None)
    raw = getattr(variant, "Value", None)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        raise ValueError("OPC UA node value must be finite numeric data.")
    source_time = getattr(data_value, "SourceTimestamp", None)
    server_time = getattr(data_value, "ServerTimestamp", None)
    event_time = _utc_timestamp(source_time or server_time)
    quality = _quality(getattr(data_value, "StatusCode", None))
    return {
        "sensor_id": sensor_map.sensor_id,
        "value": float(raw) * sensor_map.scale + sensor_map.offset,
        "unit": sensor_map.unit,
        "event_time_utc": event_time,
        "quality": quality,
        "source_event_id": f"opcua:{sensor_map.node_id}:{event_time}",
    }


class AsyncUaReadOnlyAdapter:
    def __init__(
        self,
        endpoint: str,
        *,
        certificate_file: str,
        private_key_file: str,
    ) -> None:
        if not endpoint.startswith("opc.tcp://"):
            raise ValueError("OPC UA endpoint must use opc.tcp://.")
        if not certificate_file or not private_key_file:
            raise ValueError("OPC UA SignAndEncrypt certificate and private key are required.")
        self._client = Client(endpoint)
        self._certificate_file = certificate_file
        self._private_key_file = private_key_file

    async def connect(self) -> None:
        await self._client.set_security_string(
            f"Basic256Sha256,SignAndEncrypt,{self._certificate_file},{self._private_key_file}"
        )
        await self._client.connect()

    async def read_data_value(self, node_id: str) -> Any:
        return await self._client.get_node(node_id).read_data_value()

    async def disconnect(self) -> None:
        await self._client.disconnect()


async def run_publisher(
    client: ReadOnlyOpcUaClient,
    mappings: list[OpcUaSensorMap],
    buffer: DurableEdgeBuffer,
    publisher: RestEdgePublisher,
    poll_interval_seconds: float,
) -> None:
    if poll_interval_seconds <= 0 or poll_interval_seconds > 3600:
        raise ValueError("OPC UA polling interval must be between 0 and 3600 seconds.")
    settings = get_settings()
    retry_delay = settings.edge_retry_base_seconds
    connected = False
    try:
        while True:
            try:
                if not connected:
                    await client.connect()
                    connected = True
                for sensor_map in mappings:
                    data_value = await client.read_data_value(sensor_map.node_id)
                    buffer.enqueue(mapped_reading(sensor_map, data_value))
                publisher.publish_pending()
                retry_delay = settings.edge_retry_base_seconds
                await asyncio.sleep(poll_interval_seconds)
            except (ConnectionError, OSError, TimeoutError, UaError) as error:
                logger.warning(
                    "OPC UA or API connection failed; reconnecting with backoff (error_type=%s).",
                    type(error).__name__,
                )
                if connected:
                    await client.disconnect()
                    connected = False
                await asyncio.sleep(retry_delay)
                retry_delay = min(
                    retry_delay * 2, settings.edge_retry_max_seconds
                )
    finally:
        if connected:
            await client.disconnect()


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Read-only OPC UA to RealityLoop REST edge adapter.")
    parser.add_argument("--mapping", required=True, help="JSON file with explicit node-to-sensor unit and scale mappings.")
    args = parser.parse_args()
    endpoint = os.environ.get("OPCUA_ENDPOINT", "")
    cert = os.environ.get("OPCUA_CLIENT_CERT_FILE", "")
    key = os.environ.get("OPCUA_CLIENT_KEY_FILE", "")
    api_url = os.environ.get("REALITYLOOP_API_URL", "")
    credential = os.environ.get("REALITYLOOP_DEVICE_CREDENTIAL", "")
    buffer_path = os.environ.get("REALITYLOOP_EDGE_BUFFER", "realityloop-edge.sqlite3")
    if not endpoint or not api_url or not credential:
        raise ValueError("Set OPCUA_ENDPOINT, REALITYLOOP_API_URL, and REALITYLOOP_DEVICE_CREDENTIAL.")
    mapping_data = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
    if not isinstance(mapping_data, list) or not mapping_data:
        raise ValueError("OPC UA mapping file must contain a non-empty JSON array.")
    mappings = [OpcUaSensorMap.from_json(entry) for entry in mapping_data]
    buffer = DurableEdgeBuffer(buffer_path)
    publisher = RestEdgePublisher(buffer, api_url=api_url, credential=credential)
    adapter = AsyncUaReadOnlyAdapter(
        endpoint,
        certificate_file=cert,
        private_key_file=key,
    )
    try:
        await run_publisher(
            adapter,
            mappings,
            buffer,
            publisher,
            float(os.environ.get("OPCUA_POLL_INTERVAL_SECONDS", "5")),
        )
    finally:
        await adapter.disconnect()
        buffer.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
