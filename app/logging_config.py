import logging
import time
from datetime import UTC, datetime
from itertools import count
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
    date_part = datetime.now(UTC).strftime("%Y-%m-%d")
    seq = next(_run_id_seq)
    return f"RUN-{date_part}-{seq:03d}"


_run_id_seq = count(1)


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
