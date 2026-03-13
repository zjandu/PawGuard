# Contributing to PawGuard

## Adding a new tracker connector

1. Create `pawguard/connectors/your_tracker.py`
2. Subclass `BaseConnector`
3. Implement `start()`, `stop()`
4. Call `self.on_location_received(event)` with a `LocationEvent`
5. Add your connector to `pawguard/connectors/__init__.py`
6. Add a config block in `config.example.yaml`
7. Handle it in `orchestrator.py → _build_connector()`
8. Submit a PR with a short description of the tracker hardware

The connector must:
- Be thread-safe
- Not crash silently (log errors, keep running)
- Only forward genuinely new GPS fixes (check timestamp)
- Fill `LocationEvent.accuracy_meters` as accurately as possible

## Running locally (no Docker)

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
# Edit config.yaml
python -m pawguard.main
```

## Running tests

```bash
pip install pytest
pytest tests/
```
