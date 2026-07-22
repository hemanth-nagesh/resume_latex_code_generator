"""Structured JSON logging for observability.

Every log entry carries: timestamp, level, logger name, correlation_id (for
tracing a single request through the pipeline), and arbitrary context fields.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class StructuredLogger(logging.LoggerAdapter):
    """Logger adapter that emits JSON lines with correlation context.

    Usage:
        logger = StructuredLogger(logging.getLogger("server"))
        logger.info("node_complete", node="n3", duration_ms=1420)
        # {"timestamp":"...","level":"INFO","logger":"server","node":"n3",...}
    """

    def __init__(
        self,
        logger: logging.Logger,
        correlation_id: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        base_extra = {"correlation_id": correlation_id}
        if extra:
            base_extra.update(extra)
        super().__init__(logger, base_extra)

    def process(self, msg: Any, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        extra = self.extra.copy() if self.extra else {}
        if "extra" in kwargs:
            extra.update(kwargs.pop("extra"))
        kwargs["extra"] = extra
        return msg, kwargs


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }

        if hasattr(record, "correlation_id"):
            payload["correlation_id"] = record.correlation_id

        if record.msg and isinstance(record.msg, str):
            payload["message"] = record.msg % record.args if record.args else record.msg

        if record.exc_info and record.exc_info[1]:
            payload["error"] = str(record.exc_info[1])

        # Merge any extra context fields
        if hasattr(record, "__dict__"):
            skip = {"name", "msg", "args", "levelname", "levelno", "pathname",
                    "filename", "module", "exc_info", "exc_text", "stack_info",
                    "lineno", "funcName", "created", "msecs", "relativeCreated",
                    "thread", "threadName", "processName", "process",
                    "correlation_id", "message"}
            for key, value in record.__dict__.items():
                if key not in skip and not key.startswith("_"):
                    payload[key] = value

        return json.dumps(payload, default=str)


def configure_root_logger(level: str = "INFO") -> None:
    """Set up JSON logging on stdout. Call once at startup."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
