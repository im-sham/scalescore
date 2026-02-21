"""
Structured logging configuration for ScaleScore.

This module implements ADR-0010: Structured Logging and Observability.

Features:
- Structured JSON logging in production
- Pretty console output in development
- Automatic sensitive data filtering
- Context binding for correlation IDs
- Application metadata in all logs
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from scalescore.config import settings

SENSITIVE_FIELDS = frozenset({
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "credential",
    "private_key",
    "access_token",
    "refresh_token",
    "jwt",
    "ssn",
    "credit_card",
    "card_number",
})


def _is_sensitive(key: str) -> bool:
    """Check if a key name indicates sensitive data."""
    key_lower = key.lower()
    return any(pattern in key_lower for pattern in SENSITIVE_FIELDS)


def _recursive_filter(data: Any) -> Any:
    """Recursively filter sensitive fields from data structures."""
    if isinstance(data, dict):
        return {
            k: "[REDACTED]" if _is_sensitive(k) else _recursive_filter(v)
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [_recursive_filter(item) for item in data]
    return data


def _filter_sensitive_data(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Structlog processor to filter sensitive data from logs."""
    return _recursive_filter(event_dict)


def _add_app_context(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add application context to all log entries."""
    event_dict["service"] = "scalescore"
    event_dict["version"] = settings.app_version
    event_dict["environment"] = settings.environment
    return event_dict


def setup_logging() -> None:
    """
    Configure structured logging for the application.

    Call this once at application startup.
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _add_app_context,
        _filter_sensitive_data,
    ]

    if settings.is_development() or settings.log_format == "text":
        final_processors: list[Processor] = [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]
        formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
        )
    else:
        final_processors = [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]
        formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    for noisy_logger in ["uvicorn", "uvicorn.access", "httpx", "httpcore"]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    structlog.configure(
        processors=shared_processors + final_processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """
    Bind context variables to the current context.

    These will be included in all subsequent log entries.
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_context(*keys: str) -> None:
    """Remove context variables from the current context."""
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context() -> None:
    """Clear all context variables."""
    structlog.contextvars.clear_contextvars()
