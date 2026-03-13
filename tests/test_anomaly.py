"""Tests for anomaly detection logic."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from pawguard.models import LocationEvent, AlertLevel, PetState, HomeZone
from pawguard.engine.anomaly import AnomalyDetector
from pawguard.config import ThresholdsConfig


def make_event(lat=39.9042, lon=116.4074, minutes_ago=0, battery=80):
    return LocationEvent(
        pet_id="test_cat",
        timestamp=datetime.utcnow() - timedelta(minutes=minutes_ago),
        lat=lat,
        lon=lon,
        accuracy_meters=10.0,
        battery_pct=battery,
        source="test",
    )


def make_detector(pet_is_home=True, familiar=True, still_minutes=0):
    db = MagicMock()
    behavior = MagicMock()
    behavior.is_familiar_location.return_value = (familiar, "test")

    # Simulate stillness: return past events N minutes ago at same location
    if still_minutes > 0:
        past = make_event(minutes_ago=still_minutes + 5)
        current = make_event()
        db.get_recent_locations.return_value = [current, past]
    else:
        db.get_recent_locations.return_value = [make_event(), make_event(minutes_ago=1)]

    db.get_data_span_days.return_value = 10.0

    home = HomeZone(lat=39.9042, lon=116.4074, radius_meters=150)
    thresholds = ThresholdsConfig()

    return AnomalyDetector(db=db, behavior=behavior, home=home, thresholds=thresholds)


def test_pet_at_home_is_safe():
    detector = make_detector()
    event = make_event()  # At home coordinates
    assessment = detector.assess(event)
    assert assessment.level == AlertLevel.SAFE


def test_low_battery_raises_notice():
    detector = make_detector()
    event = make_event(battery=15)
    assessment = detector.assess(event)
    assert assessment.level >= AlertLevel.NOTICE
    assert any("battery" in t.lower() for t in assessment.triggers)


def test_critical_stillness_in_unfamiliar_area():
    detector = make_detector(familiar=False, still_minutes=50)
    # Pet at a location 500m from home (outside geofence)
    event = make_event(lat=39.9086, lon=116.4074)  # ~500m north
    assessment = detector.assess(event)
    # Should be at least WARNING; may be CRITICAL depending on stillness calc
    assert assessment.level in (AlertLevel.WARNING, AlertLevel.CRITICAL)
