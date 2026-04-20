from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger as _logger


logger = _logger


def _build_filter(enabled_areas: set[str] | None):
    if enabled_areas is None:
        return lambda record: True

    normalized_areas = {area.strip().lower() for area in enabled_areas}

    def area_filter(record: dict) -> bool:
        area = str(record["extra"].get("area", "")).strip().lower()
        return area in normalized_areas

    return area_filter


def configure_logging(
        *,
        console_level: str = "INFO",
        file_level: str = "DEBUG",
        log_file_path: str = "logs/app.log",
        enabled_areas: set[str] | None = None,
) -> None:
    logger.remove()

    area_filter = _build_filter(enabled_areas)

    logger.add(
        sys.stderr,
        level=console_level.upper(),
        filter=area_filter,
        colorize=True,
        backtrace=False,
        diagnose=False,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{extra[area]}</cyan> | "
            "<white>{name}:{function}:{line}</white> | "
            "<level>{message}</level>"
        ),
    )

    log_path = Path(log_file_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_path,
        level=file_level.upper(),
        filter=area_filter,
        encoding="utf-8",
        backtrace=False,
        diagnose=False,
        rotation="10 MB",
        retention=5,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{extra[area]} | "
            "{process.id}:{thread.id} | "
            "{name}:{function}:{line} | "
            "{message}"
        ),
    )


def get_logger(area: str):
    return logger.bind(area=area)