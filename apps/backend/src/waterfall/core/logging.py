import logging
import logging.config


def configure_logging(level: str = "INFO") -> None:
    log_level = level.upper()

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                    "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s",
                }
            },
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "level": log_level,
                }
            },
            "root": {
                "handlers": ["stdout"],
                "level": log_level,
            },
        }
    )
