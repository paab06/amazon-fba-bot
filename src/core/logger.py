# src/core/logger.py
import structlog
import logging


def setup_logging(level: str = "INFO") -> None:
    """
    Configura structlog para output JSON en producción
    y output legible (consola) en desarrollo.
    """
    # PrintLoggerFactory no expone `.name`; no usar add_logger_name de stdlib aquí.
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),   # cambiar a JSONRenderer en prod
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )