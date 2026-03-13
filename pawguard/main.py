"""
PawGuard entry point.

Usage:
    python -m pawguard.main                    # uses config.yaml in current directory
    python -m pawguard.main --config /path/to/config.yaml
"""
import argparse
import logging
import sys
import signal
import uvicorn

from pawguard.config import load_config
from pawguard.agent.orchestrator import Orchestrator
from pawguard.api.app import create_app


def setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(description="PawGuard — AI pet safety monitoring")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.log_level)

    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("PawGuard v1.0.0 starting")
    logger.info(f"Monitoring {len(cfg.pets)} pet(s): {[p.name for p in cfg.pets]}")
    logger.info(f"Tracker type: {cfg.tracker_type}")
    logger.info("=" * 60)

    orchestrator = Orchestrator(cfg)
    orchestrator.start()

    app = create_app(orchestrator)

    def shutdown(sig, frame):
        logger.info("Shutting down PawGuard...")
        orchestrator.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info(f"API server starting on port {cfg.api_port}")
    logger.info(f"Dashboard available at http://localhost:{cfg.api_port}/dashboard")
    
    uvicorn.run(app, host="0.0.0.0", port=cfg.api_port, log_level="warning")


if __name__ == "__main__":
    main()
