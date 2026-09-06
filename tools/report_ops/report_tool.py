#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI public Report Tool.

Recommended location:
    MuseAI/tools/report_ops/report_tool.py

Responsibilities
----------------
- Expose deterministic Report operations through the MuseAI Tool protocol.
- Convert Report / Task / Time service failures into stable public errors.

This module does not:
- parse CLI arguments;
- print output;
- write lifecycle logs;
- generate natural-language reports;
- modify Task data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common.result import failure, success
from common.time_service import TimeServiceError
from report_ops.daily_report_service import (
    DailyReportServiceError,
    build_daily_report as service_build_daily_report,
)
from task_ops.task_service import TaskServiceError


def _report_failure(
    operation: str,
    exc: Exception,
) -> dict[str, Any]:
    if isinstance(exc, TimeServiceError):
        return failure(
            operation,
            "REPORT_TIME_ERROR",
            "MuseAI time context could not be resolved for the report.",
            f"{type(exc).__name__}: {exc}",
        )

    if isinstance(exc, TaskServiceError):
        return failure(
            operation,
            "REPORT_TASK_DATA_ERROR",
            "Task data could not be read for the report.",
            f"{type(exc).__name__}: {exc}",
        )

    if isinstance(exc, DailyReportServiceError):
        return failure(
            operation,
            "REPORT_DATA_ERROR",
            "Daily Report snapshot could not be built from the available data.",
            f"{type(exc).__name__}: {exc}",
        )

    return failure(
        operation,
        "REPORT_UNEXPECTED_ERROR",
        "The Report Tool failed unexpectedly.",
        f"{type(exc).__name__}: {exc}",
    )


def daily_report(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
    long_dir: str | Path | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return one deterministic Daily Report snapshot."""
    operation = "report.daily"

    try:
        data, warnings = service_build_daily_report(
            date,
            daily_dir=daily_dir,
            long_dir=long_dir,
            config_path=config_path,
        )
    except Exception as exc:
        return _report_failure(operation, exc)

    return success(
        operation,
        data,
        warnings,
    )
