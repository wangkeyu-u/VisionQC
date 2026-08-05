from __future__ import annotations

import logging
import signal
import time

from app.main import app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("visionqc.worker")
running = True


def _stop(_signum: int, _frame: object) -> None:
    global running
    running = False


def run_forever() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    service = app.state.service
    factory = app.state.session_factory
    settings = app.state.settings
    logger.info("VisionQC outbox worker started")
    while running:
        processed = False
        with factory() as session:
            try:
                processed = service.process_one_outbox(session)
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("outbox event processing failed")
        if not processed:
            time.sleep(settings.worker_poll_seconds)
    logger.info("VisionQC outbox worker stopped")


if __name__ == "__main__":
    run_forever()
