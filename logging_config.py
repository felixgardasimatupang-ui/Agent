"""
Structured logging configuration for the AI Swarm Orchestrator.
Provides JSON-formatted logs with context and correlation IDs.
"""
import logging
import json
import sys
from datetime import datetime
from typing import Optional, Dict, Any
from contextvars import ContextVar
import uuid


# Context variable for correlation ID
correlation_id: ContextVar[str] = ContextVar(
    "correlation_id", default=""
)


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add correlation ID if present
        corr_id = correlation_id.get("")
        if corr_id:
            log_entry["correlation_id"] = corr_id

        # Add exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }

        # Add extra fields
        if hasattr(record, "extra_data"):
            log_entry["extra"] = record.extra_data

        return json.dumps(log_entry, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter for console output."""

    COLORS = {
        "DEBUG": "\033[36m",      # Cyan
        "INFO": "\033[32m",       # Green
        "WARNING": "\033[33m",    # Yellow
        "ERROR": "\033[31m",      # Red
        "CRITICAL": "\033[1;31m", # Bold Red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        reset = self.RESET

        timestamp = datetime.now().strftime("%H:%M:%S")
        level = f"{color}{record.levelname:8}{reset}"
        logger_name = record.name.split(".")[-1]
        message = record.getMessage()

        # Add correlation ID if present
        corr_id = correlation_id.get("")
        corr_str = f" [{corr_id[:8]}]" if corr_id else ""

        return f"{timestamp} {level} {logger_name}{corr_str}: {message}"


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """
    Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Use JSON formatting for logs
        log_file: Optional file path for log output

    Returns:
        Configured root logger
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    if json_format:
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console_handler)

    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(file_handler)

    return root_logger


def generate_correlation_id() -> str:
    """Generate a new correlation ID."""
    return str(uuid.uuid4())[:12]


def set_correlation_id(cid: str):
    """Set the correlation ID for the current context."""
    correlation_id.set(cid)


def get_correlation_id() -> str:
    """Get the current correlation ID."""
    return correlation_id.get("")


class ContextLogger:
    """Logger that automatically adds context to log entries."""

    def __init__(self, logger: logging.Logger, context: Dict[str, Any]):
        self.logger = logger
        self.context = context

    def _log(self, level: int, msg: str, **kwargs):
        extra = kwargs.get("extra", {})
        extra["extra_data"] = {**self.context, **extra.get("extra_data", {})}
        kwargs["extra"] = extra
        self.logger.log(level, msg, **kwargs)

    def debug(self, msg: str, **kwargs):
        self._log(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs):
        self._log(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        self._log(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs):
        self._log(logging.ERROR, msg, **kwargs)

    def critical(self, msg: str, **kwargs):
        self._log(logging.CRITICAL, msg, **kwargs)


def get_logger(
    name: str,
    context: Optional[Dict[str, Any]] = None,
) -> logging.Logger:
    """
    Get a named logger with optional context.

    Args:
        name: Logger name (usually module name)
        context: Optional context to add to all log entries

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    if context:
        return ContextLogger(logger, context)

    return logger
