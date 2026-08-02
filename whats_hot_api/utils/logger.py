import sys

from loguru import logger

from whats_hot_api.config import config

# Remove default handler
logger.remove()

# Console handler
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="DEBUG",
    colorize=True,
)

# File handlers
if config.USE_LOG_FILE:
    logger.add(
        "logs/logger.log",
        rotation="1 MB",
        retention=1,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="INFO",
    )
    logger.add(
        "logs/error.log",
        rotation="1 MB",
        retention=1,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="ERROR",
    )
