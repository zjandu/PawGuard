"""
Alert agent: formats and dispatches notifications.

Design principles:
1. Avoid "cry wolf" — deduplicate alerts, only escalate (never spam same level)
2. Every alert includes: what happened, where, how long, what to do
3. Deep link to map so owner can act immediately
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import requests

from pawguard.models import RiskAssessment, AlertLevel, LocationEvent, AlertRecord, PetConfig
from pawguard.config import AlertsConfig
from pawguard.database import Database

logger = logging.getLogger(__name__)

LEVEL_EMOJI = {
    AlertLevel.SAFE:     "🟢",
    AlertLevel.NOTICE:   "🔵",
    AlertLevel.WARNING:  "🟠",
    AlertLevel.CRITICAL: "🔴",
}

LEVEL_PRIORITY = {
    AlertLevel.SAFE: 0,
    AlertLevel.NOTICE: 1,
    AlertLevel.WARNING: 2,
    AlertLevel.CRITICAL: 3,
}


class AlertAgent:
    def __init__(self, db: Database, cfg: AlertsConfig):
        self.db = db
        self.cfg = cfg

    def maybe_alert(
        self,
        pet: PetConfig,
        event: LocationEvent,
        assessment: RiskAssessment,
    ):
        """
        Decide whether to send an alert based on:
        - Current level vs. last alert level
        - Deduplication window
        """
        if assessment.level == AlertLevel.SAFE:
            return

        last_alert = self.db.get_last_alert(pet.id)
        
        if last_alert:
            elapsed = (datetime.utcnow() - last_alert.timestamp).total_seconds() / 60
            same_or_lower_level = (
                LEVEL_PRIORITY[assessment.level] <= LEVEL_PRIORITY[last_alert.level]
            )
            within_dedup_window = elapsed < self.cfg.dedup_minutes

            if same_or_lower_level and within_dedup_window:
                logger.debug(
                    f"Alert suppressed (dedup): {assessment.level} within {elapsed:.0f}min window"
                )
                return

        message = self._format_message(pet, event, assessment)
        alert_record = AlertRecord(
            pet_id=pet.id,
            timestamp=datetime.utcnow(),
            level=assessment.level,
            message=message,
            triggers=assessment.triggers,
            lat=event.lat,
            lon=event.lon,
        )
        self.db.insert_alert(alert_record)
        self._dispatch(message, assessment.level)

    def _format_message(
        self, pet: PetConfig, event: LocationEvent, assessment: RiskAssessment
    ) -> str:
        emoji = LEVEL_EMOJI[assessment.level]
        map_url = f"https://www.google.com/maps?q={event.lat},{event.lon}"
        
        lines = [
            f"{emoji} *PawGuard Alert — {pet.name}*",
            f"Level: `{assessment.level.value}` | Confidence: {assessment.confidence}",
            "",
            f"📍 Location: [{event.lat:.5f}, {event.lon:.5f}]({map_url})",
            f"🏠 Distance from home: {assessment.distance_from_home_m:.0f}m",
            f"⏱ Motionless for: {assessment.minutes_since_last_movement} min",
            f"📡 GPS fix age: {self._fix_age(event)}",
        ]

        if event.battery_pct is not None:
            batt_emoji = "🔋" if event.battery_pct > 20 else "🪫"
            lines.append(f"{batt_emoji} Battery: {event.battery_pct}%")

        lines.append("")
        lines.append("*Why this alert:*")
        for trigger in assessment.triggers:
            lines.append(f"• {trigger}")

        lines.append("")
        lines.append(f"*What to do:* {assessment.suggested_action}")

        return "\n".join(lines)

    def _fix_age(self, event: LocationEvent) -> str:
        age_s = (datetime.utcnow() - event.timestamp).total_seconds()
        if age_s < 60:
            return f"{age_s:.0f}s ago"
        return f"{age_s/60:.0f}min ago"

    def _dispatch(self, message: str, level: AlertLevel):
        if self.cfg.telegram and self.cfg.telegram.enabled:
            self._send_telegram(message)

    def _send_telegram(self, message: str):
        cfg = self.cfg.telegram
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage",
                json={
                    "chat_id": cfg.chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("Telegram alert sent successfully.")
            else:
                logger.error(f"Telegram send failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"Telegram dispatch error: {e}")

    def send_startup_message(self, pet: PetConfig):
        """Notify owner that PawGuard is running and protecting their pet."""
        message = (
            f"🐾 *PawGuard started*\n"
            f"Now monitoring: *{pet.name}*\n"
            f"Home zone: {pet.home_zone.lat:.4f}, {pet.home_zone.lon:.4f} "
            f"(radius: {pet.home_zone.radius_meters:.0f}m)\n\n"
            f"You will be notified if {pet.name} enters an unfamiliar area or "
            f"remains motionless in an unknown location."
        )
        self._dispatch(message, AlertLevel.NOTICE)
