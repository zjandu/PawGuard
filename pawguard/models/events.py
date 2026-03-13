"""
PawGuard Core Data Models
标准化数据结构，所有模块共用
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Literal
from enum import Enum


class BehaviorState(str, Enum):
    SLEEPING = "SLEEPING"        # 睡觉/静止在熟悉地
    EXPLORING = "EXPLORING"      # 正常探索
    ACTIVE = "ACTIVE"            # 高速移动
    STATIONARY_UNKNOWN = "STATIONARY_UNKNOWN"  # 静止在陌生地（高风险）
    UNKNOWN = "UNKNOWN"          # 数据不足，无法判断


class RiskLevel(str, Enum):
    SAFE = "SAFE"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class LocationEvent:
    """标准化位置事件，所有Connector输出此格式"""
    timestamp: datetime
    lat: float
    lon: float
    accuracy_meters: float = 50.0
    battery_pct: Optional[int] = None
    speed_kmh: Optional[float] = None
    source: str = "gps"              # "gps" | "ble" | "wifi" | "predicted"
    confidence: float = 1.0          # 0~1，AI预测时填充
    raw_data: dict = field(default_factory=dict)

    def is_valid(self) -> bool:
        return -90 <= self.lat <= 90 and -180 <= self.lon <= 180


@dataclass
class BehaviorPrediction:
    """行为引擎输出"""
    state: BehaviorState
    anomaly_score: float             # 0~1，越高越异常
    in_familiar_zone: bool
    distance_from_home_meters: float
    stationary_duration_seconds: int  # 当前连续静止时长
    recommended_gps_interval_seconds: int
    context: str = ""                # 人类可读的描述


@dataclass
class RiskAssessment:
    """异常检测引擎输出"""
    level: RiskLevel
    confidence: float                # 0~1
    triggers: List[str]              # 触发了哪些规则
    suggested_action: str
    predicted_location: Optional[tuple] = None  # (lat, lon) 如果GPS数据过时
    pet_name: str = ""
    last_seen: Optional[datetime] = None


@dataclass
class PetProfile:
    """宠物档案"""
    name: str
    species: str = "cat"
    home_lat: float = 0.0
    home_lon: float = 0.0
    home_radius_meters: float = 200.0
    safe_zones: List[dict] = field(default_factory=list)  # 额外安全区
