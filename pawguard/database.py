"""
SQLite database layer.
Stores location history, alert records, and learned behavior patterns.
No external DB required — a single .db file lives in the data/ directory.
"""
import sqlite3
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from pathlib import Path
from pawguard.models import LocationEvent, AlertRecord, AlertLevel

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, data_dir: str):
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.db_path = str(Path(data_dir) / "pawguard.db")
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS location_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    pet_id      TEXT    NOT NULL,
                    timestamp   TEXT    NOT NULL,
                    lat         REAL    NOT NULL,
                    lon         REAL    NOT NULL,
                    accuracy_m  REAL    DEFAULT 50,
                    battery_pct INTEGER,
                    source      TEXT    DEFAULT 'unknown',
                    speed_kmh   REAL
                );

                CREATE INDEX IF NOT EXISTS idx_loc_pet_ts
                    ON location_events(pet_id, timestamp DESC);

                CREATE TABLE IF NOT EXISTS alerts (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    pet_id       TEXT    NOT NULL,
                    timestamp    TEXT    NOT NULL,
                    level        TEXT    NOT NULL,
                    message      TEXT    NOT NULL,
                    triggers     TEXT,
                    lat          REAL,
                    lon          REAL,
                    acknowledged INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_alert_pet_ts
                    ON alerts(pet_id, timestamp DESC);

                -- Hourly activity grid: how often is this pet at approximately
                -- this lat/lon during this hour of week?
                CREATE TABLE IF NOT EXISTS activity_grid (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    pet_id      TEXT    NOT NULL,
                    hour_of_week INTEGER NOT NULL,  -- 0-167 (7 days * 24 hours)
                    lat_bucket  REAL    NOT NULL,   -- rounded to ~11m precision
                    lon_bucket  REAL    NOT NULL,
                    count       INTEGER DEFAULT 1,
                    UNIQUE(pet_id, hour_of_week, lat_bucket, lon_bucket)
                );
            """)
        logger.info(f"Database initialized at {self.db_path}")

    # ── Location events ────────────────────────────────────────────────────

    def insert_location(self, event: LocationEvent):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO location_events
                    (pet_id, timestamp, lat, lon, accuracy_m, battery_pct, source, speed_kmh)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.pet_id,
                event.timestamp.isoformat(),
                event.lat, event.lon,
                event.accuracy_meters,
                event.battery_pct,
                event.source,
                event.speed_kmh,
            ))

    def get_recent_locations(self, pet_id: str, limit: int = 100) -> List[LocationEvent]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM location_events
                WHERE pet_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (pet_id, limit)).fetchall()
        return [self._row_to_location(r) for r in rows]

    def get_locations_since(self, pet_id: str, since: datetime) -> List[LocationEvent]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM location_events
                WHERE pet_id = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (pet_id, since.isoformat())).fetchall()
        return [self._row_to_location(r) for r in rows]

    def get_last_location(self, pet_id: str) -> Optional[LocationEvent]:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT * FROM location_events
                WHERE pet_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (pet_id,)).fetchone()
        return self._row_to_location(row) if row else None

    def get_data_span_days(self, pet_id: str) -> float:
        """How many days of history do we have for this pet?"""
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    MIN(timestamp) as earliest,
                    MAX(timestamp) as latest
                FROM location_events
                WHERE pet_id = ?
            """, (pet_id,)).fetchone()
        if not row or not row["earliest"]:
            return 0.0
        t0 = datetime.fromisoformat(row["earliest"])
        t1 = datetime.fromisoformat(row["latest"])
        return (t1 - t0).total_seconds() / 86400

    def _row_to_location(self, row) -> LocationEvent:
        return LocationEvent(
            pet_id=row["pet_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            lat=row["lat"],
            lon=row["lon"],
            accuracy_meters=row["accuracy_m"] or 50.0,
            battery_pct=row["battery_pct"],
            source=row["source"] or "unknown",
            speed_kmh=row["speed_kmh"],
        )

    # ── Activity grid (behavior patterns) ─────────────────────────────────

    def update_activity_grid(self, event: LocationEvent):
        """
        Round the coordinate to ~11m resolution and record that the pet
        was at approximately this place during this hour of the week.
        """
        hour_of_week = (event.timestamp.weekday() * 24) + event.timestamp.hour
        lat_b = round(event.lat, 4)   # ~11m precision
        lon_b = round(event.lon, 4)

        with self._conn() as conn:
            conn.execute("""
                INSERT INTO activity_grid (pet_id, hour_of_week, lat_bucket, lon_bucket, count)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(pet_id, hour_of_week, lat_bucket, lon_bucket)
                DO UPDATE SET count = count + 1
            """, (event.pet_id, hour_of_week, lat_b, lon_b))

    def get_familiar_locations(
        self, pet_id: str, hour_of_week: int, radius_hours: int = 2
    ) -> List[Tuple[float, float, int]]:
        """
        Return (lat, lon, count) tuples of historically visited locations
        near the given hour of week. Used to determine if current location
        is 'familiar'.
        """
        # Wrap around week boundary (167 -> 0)
        hours = [(hour_of_week + delta) % 168 for delta in range(-radius_hours, radius_hours + 1)]
        placeholders = ",".join("?" * len(hours))
        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT lat_bucket, lon_bucket, SUM(count) as total
                FROM activity_grid
                WHERE pet_id = ? AND hour_of_week IN ({placeholders})
                GROUP BY lat_bucket, lon_bucket
                ORDER BY total DESC
            """, [pet_id] + hours).fetchall()
        return [(r["lat_bucket"], r["lon_bucket"], r["total"]) for r in rows]

    def prune_old_data(self, pet_id: str, keep_days: int = 90):
        """Remove location events older than keep_days to manage disk usage."""
        cutoff = (datetime.utcnow() - timedelta(days=keep_days)).isoformat()
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM location_events WHERE pet_id = ? AND timestamp < ?",
                (pet_id, cutoff)
            )

    # ── Alerts ─────────────────────────────────────────────────────────────

    def insert_alert(self, alert: AlertRecord):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO alerts
                    (pet_id, timestamp, level, message, triggers, lat, lon)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                alert.pet_id,
                alert.timestamp.isoformat(),
                alert.level.value,
                alert.message,
                json.dumps(alert.triggers, ensure_ascii=False),
                alert.lat,
                alert.lon,
            ))

    def get_last_alert(self, pet_id: str) -> Optional[AlertRecord]:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT * FROM alerts
                WHERE pet_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (pet_id,)).fetchone()
        if not row:
            return None
        return AlertRecord(
            pet_id=row["pet_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            level=AlertLevel(row["level"]),
            message=row["message"],
            triggers=json.loads(row["triggers"] or "[]"),
            lat=row["lat"],
            lon=row["lon"],
            acknowledged=bool(row["acknowledged"]),
        )

    def get_alerts(self, pet_id: str, limit: int = 50) -> List[dict]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM alerts
                WHERE pet_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (pet_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def acknowledge_alert(self, alert_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,)
            )
