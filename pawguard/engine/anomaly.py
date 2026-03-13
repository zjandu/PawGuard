"""
Anomaly detection engine.

Combines multiple signals into a single RiskAssessment.
Each check is independent — they all run and their results are fused.

V1 Detection Rules (in order of severity):
1. Long stillness in unfamiliar location (highest priority — the core cat-safety use case)
2. Outside geofence radius
3. Time-pattern mismatch + unfamiliar location
4. Computed speed anomaly (GPS glitch detection)
5. Low battery warning
6. No signal timeout
"""
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

from pawguard.engine.geofence import is_inside_zone, distance_from_home, compute_speed_kmh
from pawguard.engine.behavior import BehaviorEngine
from pawguard.models import (
    LocationEvent, RiskAssessment, AlertLevel, PetState, HomeZone
)
from pawguard.database import Database
from pawguard.config import ThresholdsConfig

logger = logging.getLogger(__name__)

# Cats at rest normally move < 5m between GPS fixes
MOVEMENT_THRESHOLD_METERS = 5.0
# If GPS is older than this, escalate
GPS_STALE_WARNING_MINUTES = 10
GPS_STALE_CRITICAL_MINUTES = 30


class AnomalyDetector:
    def __init__(
        self,
        db: Database,
        behavior: BehaviorEngine,
        home: HomeZone,
        thresholds: ThresholdsConfig,
    ):
        self.db = db
        self.behavior = behavior
        self.home = home
        self.t = thresholds

    def assess(self, event: LocationEvent) -> RiskAssessment:
        """
        Full risk assessment for a new location event.
        Returns a RiskAssessment with the highest-priority finding.
        """
        triggers: List[str] = []
        level = AlertLevel.SAFE
        state = PetState.UNKNOWN

        dist_from_home = distance_from_home(event.lat, event.lon, self.home)
        inside_home_zone = is_inside_zone(event.lat, event.lon, self.home)
        is_familiar, familiarity_reason = self.behavior.is_familiar_location(
            event, min_data_days=self.t.min_behavior_data_days
        )

        # ── 1. Stillness analysis ──────────────────────────────────────────
        still_minutes = self._minutes_since_last_movement(event)

        if not inside_home_zone and not is_familiar:
            if still_minutes >= self.t.stillness_critical_minutes:
                level = AlertLevel.CRITICAL
                state = PetState.STILL_UNFAMILIAR
                triggers.append(
                    f"IMMOBILE in unfamiliar location for {still_minutes:.0f} minutes "
                    f"(threshold: {self.t.stillness_critical_minutes} min)"
                )
            elif still_minutes >= self.t.stillness_warning_minutes:
                level = AlertLevel.WARNING
                state = PetState.STILL_UNFAMILIAR
                triggers.append(
                    f"Still in unfamiliar location for {still_minutes:.0f} minutes "
                    f"(threshold: {self.t.stillness_warning_minutes} min)"
                )
        elif inside_home_zone or is_familiar:
            state = PetState.STILL_FAMILIAR if still_minutes > 10 else PetState.HOME

        # ── 2. Geofence violation ──────────────────────────────────────────
        if not inside_home_zone:
            geofence_dist = dist_from_home - self.t.geofence_radius_meters
            if geofence_dist > 0:
                geofence_level = AlertLevel.WARNING if geofence_dist < 200 else AlertLevel.NOTICE
                if geofence_level.value > level.value or level == AlertLevel.SAFE:
                    # Only upgrade, never downgrade
                    pass
                triggers.append(
                    f"Outside geofence by {geofence_dist:.0f}m "
                    f"(home radius: {self.t.geofence_radius_meters:.0f}m)"
                )
                if level == AlertLevel.SAFE:
                    level = AlertLevel.NOTICE
                if state == PetState.UNKNOWN:
                    state = PetState.EXPLORING

        # ── 3. Speed anomaly (GPS glitch detection) ────────────────────────
        speed_issue = self._check_speed_anomaly(event)
        if speed_issue:
            triggers.append(speed_issue)
            # Speed anomaly alone is informational, doesn't escalate level

        # ── 4. Low battery ─────────────────────────────────────────────────
        if event.battery_pct is not None and event.battery_pct <= self.t.low_battery_warning_pct:
            triggers.append(f"Low battery: {event.battery_pct}%")
            if level == AlertLevel.SAFE:
                level = AlertLevel.NOTICE

        # ── 5. Stale GPS ───────────────────────────────────────────────────
        minutes_old = (datetime.utcnow() - event.timestamp).total_seconds() / 60
        if minutes_old > GPS_STALE_CRITICAL_MINUTES:
            triggers.append(f"GPS data is {minutes_old:.0f} minutes old")
            if level in (AlertLevel.SAFE, AlertLevel.NOTICE):
                level = AlertLevel.WARNING
        elif minutes_old > GPS_STALE_WARNING_MINUTES:
            triggers.append(f"GPS data is {minutes_old:.0f} minutes old")

        # ── Final state resolution ─────────────────────────────────────────
        if state == PetState.UNKNOWN:
            state = PetState.HOME if inside_home_zone else PetState.EXPLORING

        action = self._suggested_action(level, state, still_minutes, dist_from_home)
        confidence = self._confidence(event, still_minutes)

        return RiskAssessment(
            level=level,
            pet_state=state,
            triggers=triggers if triggers else ["All checks passed"],
            suggested_action=action,
            confidence=confidence,
            minutes_since_last_movement=int(still_minutes),
            distance_from_home_m=dist_from_home,
            is_in_familiar_zone=is_familiar,
        )

    def _minutes_since_last_movement(self, event: LocationEvent) -> float:
        """
        How long has the pet been approximately stationary?
        Looks back through recent history to find the last significant movement.
        """
        recent = self.db.get_recent_locations(event.pet_id, limit=60)
        if len(recent) < 2:
            return 0.0

        # recent[0] is the latest (just stored before this call)
        # Walk backwards to find last significant movement
        ref_lat, ref_lon = event.lat, event.lon
        for past_event in recent:
            from pawguard.engine.geofence import haversine_meters
            dist = haversine_meters(ref_lat, ref_lon, past_event.lat, past_event.lon)
            if dist > MOVEMENT_THRESHOLD_METERS:
                # Found the last point where the pet was meaningfully elsewhere
                elapsed = (event.timestamp - past_event.timestamp).total_seconds() / 60
                return max(0.0, elapsed)

        # All recent history shows no movement — use full time span
        oldest = recent[-1]
        elapsed = (event.timestamp - oldest.timestamp).total_seconds() / 60
        return max(0.0, elapsed)

    def _check_speed_anomaly(self, current: LocationEvent) -> Optional[str]:
        """
        Detect GPS teleportation (common with poor satellite lock).
        A cat cannot physically move faster than ~50 km/h (sprint speed ~45 km/h).
        """
        recent = self.db.get_recent_locations(current.pet_id, limit=2)
        if not recent:
            return None
        prev = recent[0]
        dt = (current.timestamp - prev.timestamp).total_seconds()
        if dt < 5:
            return None  # Too close in time to be meaningful
        speed = compute_speed_kmh(
            prev.lat, prev.lon, prev.timestamp,
            current.lat, current.lon, current.timestamp
        )
        if speed > 80:  # Clear physical impossibility for a cat
            return f"Suspicious GPS jump: computed speed {speed:.0f} km/h (likely GPS glitch)"
        return None

    def _suggested_action(
        self, level: AlertLevel, state: PetState,
        still_minutes: float, dist_m: float
    ) -> str:
        if level == AlertLevel.CRITICAL:
            return (
                f"GO NOW — pet has been motionless in an unfamiliar location for "
                f"{still_minutes:.0f} minutes. This could indicate injury, illness, or poisoning. "
                f"Head to the last known location immediately."
            )
        if level == AlertLevel.WARNING:
            if state == PetState.STILL_UNFAMILIAR:
                return (
                    f"Check on your pet — motionless in unfamiliar area for {still_minutes:.0f} min. "
                    f"Try calling or use a squeaky toy. If no response in 5 minutes, go in person."
                )
            return "Monitor closely. Check location on map and be ready to investigate."
        if level == AlertLevel.NOTICE:
            return "Pet is exploring. No immediate action needed. Keep an eye on updates."
        return "Everything looks normal. No action needed."

    def _confidence(self, event: LocationEvent, still_minutes: float) -> str:
        if event.accuracy_meters > 100:
            return "LOW"  # Poor GPS fix
        if still_minutes > 5:
            return "HIGH"  # Stillness is unambiguous
        return "MEDIUM"
