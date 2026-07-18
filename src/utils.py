from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .constants import LOG_DIR, LOG_FILE


def setup_logging(debug: bool = False) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if debug else logging.INFO

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=5)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def clamp(value: int, minimum: int = 0, maximum: int = 100) -> int:
    return max(minimum, min(maximum, value))

