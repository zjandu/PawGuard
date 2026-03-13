"""
Behavior pattern engine (V1: rule-based with activity grid).

This engine answers two questions:
1. Is the current location 'familiar'? (Has the pet been here before?)
2. Is the pet's behavior consistent with what it usually does at this time of week?

V1 uses a simple activity grid (not ML). This is intentional:
- No training required
- Transparent and auditable
- Works from day 3 onward
- Can be replaced with GP/HMM in V2 without changing the interface
"""
import logging
from datetime import datetime
from typing import Optional, Tuple, List

from pawguard.engine.geofence import haversine_meters
from pawguard.models import LocationEvent
from pawguard.database import Database

logger = logging.getLogger(__name__)


class BehaviorEngine:
    def __init__(self, db: Database, familiar_zone_radius_m: float = 30.0):
        self.db = db
        self.familiar_zone_radius_m = familiar_zone_radius_m

    def record(self, event: LocationEvent):
        """
        Called on every new location event to update the activity grid.
        Should always be called, even before we have enough data to analyze.
        """
        self.db.update_activity_grid(event)

    def is_familiar_location(self, event: LocationEvent, min_data_days: float = 3.0) -> Tuple[bool, str]:
        """
        Returns (is_familiar, reason).
        
        A location is 'familiar' if the pet has historically been within
        familiar_zone_radius_m of this point during a similar time of week.
        """
        data_days = self.db.get_data_span_days(event.pet_id)
        if data_days < min_data_days:
            # Not enough data yet — conservatively assume familiar
            # (we don't want false alerts in the first few days)
            return True, f"insufficient_data ({data_days:.1f} days < {min_data_days} required)"

        hour_of_week = (event.timestamp.weekday() * 24) + event.timestamp.hour
        known_locations = self.db.get_familiar_locations(event.pet_id, hour_of_week, radius_hours=2)

        if not known_locations:
            return False, "never_visited_this_hour_of_week"

        # Check if any known location is within the familiar radius
        for lat_b, lon_b, count in known_locations:
            dist = haversine_meters(event.lat, event.lon, lat_b, lon_b)
            if dist <= self.familiar_zone_radius_m:
                return True, f"matches_known_location (dist={dist:.0f}m, seen {count}x)"

        # Find the nearest known location to help with diagnostics
        nearest_dist = min(
            haversine_meters(event.lat, event.lon, lat, lon)
            for lat, lon, _ in known_locations
        )
        return False, f"unfamiliar (nearest known: {nearest_dist:.0f}m away)"

    def get_typical_home_center(self, pet_id: str) -> Optional[Tuple[float, float]]:
        """
        Returns the most frequently visited lat/lon as the pet's 'learned home center'.
        Useful for display purposes.
        """
        from pawguard.database import Database
        with self.db._conn() as conn:
            row = conn.execute("""
                SELECT lat_bucket, lon_bucket, SUM(count) as total
                FROM activity_grid
                WHERE pet_id = ?
                GROUP BY lat_bucket, lon_bucket
                ORDER BY total DESC
                LIMIT 1
            """, (pet_id,)).fetchone()
        if row:
            return row["lat_bucket"], row["lon_bucket"]
        return None
