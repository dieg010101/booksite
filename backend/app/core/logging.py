"""
Structured logging configuration.

Call `setup_logging()` once at app startup.
- Development: human-readable format with colors
- Production: JSON-structured logs for log aggregation (ELK, Datadog, etc.)
"""

import logging
import sys

from app.core.config import DEBUG, ENVIRONMENT


def setup_logging() -> None:
    """Configure logging for the application."""
    log_level = logging.DEBUG if DEBUG else logging.INFO

    if ENVIRONMENT == "development":
        # Human-readable format for dev
        fmt = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
        logging.basicConfig(
            level=log_level,
            format=fmt,
            datefmt="%H:%M:%S",
            stream=sys.stdout,
        )
        # Quiet down SQLAlchemy in dev (it's very chatty with echo=True)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    else:
        # Structured format for production
        fmt = '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'
        logging.basicConfig(
            level=log_level,
            format=fmt,
            datefmt="%Y-%m-%dT%H:%M:%S",
            stream=sys.stdout,
        )
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging configured for {ENVIRONMENT} environment (level={logging.getLevelName(log_level)})"
    )
