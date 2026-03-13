"""
Geofence and distance utilities.
Uses the Haversine formula — no external libraries required.
"""
import math
from typing import Tuple
from pawguard.models import HomeZone


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance in meters between two GPS coordinates.
    Haversine formula: accurate to within ~0.3% for distances < 1000km.
    """
    R = 6_371_000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def is_inside_zone(lat: float, lon: float, zone: HomeZone) -> bool:
    dist = haversine_meters(lat, lon, zone.lat, zone.lon)
    return dist <= zone.radius_meters


def distance_from_home(lat: float, lon: float, home: HomeZone) -> float:
    return haversine_meters(lat, lon, home.lat, home.lon)


def compute_speed_kmh(
    lat1: float, lon1: float, t1,
    lat2: float, lon2: float, t2,
) -> float:
    """Compute speed between two fixes. Returns km/h."""
    dist_m = haversine_meters(lat1, lon1, lat2, lon2)
    dt_s = (t2 - t1).total_seconds()
    if dt_s <= 0:
        return 0.0
    return (dist_m / dt_s) * 3.6
