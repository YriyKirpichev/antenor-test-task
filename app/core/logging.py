import json
import logging
import logging.config
from contextvars import ContextVar
from typing import Any

from app.core.config import settings

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"asctime", "message", "taskName"}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        payload.update(
            {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        )
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    formatter = "json" if settings.LOG_JSON else "console"

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "request_id": {"()": RequestIdFilter},
            },
            "formatters": {
                "console": {
                    "format": (
                        "%(asctime)s %(levelname)-8s [%(request_id)s] "
                        "%(name)s: %(message)s"
                    ),
                    "datefmt": "%H:%M:%S",
                },
                "json": {"()": JsonFormatter},
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": formatter,
                    "filters": ["request_id"],
                },
            },
            "root": {
                "handlers": ["default"],
                "level": settings.LOG_LEVEL,
            },
            "loggers": {
                "uvicorn.access": {"handlers": [], "propagate": False},
                "uvicorn.error": {
                    "handlers": ["default"],
                    "level": settings.LOG_LEVEL,
                    "propagate": False,
                },
                "sqlalchemy.engine": {
                    "level": "INFO" if settings.DB_ECHO else "WARNING",
                    "propagate": True,
                },
                "alembic": {"level": "INFO", "propagate": True},
            },
        }
    )
