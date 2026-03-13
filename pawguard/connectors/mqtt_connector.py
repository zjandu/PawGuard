"""
Generic MQTT connector.

Designed for DIY hardware (ESP32, Arduino + SIM7000, etc.)
The device should publish JSON to the configured topic.

Expected payload format:
{
  "lat": 39.9042,
  "lon": 116.4074,
  "accuracy": 10.5,       (optional, meters)
  "battery": 78,          (optional, percent 0-100)
  "speed": 0.5,           (optional, km/h)
  "ts": 1710000000        (optional, unix timestamp; defaults to server time)
}
"""
import json
import logging
import threading
from datetime import datetime
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from pawguard.connectors.base import BaseConnector
from pawguard.config import MQTTConfig
from pawguard.models import LocationEvent

logger = logging.getLogger(__name__)


class MQTTConnector(BaseConnector):
    def __init__(
        self,
        pet_id: str,
        on_location_received: Callable[[LocationEvent], None],
        cfg: MQTTConfig,
    ):
        super().__init__(pet_id, on_location_received)
        self.cfg = cfg
        self._client: Optional[mqtt.Client] = None

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info(f"MQTT connected to {self.cfg.host}:{self.cfg.port}")
            client.subscribe(self.cfg.topic)
            logger.info(f"MQTT subscribed to topic: {self.cfg.topic}")
        else:
            logger.error(f"MQTT connection failed, rc={rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except json.JSONDecodeError as e:
            logger.warning(f"MQTT: invalid JSON payload: {e}")
            return

        lat = payload.get("lat")
        lon = payload.get("lon")
        if lat is None or lon is None:
            logger.warning(f"MQTT payload missing lat/lon: {payload}")
            return

        ts_raw = payload.get("ts")
        if ts_raw:
            ts = datetime.utcfromtimestamp(float(ts_raw))
        else:
            ts = datetime.utcnow()

        event = LocationEvent(
            pet_id=self.pet_id,
            timestamp=ts,
            lat=float(lat),
            lon=float(lon),
            accuracy_meters=float(payload.get("accuracy", 50)),
            battery_pct=payload.get("battery"),
            source="mqtt",
            speed_kmh=payload.get("speed"),
            raw=payload,
        )
        logger.debug(f"MQTT location received: ({lat}, {lon})")
        self.on_location_received(event)

    def start(self):
        self._client = mqtt.Client()
        if self.cfg.username:
            self._client.username_pw_set(self.cfg.username, self.cfg.password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        self._client.connect(self.cfg.host, self.cfg.port, keepalive=60)
        self._running = True
        # loop_start() runs the MQTT network loop in a background thread
        self._client.loop_start()

    def stop(self):
        self._running = False
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
        logger.info("MQTT connector stopped.")
