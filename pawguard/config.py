"""
Configuration loader. Reads config.yaml and environment variable overrides.
"""
import os
import yaml
from typing import Optional, List
from dataclasses import dataclass
from pawguard.models import HomeZone, PetConfig


@dataclass
class TractiveConfig:
    email: str
    password: str
    tracker_id: str
    poll_interval_seconds: int = 60


@dataclass
class MQTTConfig:
    host: str
    port: int = 1883
    topic: str = "pawguard/location"
    username: Optional[str] = None
    password: Optional[str] = None


@dataclass
class WebhookConfig:
    # Webhook connector: PawGuard exposes a POST endpoint
    # Any tracker/IFTTT/Zapier can POST location data to it
    path: str = "/webhook/location"
    secret: Optional[str] = None


@dataclass
class TelegramConfig:
    enabled: bool
    bot_token: str
    chat_id: str


@dataclass
class AlertsConfig:
    telegram: Optional[TelegramConfig] = None
    # Deduplicate: don't re-alert at same level within N minutes
    dedup_minutes: int = 15


@dataclass
class ThresholdsConfig:
    stillness_warning_minutes: int = 20
    stillness_critical_minutes: int = 45
    geofence_radius_meters: float = 300.0
    familiar_zone_radius_meters: float = 30.0
    min_behavior_data_days: int = 3
    low_battery_warning_pct: int = 20


@dataclass
class AppConfig:
    pets: List[PetConfig]
    home: HomeZone
    tracker_type: str                # "tractive" | "mqtt" | "webhook"
    thresholds: ThresholdsConfig
    alerts: AlertsConfig
    tractive: Optional[TractiveConfig] = None
    mqtt: Optional[MQTTConfig] = None
    webhook: Optional[WebhookConfig] = None
    api_port: int = 8000
    log_level: str = "INFO"
    data_dir: str = "./data"


def load_config(path: str = "config.yaml") -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    # Allow env overrides for secrets (safer in Docker)
    def env_or(val, env_key):
        return os.environ.get(env_key, val)

    home_raw = raw["home"]
    home = HomeZone(
        lat=float(home_raw["lat"]),
        lon=float(home_raw["lon"]),
        radius_meters=float(home_raw.get("radius_meters", 150)),
    )

    pets = []
    for p in raw.get("pets", []):
        pets.append(PetConfig(
            id=p["id"],
            name=p["name"],
            species=p.get("species", "cat"),
            home_zone=home,
        ))

    thresh_raw = raw.get("thresholds", {})
    thresholds = ThresholdsConfig(
        stillness_warning_minutes=thresh_raw.get("stillness_warning_minutes", 20),
        stillness_critical_minutes=thresh_raw.get("stillness_critical_minutes", 45),
        geofence_radius_meters=thresh_raw.get("geofence_radius_meters", 300.0),
        familiar_zone_radius_meters=thresh_raw.get("familiar_zone_radius_meters", 30.0),
        min_behavior_data_days=thresh_raw.get("min_behavior_data_days", 3),
        low_battery_warning_pct=thresh_raw.get("low_battery_warning_pct", 20),
    )

    alerts_raw = raw.get("alerts", {})
    tg_raw = alerts_raw.get("telegram", {})
    telegram = TelegramConfig(
        enabled=tg_raw.get("enabled", False),
        bot_token=env_or(tg_raw.get("bot_token", ""), "TELEGRAM_BOT_TOKEN"),
        chat_id=env_or(tg_raw.get("chat_id", ""), "TELEGRAM_CHAT_ID"),
    ) if tg_raw.get("enabled") else None

    alerts = AlertsConfig(
        telegram=telegram,
        dedup_minutes=alerts_raw.get("dedup_minutes", 15),
    )

    tracker_type = raw.get("tracker", {}).get("type", "webhook")
    tractive_cfg = None
    mqtt_cfg = None
    webhook_cfg = None

    tracker_raw = raw.get("tracker", {})
    if tracker_type == "tractive":
        tr = tracker_raw.get("tractive", {})
        tractive_cfg = TractiveConfig(
            email=env_or(tr.get("email", ""), "TRACTIVE_EMAIL"),
            password=env_or(tr.get("password", ""), "TRACTIVE_PASSWORD"),
            tracker_id=env_or(tr.get("tracker_id", ""), "TRACTIVE_TRACKER_ID"),
            poll_interval_seconds=tr.get("poll_interval_seconds", 60),
        )
    elif tracker_type == "mqtt":
        mq = tracker_raw.get("mqtt", {})
        mqtt_cfg = MQTTConfig(
            host=mq.get("host", "localhost"),
            port=mq.get("port", 1883),
            topic=mq.get("topic", "pawguard/location"),
            username=mq.get("username"),
            password=mq.get("password"),
        )
    elif tracker_type == "webhook":
        wh = tracker_raw.get("webhook", {})
        webhook_cfg = WebhookConfig(
            path=wh.get("path", "/webhook/location"),
            secret=env_or(wh.get("secret"), "WEBHOOK_SECRET"),
        )

    return AppConfig(
        pets=pets,
        home=home,
        tracker_type=tracker_type,
        thresholds=thresholds,
        alerts=alerts,
        tractive=tractive_cfg,
        mqtt=mqtt_cfg,
        webhook=webhook_cfg,
        api_port=int(raw.get("api_port", 8000)),
        log_level=raw.get("log_level", "INFO"),
        data_dir=raw.get("data_dir", "./data"),
    )
