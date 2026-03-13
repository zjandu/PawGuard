"""
PawGuard core data models.
All data flowing through the system is represented by these dataclasses.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from enum import Enum


class AlertLevel(str, Enum):
    SAFE = "SAFE"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class PetState(str, Enum):
    HOME = "HOME"
    EXPLORING = "EXPLORING"
    STILL_FAMILIAR = "STILL_FAMILIAR"
    STILL_UNFAMILIAR = "STILL_UNFAMILIAR"
    UNKNOWN = "UNKNOWN"


@dataclass
class LocationEvent:
    pet_id: str
    timestamp: datetime
    lat: float
    lon: float
    accuracy_meters: float = 50.0
    battery_pct: Optional[int] = None
    source: str = "unknown"
    speed_kmh: Optional[float] = None
    raw: Optional[dict] = None


@dataclass
class RiskAssessment:
    level: AlertLevel
    pet_state: PetState
    triggers: List[str]
    suggested_action: str
    confidence: str
    predicted_lat: Optional[float] = None
    predicted_lon: Optional[float] = None
    minutes_since_last_movement: int = 0
    distance_from_home_m: float = 0.0
    is_in_familiar_zone: bool = True


@dataclass
class HomeZone:
    lat: float
    lon: float
    radius_meters: float


@dataclass
class PetConfig:
    id: str
    name: str
    species: str = "cat"
    home_zone: Optional[HomeZone] = None


@dataclass
class AlertRecord:
    pet_id: str
    timestamp: datetime
    level: AlertLevel
    message: str
    triggers: List[str]
    lat: Optional[float] = None
    lon: Optional[float] = None
    acknowledged: bool = False
