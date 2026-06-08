import logging
import os
import sys
import builtins
from datetime import datetime

# Force built-in io, not pandas.io
io = builtins.__import__('io')

def get_logger(name: str) -> logging.Logger:
    """
    Returns a configured logger that writes to both console and a log file.
    Use this at the top of every module:
        logger = get_logger(__name__)
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler - force UTF-8 so arrow characters work on Windows
    console = logging.StreamHandler(
        io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", write_through=True)
    )
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler - writes to logs/ folder
    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger