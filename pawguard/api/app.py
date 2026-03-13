"""
FastAPI REST API.

Endpoints:
  GET  /                          → Health check
  GET  /api/pets                  → List all pets and their last known status
  GET  /api/pets/{pet_id}/location → Last N location events
  GET  /api/pets/{pet_id}/alerts   → Recent alerts
  POST /api/pets/{pet_id}/alerts/{alert_id}/ack  → Acknowledge alert
  POST /webhook/location/{pet_id}  → Receive location from external source
  GET  /api/status                 → System status
"""
import logging
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Orchestrator is injected at startup (see main.py)
_orchestrator = None


def create_app(orchestrator) -> FastAPI:
    global _orchestrator
    _orchestrator = orchestrator

    app = FastAPI(
        title="PawGuard",
        description="AI-powered pet safety monitoring",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def root():
        return {"status": "ok", "service": "PawGuard", "version": "1.0.0"}

    @app.get("/api/pets")
    def list_pets():
        result = []
        for pet in _orchestrator.cfg.pets:
            last_loc = _orchestrator.db.get_last_location(pet.id)
            last_alert = _orchestrator.db.get_last_alert(pet.id)
            data_days = _orchestrator.db.get_data_span_days(pet.id)
            
            result.append({
                "id": pet.id,
                "name": pet.name,
                "species": pet.species,
                "data_days_collected": round(data_days, 1),
                "behavior_model_active": data_days >= _orchestrator.cfg.thresholds.min_behavior_data_days,
                "last_location": _location_to_dict(last_loc) if last_loc else None,
                "last_alert": {
                    "level": last_alert.level.value,
                    "message": last_alert.message,
                    "timestamp": last_alert.timestamp.isoformat(),
                } if last_alert else None,
            })
        return result

    @app.get("/api/pets/{pet_id}/location")
    def get_location(pet_id: str, limit: int = 50):
        _check_pet(pet_id)
        events = _orchestrator.db.get_recent_locations(pet_id, limit=limit)
        return [_location_to_dict(e) for e in events]

    @app.get("/api/pets/{pet_id}/alerts")
    def get_alerts(pet_id: str, limit: int = 50):
        _check_pet(pet_id)
        return _orchestrator.db.get_alerts(pet_id, limit=limit)

    @app.post("/api/pets/{pet_id}/alerts/{alert_id}/ack")
    def acknowledge_alert(pet_id: str, alert_id: int):
        _check_pet(pet_id)
        _orchestrator.db.acknowledge_alert(alert_id)
        return {"acknowledged": True}

    @app.get("/api/status")
    def system_status():
        connectors = {}
        for pet_id, connector in _orchestrator.connectors.items():
            connectors[pet_id] = {
                "running": connector.is_running,
                "type": _orchestrator.cfg.tracker_type,
            }
        return {
            "status": "running",
            "uptime_since": datetime.utcnow().isoformat(),
            "tracker_type": _orchestrator.cfg.tracker_type,
            "pets": len(_orchestrator.cfg.pets),
            "connectors": connectors,
        }

    # ── Webhook endpoint ───────────────────────────────────────────────────

    @app.post("/webhook/location/{pet_id}")
    async def webhook_location(pet_id: str, request: Request):
        """
        Receive location data from any external source.
        
        Supports:
        - PawGuard standard JSON
        - OwnTracks (_type: "location")
        - GPSLogger for Android
        
        Optional: set WEBHOOK_SECRET in config and pass it as
        X-PawGuard-Secret header for basic security.
        """
        _check_pet(pet_id)
        payload = await request.json()

        # Validate secret if configured
        wh_cfg = _orchestrator.cfg.webhook
        if wh_cfg and wh_cfg.secret:
            secret_header = request.headers.get("X-PawGuard-Secret", "")
            if secret_header != wh_cfg.secret:
                raise HTTPException(status_code=403, detail="Invalid webhook secret")

        connector = _orchestrator.get_webhook_connector(pet_id)
        if not connector:
            raise HTTPException(status_code=400, detail="No webhook connector for this pet")

        success = connector.handle_payload(payload)
        if not success:
            raise HTTPException(status_code=422, detail="Could not parse location payload")

        return {"received": True}

    # ── Static frontend ────────────────────────────────────────────────────
    try:
        app.mount("/static", StaticFiles(directory="frontend"), name="static")

        @app.get("/dashboard")
        def dashboard():
            return FileResponse("frontend/index.html")
    except Exception:
        pass  # Frontend dir not found — API-only mode

    return app


def _check_pet(pet_id: str):
    if pet_id not in _orchestrator.pets:
        raise HTTPException(status_code=404, detail=f"Pet '{pet_id}' not found")


def _location_to_dict(event) -> dict:
    return {
        "pet_id": event.pet_id,
        "timestamp": event.timestamp.isoformat(),
        "lat": event.lat,
        "lon": event.lon,
        "accuracy_meters": event.accuracy_meters,
        "battery_pct": event.battery_pct,
        "source": event.source,
        "speed_kmh": event.speed_kmh,
    }
