"""
Tractive GPS connector.

Uses the unofficial Tractive REST API (reverse-engineered from the mobile app).
Endpoints are not officially documented but are stable and widely used by the
Home Assistant community integration (github.com/Danielhiversen/PyTractiveGPS).

Rate limit: Tractive allows ~60 req/min on free accounts.
Poll interval should be at minimum 60 seconds.
"""
import threading
import time
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

import requests

from pawguard.connectors.base import BaseConnector
from pawguard.models import LocationEvent
from pawguard.config import TractiveConfig

logger = logging.getLogger(__name__)

TRACTIVE_BASE = "https://platform.tractive.com/v2"
CLIENT_ID = "5f9be055d8912eb21a4cd7ba"   # Tractive's public mobile client ID


class TractiveConnector(BaseConnector):
    """
    Polls the Tractive API at a configurable interval.
    
    Free Tractive accounts update GPS every 2-3 minutes.
    Tractive Premium accounts support Live Tracking (every 2-3 seconds).
    This connector polls at poll_interval_seconds; set it to match your plan.
    """

    def __init__(
        self,
        pet_id: str,
        on_location_received: Callable[[LocationEvent], None],
        cfg: TractiveConfig,
    ):
        super().__init__(pet_id, on_location_received)
        self.cfg = cfg
        self._session = requests.Session()
        self._token: Optional[str] = None
        self._thread: Optional[threading.Thread] = None

    def _authenticate(self) -> bool:
        """Obtain a session token from Tractive."""
        try:
            resp = self._session.post(
                f"{TRACTIVE_BASE}/user/session",
                json={
                    "platform_email": self.cfg.email,
                    "platform_token": self.cfg.password,
                },
                headers={"X-Tractive-Client": CLIENT_ID},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                self._token = data.get("access_token")
                self._session.headers.update({
                    "Authorization": f"Bearer {self._token}",
                    "X-Tractive-Client": CLIENT_ID,
                })
                logger.info("Tractive authentication successful.")
                return True
            else:
                logger.error(f"Tractive auth failed: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Tractive auth exception: {e}")
            return False

    def _fetch_position(self) -> Optional[LocationEvent]:
        """Fetch the latest GPS position for the tracker."""
        try:
            resp = self._session.get(
                f"{TRACTIVE_BASE}/device_pos_report/{self.cfg.tracker_id}",
                timeout=10,
            )
            if resp.status_code == 401:
                logger.warning("Tractive token expired, re-authenticating...")
                if self._authenticate():
                    return self._fetch_position()
                return None

            if resp.status_code != 200:
                logger.warning(f"Position fetch returned {resp.status_code}")
                return None

            data = resp.json()
            pos = data.get("pos_status", {})
            lat = pos.get("lat")
            lon = pos.get("lon")

            if lat is None or lon is None:
                logger.warning("Position response missing lat/lon")
                return None

            # Tractive timestamps are Unix seconds UTC
            ts_raw = pos.get("time", time.time())
            ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc).replace(tzinfo=None)

            # Fetch battery separately
            battery_pct = None
            try:
                hw_resp = self._session.get(
                    f"{TRACTIVE_BASE}/hardware/{self.cfg.tracker_id}",
                    timeout=5,
                )
                if hw_resp.status_code == 200:
                    battery_pct = hw_resp.json().get("battery_level")
            except Exception:
                pass

            return LocationEvent(
                pet_id=self.pet_id,
                timestamp=ts,
                lat=float(lat),
                lon=float(lon),
                accuracy_meters=float(pos.get("accuracy", 50)),
                battery_pct=battery_pct,
                source="gps",
                speed_kmh=pos.get("speed"),
                raw=data,
            )

        except Exception as e:
            logger.error(f"Tractive fetch exception: {e}")
            return None

    def _poll_loop(self):
        logger.info(f"Tractive polling loop started (interval: {self.cfg.poll_interval_seconds}s)")
        last_timestamp = None

        while self._running:
            event = self._fetch_position()
            if event:
                # Only forward if this is a genuinely new GPS fix
                if event.timestamp != last_timestamp:
                    last_timestamp = event.timestamp
                    self.on_location_received(event)
                else:
                    logger.debug("Tractive: same timestamp as last fix, skipping.")
            time.sleep(self.cfg.poll_interval_seconds)

    def start(self):
        if not self._authenticate():
            raise RuntimeError("Could not authenticate with Tractive. Check email/password.")
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Tractive connector stopped.")
