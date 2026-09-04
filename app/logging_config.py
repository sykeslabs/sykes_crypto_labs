import logging
import time
from datetime import UTC, datetime
import sys


class RunIdFilter(logging.Filter):
    """Injects a run_id into every log record so a pipeline run can be grepped."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id
        return True


def new_run_id() -> str:
    """Generates a run_id unique per invocation.

    Time-based (to the second) rather than an in-process sequence counter:
    each `python -m app.main` run is a separate process, so a counter that
    lives only in memory (e.g. itertools.count starting at 1) resets every
    time and always produces the same id — which is exactly the bug this
    replaced. Seconds-resolution avoids needing a persisted/DB-backed
    counter just to stay unique.
    """
    return f"RUN-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"


def setup_logging(run_id: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("crypto_ai_portfolio")
    logger.setLevel(level)
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | run=%(run_id)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    handler.addFilter(RunIdFilter(run_id))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
