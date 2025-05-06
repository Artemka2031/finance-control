# Bot/utils/logging.py
from loguru import logger


def configure_logger(prefix: str, color: str):
    """Configure loguru logger with a specific prefix and color."""
    # Only add handler if not already configured
    if not logger._core.handlers:
        logger.add(
            lambda msg: print(msg, end=""),
            level="DEBUG",
            format=(
                f"<{color}>{{time:YYYY-MM-DD HH:mm:ss.SSS}}</{color}> | "
                "<b>{level:<8}</b> | "
                "<cyan>{name}:{function}:{line}</cyan> | "
                f"{prefix} <b>{{message}}</b>"
            ),
            colorize=True
        )
    return logger
