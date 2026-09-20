import logging

import structlog

from app.redaction import Redactor, redact_event_dict


def configure_logging(level: str, redactor: Redactor | None = None) -> None:
    logging.basicConfig(format="%(message)s", level=level, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            redact_event_dict(redactor or Redactor()),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
