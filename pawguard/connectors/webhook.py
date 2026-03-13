"""
Webhook connector.

PawGuard exposes a POST endpoint that any external service can call.
Compatible with: IFTTT, Zapier, OwnTracks, GPSLogger (Android), and any
tracker that supports HTTP webhook callbacks.

The API endpoint is defined in api/app.py and calls WebhookConnector.handle_payload().

Supported payload formats:
1. PawGuard standard (same as MQTT JSON format)
2. OwnTracks (_type: "location")
3. GPSLogger for Android
"""
import logging
from datetime import datetime
from typing import Callable
from pawguard.connectors.base import BaseConnector
from pawguard.models import LocationEvent

logger = logging.getLogger(__name__)


class WebhookConnector(BaseConnector):
    """
    Passive connector — it doesn't poll anything.
    Data arrives via HTTP POST to /webhook/location.
    The FastAPI route calls handle_payload() directly.
    """

    def start(self):
        self._running = True
        logger.info("Webhook connector ready (listening for HTTP POST)")

    def stop(self):
        self._running = False

    def handle_payload(self, payload: dict, secret_header: str = None) -> bool:
        """
        Parse incoming webhook payload and dispatch a LocationEvent.
        Returns True if the payload was valid and processed.
        """
        event = self._parse_payload(payload)
        if event:
            logger.debug(f"Webhook location: ({event.lat}, {event.lon})")
            self.on_location_received(event)
            return True
        return False

    def _parse_payload(self, payload: dict) -> LocationEvent | None:
        # Format 2: OwnTracks (check before standard — it also has lat/lon)
        if payload.get("_type") == "location":
            return self._parse_owntracks(payload)

        # Format 3: GPSLogger for Android
        if "latitude" in payload and "longitude" in payload:
            return self._parse_gpslogger(payload)

        # Format 1: PawGuard / MQTT standard
        if "lat" in payload and "lon" in payload:
            return self._parse_standard(payload)

        logger.warning(f"Webhook: unrecognized payload format: {list(payload.keys())}")
        return None

    def _parse_standard(self, p: dict) -> LocationEvent:
        ts_raw = p.get("ts")
        ts = datetime.utcfromtimestamp(float(ts_raw)) if ts_raw else datetime.utcnow()
        return LocationEvent(
            pet_id=self.pet_id,
            timestamp=ts,
            lat=float(p["lat"]),
            lon=float(p["lon"]),
            accuracy_meters=float(p.get("accuracy", 50)),
            battery_pct=p.get("battery"),
            source="webhook",
            speed_kmh=p.get("speed"),
            raw=p,
        )

    def _parse_owntracks(self, p: dict) -> LocationEvent:
        ts = datetime.utcfromtimestamp(p["tst"]) if "tst" in p else datetime.utcnow()
        return LocationEvent(
            pet_id=self.pet_id,
            timestamp=ts,
            lat=float(p["lat"]),
            lon=float(p["lon"]),
            accuracy_meters=float(p.get("acc", 50)),
            battery_pct=p.get("batt"),
            source="owntracks",
            speed_kmh=p.get("vel"),
            raw=p,
        )

    def _parse_gpslogger(self, p: dict) -> LocationEvent:
        ts_str = p.get("time") or p.get("datetime")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            ts = datetime.utcnow()
        return LocationEvent(
            pet_id=self.pet_id,
            timestamp=ts,
            lat=float(p["latitude"]),
            lon=float(p["longitude"]),
            accuracy_meters=float(p.get("accuracy", 50)),
            battery_pct=p.get("battery"),
            source="gpslogger",
            speed_kmh=p.get("speed"),
            raw=p,
        )
