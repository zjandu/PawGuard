"""
Main orchestrator — the central AI Agent loop.

Coordinates:
- Connector (data in)
- BehaviorEngine (learn patterns)
- AnomalyDetector (assess risk)
- AlertAgent (notify)
- Database (persist everything)

This is the single object that ties all modules together.
"""
import logging
import threading
from typing import Dict

from pawguard.config import AppConfig
from pawguard.database import Database
from pawguard.engine.behavior import BehaviorEngine
from pawguard.engine.anomaly import AnomalyDetector
from pawguard.agent.alert_agent import AlertAgent
from pawguard.connectors.base import BaseConnector
from pawguard.connectors.tractive import TractiveConnector
from pawguard.connectors.mqtt_connector import MQTTConnector
from pawguard.connectors.webhook import WebhookConnector
from pawguard.models import LocationEvent, PetConfig

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.db = Database(cfg.data_dir)
        self.behavior = BehaviorEngine(self.db, cfg.thresholds.familiar_zone_radius_meters)
        self.alert_agent = AlertAgent(self.db, cfg.alerts)

        # One detector per pet (could differ in thresholds in the future)
        self.detectors: Dict[str, AnomalyDetector] = {}
        for pet in cfg.pets:
            self.detectors[pet.id] = AnomalyDetector(
                db=self.db,
                behavior=self.behavior,
                home=pet.home_zone,
                thresholds=cfg.thresholds,
            )

        self.pets: Dict[str, PetConfig] = {p.id: p for p in cfg.pets}
        self.connectors: Dict[str, BaseConnector] = {}
        self.webhook_connectors: Dict[str, WebhookConnector] = {}
        self._lock = threading.Lock()

    def on_location_received(self, event: LocationEvent):
        """
        Central callback. Called by any connector when a new location arrives.
        Thread-safe.
        """
        with self._lock:
            pet = self.pets.get(event.pet_id)
            if not pet:
                logger.warning(f"Received location for unknown pet_id: {event.pet_id}")
                return

            logger.info(
                f"[{pet.name}] New location: ({event.lat:.5f}, {event.lon:.5f}) "
                f"source={event.source} battery={event.battery_pct}%"
            )

            # 1. Persist to database
            self.db.insert_location(event)

            # 2. Update behavior model (always — this feeds our learning)
            self.behavior.record(event)

            # 3. Assess risk
            detector = self.detectors.get(event.pet_id)
            assessment = detector.assess(event)

            logger.info(
                f"[{pet.name}] Risk assessment: {assessment.level.value} "
                f"| state={assessment.pet_state.value} "
                f"| confidence={assessment.confidence} "
                f"| triggers={assessment.triggers}"
            )

            # 4. Maybe alert
            self.alert_agent.maybe_alert(pet, event, assessment)

    def start(self):
        logger.info("PawGuard orchestrator starting...")

        for pet in self.cfg.pets:
            connector = self._build_connector(pet)
            if connector:
                self.connectors[pet.id] = connector
                connector.start()
                logger.info(f"Connector started for {pet.name} (type: {self.cfg.tracker_type})")

        # Send startup Telegram message
        for pet in self.cfg.pets:
            try:
                self.alert_agent.send_startup_message(pet)
            except Exception as e:
                logger.warning(f"Could not send startup message: {e}")

        logger.info("PawGuard is running. Monitoring started.")

    def stop(self):
        for connector in self.connectors.values():
            try:
                connector.stop()
            except Exception:
                pass
        logger.info("PawGuard orchestrator stopped.")

    def _build_connector(self, pet: PetConfig) -> BaseConnector:
        t = self.cfg.tracker_type

        if t == "tractive":
            return TractiveConnector(
                pet_id=pet.id,
                on_location_received=self.on_location_received,
                cfg=self.cfg.tractive,
            )
        elif t == "mqtt":
            return MQTTConnector(
                pet_id=pet.id,
                on_location_received=self.on_location_received,
                cfg=self.cfg.mqtt,
            )
        elif t == "webhook":
            wc = WebhookConnector(
                pet_id=pet.id,
                on_location_received=self.on_location_received,
            )
            self.webhook_connectors[pet.id] = wc
            return wc
        else:
            logger.error(f"Unknown tracker type: {t}")
            return None

    def get_webhook_connector(self, pet_id: str) -> WebhookConnector:
        return self.webhook_connectors.get(pet_id)
