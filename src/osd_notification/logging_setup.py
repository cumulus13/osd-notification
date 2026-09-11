#!/usr/bin/env python3

# File: src/osd_notification/logging_setup.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Centralized logger factory. Prefers `richcolorlog` if present,
#              falls back to a rotating file handler + stream handler.
# License: MIT


from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _fallback_logger(name: str, log_dir: Path) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level_name = os.getenv("OSD_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s - %(name)s - [%(levelname)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / f"{name}.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError:
        # Non-fatal: continue with stream-only logging if the log dir is unwritable.
        logger.warning("Could not create log directory %s; file logging disabled.", log_dir)

    logger.propagate = False
    return logger


def get_logger(name: str = "OSDNotifier", log_dir: Path | None = None) -> logging.Logger:
    """Return a configured logger, preferring `richcolorlog` when installed."""
    try:
        from richcolorlog import setup_logging  # type: ignore

        return setup_logging(name)
    except Exception:
        base_dir = log_dir or (Path.home() / f".{name.lower()}" / "logs")
        return _fallback_logger(name, base_dir)
