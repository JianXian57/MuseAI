#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI public Task Tool.

Recommended location:
    MuseAI/tools/task_ops/task_tool.py

Responsibilities
----------------
- Expose public Daily Task operations.
- Convert service results/errors into the unified MuseAI Tool protocol.

This module does not:
- parse CLI arguments;
- print output;
- write lifecycle logs;
- directly manipulate Task JSON.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from common.result import failure, success
from common.time_service import (
    InvalidTimezoneError,
    InvalidUserConfigError,
    TimeServiceError,
    TimezoneNotConfiguredError,
    UserConfigNotFoundError,
    UserConfigReadError,
)

from task_ops.daily_service import (
    DailyDateMismatchError,
    DailyFileNotFoundError,
    DailyTaskError,
    InvalidDailyDateError,
    InvalidDailyDocumentError,
    InvalidDailySourceError,
    add_daily as service_add_daily,
    ensure_daily as service_ensure_daily,
    read_daily as service_read_daily,
    remove_daily as service_remove_daily,
    set_daily_status as service_set_daily_status,
    update_daily as service_update_daily,
)
from task_ops.task_service import (
    DuplicateTaskIdError,
    InvalidTaskDocumentError,
    InvalidTaskIdError,
    TaskNotFoundError,
    TaskReadError,
    TaskServiceError,
    TaskWriteError,
    UnsupportedSchemaVersionError,
)


def _service_failure(
    operation: str,
    exc: Exception,
) -> dict[str, Any]:
    """Map deterministic service exceptions to stable public error codes."""
    mappings: list[tuple[type[BaseException], str, str]] = [
        (
            DailyFileNotFoundError,
            "DAILY_FILE_NOT_FOUND",
            "The Daily Task file does not exist.",
        ),
        (
            InvalidDailyDateError,
            "INVALID_DAILY_DATE",
            "The Daily Task date is invalid.",
        ),
        (
            DailyDateMismatchError,
            "DAILY_DATE_MISMATCH",
            "The Daily Task document date does not match its target date.",
        ),
        (
            InvalidDailySourceError,
            "INVALID_DAILY_SOURCE",
            "The requested Daily Task source is invalid.",
        ),
        (
            UnsupportedSchemaVersionError,
            "UNSUPPORTED_SCHEMA_VERSION",
            "The Task document uses an unsupported schema version.",
        ),
        (
            DuplicateTaskIdError,
            "DUPLICATE_TASK_ID",
            "The Task document contains duplicate Task IDs.",
        ),
        (
            InvalidTaskIdError,
            "INVALID_TASK_ID",
            "The Task ID is invalid for this operation.",
        ),
        (
            TaskNotFoundError,
            "TASK_NOT_FOUND",
            "The requested Task ID was not found.",
        ),
        (
            TaskReadError,
            "TASK_READ_FAILED",
            "MuseAI could not read the Task document.",
        ),
        (
            TaskWriteError,
            "TASK_WRITE_FAILED",
            "MuseAI could not write the Task document.",
        ),
        (
            InvalidDailyDocumentError,
            "INVALID_DAILY_DOCUMENT",
            "The Daily Task document is invalid.",
        ),
        (
            InvalidTaskDocumentError,
            "INVALID_TASK_DOCUMENT",
            "The Task document is invalid.",
        ),
        (
            DailyTaskError,
            "DAILY_TASK_ERROR",
            "The Daily Task service failed.",
        ),
        (
            TaskServiceError,
            "TASK_SERVICE_ERROR",
            "The Task service failed.",
        ),
        (
            UserConfigNotFoundError,
            "USER_CONFIG_NOT_FOUND",
            "MuseAI user configuration file was not found.",
        ),
        (
            TimezoneNotConfiguredError,
            "TIMEZONE_NOT_CONFIGURED",
            "The `timezone` field is missing from the MuseAI user configuration.",
        ),
        (
            InvalidTimezoneError,
            "INVALID_TIMEZONE",
            "The configured IANA timezone could not be resolved.",
        ),
        (
            UserConfigReadError,
            "USER_CONFIG_READ_FAILED",
            "MuseAI could not read the user configuration file.",
        ),
        (
            InvalidUserConfigError,
            "INVALID_USER_CONFIG",
            "MuseAI user configuration is invalid.",
        ),
        (
            TimeServiceError,
            "TIME_SERVICE_ERROR",
            "MuseAI time service failed.",
        ),
    ]

    for error_type, code, message in mappings:
        if isinstance(exc, error_type):
            details: dict[str, Any] = {
                "reason": str(exc),
                "exception": type(exc).__name__,
            }

            if isinstance(exc, UnsupportedSchemaVersionError):
                details.update(
                    {
                        "version": exc.version,
                        "supported_versions": list(exc.supported_versions),
                        "kind": exc.kind,
                    }
                )

            return failure(
                operation,
                code,
                message,
                details,
            )

    return failure(
        operation,
        "TASK_UNEXPECTED_ERROR",
        "The Task Tool failed unexpectedly.",
        {
            "reason": str(exc),
            "exception": type(exc).__name__,
        },
    )


def _run(
    operation: str,
    action: Callable[..., tuple[dict[str, Any], list[str]]],
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        data, warnings = action(**kwargs)
    except Exception as exc:
        return _service_failure(operation, exc)

    return success(
        operation,
        data,
        warnings,
    )


def daily_ensure(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.daily.ensure",
        service_ensure_daily,
        date=date,
        daily_dir=daily_dir,
    )


def daily_read(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.daily.read",
        service_read_daily,
        date=date,
        daily_dir=daily_dir,
    )


def daily_add(
    *,
    title: str,
    description: str = "",
    category: str = "未分类",
    source: str = "manual",
    date: str | None = None,
    meta: dict[str, Any] | None = None,
    daily_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.daily.add",
        service_add_daily,
        title=title,
        description=description,
        category=category,
        source=source,
        date=date,
        meta=meta,
        daily_dir=daily_dir,
    )


def daily_update(
    *,
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    category: str | None = None,
    date: str | None = None,
    daily_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.daily.update",
        service_update_daily,
        task_id=task_id,
        title=title,
        description=description,
        category=category,
        date=date,
        daily_dir=daily_dir,
    )


def daily_status(
    *,
    task_id: str,
    status: str,
    date: str | None = None,
    daily_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.daily.status",
        service_set_daily_status,
        task_id=task_id,
        status=status,
        date=date,
        daily_dir=daily_dir,
    )


def daily_remove(
    *,
    task_id: str,
    date: str | None = None,
    daily_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.daily.remove",
        service_remove_daily,
        task_id=task_id,
        date=date,
        daily_dir=daily_dir,
    )
