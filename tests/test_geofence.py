"""Tests for the geofence engine."""
import pytest
from pawguard.engine.geofence import haversine_meters, is_inside_zone, compute_speed_kmh
from pawguard.models import HomeZone
from datetime import datetime, timedelta


def test_haversine_known_distance():
    # Tiananmen Square to Forbidden City: ~940m
    dist = haversine_meters(39.9087, 116.3975, 39.9163, 116.3972)
    assert 800 < dist < 1100, f"Expected ~940m, got {dist:.0f}m"


def test_haversine_zero():
    dist = haversine_meters(39.9042, 116.4074, 39.9042, 116.4074)
    assert dist == 0.0


def test_inside_zone():
    home = HomeZone(lat=39.9042, lon=116.4074, radius_meters=150)
    # Same point — inside
    assert is_inside_zone(39.9042, 116.4074, home)
    # 200m away — outside
    assert not is_inside_zone(39.9060, 116.4074, home)


def test_speed_calculation():
    t1 = datetime(2024, 1, 1, 12, 0, 0)
    t2 = t1 + timedelta(seconds=3600)  # 1 hour later
    # ~111km between these points (1 degree lat)
    speed = compute_speed_kmh(0.0, 0.0, t1, 1.0, 0.0, t2)
    assert 109 < speed < 113, f"Expected ~111 km/h, got {speed:.1f}"
