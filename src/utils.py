"""
utils.py — shared utilities for the CPO Competitiveness Monitor ETL pipeline.

Usage in every module:
    from src.utils import get_logger
    logger = get_logger(__name__)
"""

import io as _io
import logging
import os
import sys
from datetime import datetime


def get_logger(name: str = __name__) -> logging.Logger:
    """
    Return a configured logger that writes to both the console and a dated log file.

    Args:
        name: Logger name — pass __name__ from the calling module so each file
              gets its own named logger (e.g. "src.extract.extract_worldbank").
              Defaults to this module's name when called without arguments, but
              callers should always pass __name__ explicitly.

    Returns:
        logging.Logger: Configured logger instance. Handlers are only added once
                        per name, so calling get_logger(__name__) multiple times
                        in the same module is safe.

    Example:
        logger = get_logger(__name__)
        logger.info("worldbank: 137 rows extracted")
        logger.warning("fao: sfvrsn URL param may have rotated — check if 404")
        logger.error("usda: download failed: %s", exc)
    """
    logger = logging.getLogger(name)

    # Guard: don't add handlers a second time (e.g. on module reimport in notebooks)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Console handler ──────────────────────────────────────────────────────
    # Force UTF-8 so arrow characters (→) and ellipsis (…) render correctly on
    # Windows terminals that default to cp1252.
    console_stream = _io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", write_through=True
    )
    console_handler = logging.StreamHandler(console_stream)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # ── File handler ─────────────────────────────────────────────────────────
    # One log file per pipeline run, named by timestamp so runs don't overwrite
    # each other. Folder is created if it doesn't exist.
    os.makedirs("logs", exist_ok=True)
    log_path = f"logs/pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger