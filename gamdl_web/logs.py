from __future__ import annotations

import logging
import re
import time
from contextvars import ContextVar
from typing import Any, Callable

import structlog

# Set while a download job runs so gamdl's log lines land in that job's log.
current_job_id: ContextVar[str | None] = ContextVar("current_job_id", default=None)

LogSink = Callable[[str, dict[str, Any]], None]


SECRET_KEYS = {"music_user_token", "media_user_token", "dev_token", "dsid", "token", "authorization", "cookie", "cookies", "password"}
SECRET_TEXT = re.compile(
    r"""(['"]?(?:music_user_token|media[-_]user[-_]token|dev_token|dsid|authorization|password)['"]?\s*[:=]\s*)"""
    r"""('[^']*'|"[^"]*"|[^\s,}]+)""",
    re.IGNORECASE,
)


def redact(value: Any) -> Any:
    """Mask tokens and passwords anywhere in a log event (gamdl logs account info at DEBUG)."""
    if isinstance(value, dict):
        return {
            k: "***" if str(k).lower().replace("-", "_") in SECRET_KEYS else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(redact(v) for v in value)
    if isinstance(value, str):
        return SECRET_TEXT.sub(r"\1***", value)
    return value


def redact_processor(logger: Any, method_name: str, event_dict: dict[str, Any]):
    return redact(event_dict)


def _make_job_dispatcher(sink: LogSink):
    def dispatch(logger: Any, method_name: str, event_dict: dict[str, Any]):
        job_id = current_job_id.get()
        if job_id is None:
            return event_dict

        level = event_dict.get("level", method_name).upper()
        if level in {"INFO", "WARNING", "ERROR", "CRITICAL"}:
            message = str(event_dict.get("event", ""))
        else:
            message = " ".join(
                f"{k}={v}" for k, v in event_dict.items() if k not in {"level"}
            )

        entry = {
            "time": time.time(),
            "level": level,
            "action": event_dict.get("action"),
            "message": message,
        }
        exception = event_dict.get("exception")
        if exception:
            entry["detail"] = exception
        sink(job_id, entry)
        return event_dict

    return dispatch


def configure_logging(level: str, sink: LogSink) -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.format_exc_info,
            redact_processor,
            _make_job_dispatcher(sink),
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level.upper())
        ),
        cache_logger_on_first_use=False,
    )
