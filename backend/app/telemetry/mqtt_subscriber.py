import json
import logging
import queue
import threading
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from bson import ObjectId
from bson.errors import InvalidId
from paho.mqtt import client as mqtt
from pydantic import ValidationError

from app.core.config import get_settings
from app.db.client import get_database
from app.telemetry.devices import audit_device_event, authenticate_device_token
from app.telemetry.ingestion import DeviceReading, ingest_readings

logger = logging.getLogger(__name__)
MQTT_TOPIC_PREFIX = "realityloop/v1/organizations"


def _reject(index: int, code: str, message: str) -> dict[str, Any]:
    return {"index": index, "status": "rejected", "code": code, "message": message}


def process_mqtt_message(
    *,
    database,
    topic: str,
    payload: bytes,
    received_at: datetime | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if len(payload) > settings.mqtt_message_max_bytes:
        raise ValueError("MQTT message exceeds the configured payload byte limit.")
    if len(payload) > settings.device_batch_max_bytes:
        raise ValueError("MQTT message exceeds the configured device batch byte limit.")
    parts = topic.split("/")
    if (
        len(parts) != 7
        or parts[:3] != ["realityloop", "v1", "organizations"]
        or parts[4] != "devices"
        or parts[6] != "readings"
    ):
        raise ValueError("MQTT topic must follow the documented organization/device scheme.")
    try:
        organization_id = ObjectId(parts[3])
    except InvalidId as error:
        raise ValueError("MQTT topic organization is invalid.") from error
    try:
        body = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("MQTT payload must be valid UTF-8 JSON.") from error
    if not isinstance(body, dict) or set(body) != {"credential", "readings"}:
        raise ValueError("MQTT payload must contain only credential and readings.")
    token = body["credential"]
    if not isinstance(token, str):
        raise ValueError("MQTT payload requires a device credential.")
    credential = authenticate_device_token(database, token)
    if credential is None:
        raise PermissionError("MQTT device credential is invalid, revoked, or expired.")
    if (
        credential["key_id"] != parts[5]
        or credential["organization_id"] != organization_id
    ):
        raise PermissionError("MQTT topic does not match the credential's organization and key.")
    raw_readings = body["readings"]
    if (
        not isinstance(raw_readings, list)
        or not raw_readings
        or len(raw_readings) > settings.device_batch_max_readings
    ):
        raise ValueError("MQTT readings must be a non-empty bounded array.")

    parsed: list[DeviceReading | None] = []
    results: list[dict[str, Any] | None] = [None] * len(raw_readings)
    for index, value in enumerate(raw_readings):
        try:
            parsed.append(DeviceReading.model_validate(value))
        except ValidationError:
            parsed.append(None)
            results[index] = _reject(
                index,
                "INVALID_ITEM",
                "Provide sensor_id, finite value, unit, and offset-aware event_time_utc.",
            )
    valid_items = [item for item in parsed if item is not None]
    valid_results = ingest_readings(
        database=database,
        credential=credential,
        items=valid_items,
        source="mqtt",
        received_at=received_at,
    )
    result_index = 0
    for index, result in enumerate(results):
        if result is None:
            valid_result = valid_results[result_index]
            valid_result["index"] = index
            results[index] = valid_result
            result_index += 1
    final = [result for result in results if result is not None]
    counts = {
        "accepted": sum(item["status"] == "accepted" for item in final),
        "duplicates": sum(item["status"] == "duplicate" for item in final),
        "rejected": sum(item["status"] == "rejected" for item in final),
    }
    audit_device_event(
        database,
        organization_id=credential["organization_id"],
        event="mqtt_readings_ingested",
        credential_id=credential["_id"],
        actor_user_id=None,
        created_at=received_at or datetime.now(UTC),
        counts=counts,
    )
    return {"results": final, "counts": counts, "source": "measured"}


class MQTTIngestSubscriber:
    def __init__(self) -> None:
        settings = get_settings()
        parsed = urlparse(settings.mqtt_broker_url)
        if parsed.scheme != "mqtts" or not parsed.hostname:
            raise ValueError("MQTT broker URL must be a TLS mqtts:// URL.")
        if bool(settings.mqtt_client_cert_file) != bool(settings.mqtt_client_key_file):
            raise ValueError("MQTT client certificate and key must be configured together.")
        if bool(settings.mqtt_username) != bool(settings.mqtt_password):
            raise ValueError("MQTT broker username and password must be configured together.")
        self.settings = settings
        self.host = parsed.hostname
        self.port = parsed.port or 8883
        self.messages: queue.Queue = queue.Queue(settings.mqtt_queue_capacity)
        self.stopping = threading.Event()
        self.reconnect_requested = threading.Event()
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="realityloop-telemetry-ingest",
            protocol=mqtt.MQTTv311,
            clean_session=False,
            manual_ack=True,
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        if settings.mqtt_ca_file:
            self.client.tls_set(
                ca_certs=settings.mqtt_ca_file,
                certfile=settings.mqtt_client_cert_file or None,
                keyfile=settings.mqtt_client_key_file or None,
            )
        else:
            self.client.tls_set(
                certfile=settings.mqtt_client_cert_file or None,
                keyfile=settings.mqtt_client_key_file or None,
            )
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self.consumer = threading.Thread(
            target=self._consume, name="mqtt-telemetry-consumer", daemon=True
        )
        self.reconnector = threading.Thread(
            target=self._reconnect, name="mqtt-reconnect", daemon=True
        )

    def start(self) -> None:
        self.client.connect_async(self.host, self.port, keepalive=60)
        self.client.loop_start()
        self.consumer.start()
        self.reconnector.start()

    def stop(self) -> None:
        self.stopping.set()
        self.reconnect_requested.set()
        self.client.disconnect()
        self.client.loop_stop()
        if self.consumer.is_alive():
            self.consumer.join(timeout=5)
        if self.reconnector.is_alive():
            self.reconnector.join(timeout=5)

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code.is_failure:
            logger.error("MQTT broker connection rejected.")
            return
        client.subscribe(
            f"{MQTT_TOPIC_PREFIX}/+/devices/+/readings",
            qos=1,
        )

    def _on_message(self, client, _userdata, message) -> None:
        if message.retain or len(message.payload) > self.settings.mqtt_message_max_bytes:
            client.ack(message.mid, message.qos)
            logger.warning("Rejected retained or oversized MQTT message.")
            return
        try:
            self.messages.put_nowait(message)
        except queue.Full:
            logger.warning("MQTT ingestion queue is full; disconnecting to apply broker backpressure.")
            self._request_reconnect()

    def _consume(self) -> None:
        while not self.stopping.is_set():
            try:
                message = self.messages.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                try:
                    result = process_mqtt_message(
                        database=get_database(),
                        topic=message.topic,
                        payload=message.payload,
                    )
                except PermissionError:
                    result = {"status": "rejected", "code": "DEVICE_NOT_PERMITTED"}
                    logger.warning("Rejected MQTT message by credential policy.")
                except ValueError:
                    result = {"status": "rejected", "code": "INVALID_MESSAGE"}
                    logger.warning("Rejected MQTT message by schema or credential policy.")
                except Exception as error:
                    logger.error(
                        "MQTT message processing failed; message will be redelivered (error_type=%s).",
                        type(error).__name__,
                    )
                    self._request_reconnect()
                    continue
                try:
                    self._publish_result(message.topic, result)
                except Exception as error:
                    logger.error(
                        "MQTT result delivery failed; message will be redelivered (error_type=%s).",
                        type(error).__name__,
                    )
                    self._request_reconnect()
                else:
                    self.client.ack(message.mid, message.qos)
            finally:
                self.messages.task_done()

    def _request_reconnect(self) -> None:
        self.client.disconnect()
        self.reconnect_requested.set()

    def _reconnect(self) -> None:
        delay = 1.0
        while not self.stopping.is_set():
            if not self.reconnect_requested.wait(timeout=0.5):
                continue
            while not self.stopping.is_set() and not self.messages.empty():
                self.stopping.wait(0.1)
            if self.stopping.is_set():
                break
            self.client.loop_stop()
            self.reconnect_requested.clear()
            try:
                self.client.connect(self.host, self.port, keepalive=60)
                self.client.loop_start()
                self.reconnect_requested.clear()
                delay = 1.0
            except Exception as error:
                logger.warning(
                    "MQTT reconnect failed; retrying with backoff (error_type=%s).",
                    type(error).__name__,
                )
                self.stopping.wait(delay)
                delay = min(delay * 2, 60)

    def _publish_result(self, topic: str, result: dict[str, Any]) -> None:
        parts = topic.split("/")
        if len(parts) != 7 or parts[:3] != ["realityloop", "v1", "organizations"]:
            return
        response_topic = (
            f"{MQTT_TOPIC_PREFIX}/{parts[3]}/devices/{parts[5]}/results"
        )
        info = self.client.publish(
            response_topic,
            json.dumps(result, separators=(",", ":")),
            qos=1,
            retain=False,
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError("MQTT result could not be queued for delivery.")
        info.wait_for_publish(timeout=5)
        if not info.is_published():
            raise TimeoutError("MQTT result delivery timed out.")


def start_mqtt_subscriber() -> MQTTIngestSubscriber | None:
    if not get_settings().mqtt_enabled:
        return None
    subscriber = MQTTIngestSubscriber()
    subscriber.start()
    logger.info("MQTT subscriber started with bounded QoS 1 ingestion.")
    return subscriber
