#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI Task Tool exception mapping.

Recommended location:
    MuseAI/tools/task_ops/task_errors.py

Responsibilities
----------------
- Convert deterministic Task/Time service exceptions into stable public
  MuseAI Task Tool failures.
- Keep public error codes and messages centralized.

This module does not execute Task operations or mutate Task data.
"""

from __future__ import annotations

from typing import Any

from common.result import failure
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
)
from task_ops.long_service import (
    InvalidLongCollectionError,
    InvalidLongDeadlineError,
    InvalidLongDocumentError,
    InvalidLongStageError,
    InvalidLongStateError,
    InvalidTimelineEventError,
    LongCollectionConflictError,
    LongFileNotFoundError,
    LongTaskError,
)
from task_ops.standing_service import (
    InvalidStandingDateError,
    InvalidStandingDocumentError,
    InvalidStandingScheduleError,
    StandingFileNotFoundError,
    StandingGenerationDateRegressionError,
    StandingNotScheduledError,
    StandingTaskError,
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


ERROR_MAPPINGS: tuple[tuple[type[BaseException], str, str], ...] = (
    (DailyFileNotFoundError, "DAILY_FILE_NOT_FOUND", "The Daily Task file does not exist."),
    (InvalidDailyDateError, "INVALID_DAILY_DATE", "The Daily Task date is invalid."),
    (DailyDateMismatchError, "DAILY_DATE_MISMATCH", "The Daily Task document date does not match its target date."),
    (InvalidDailySourceError, "INVALID_DAILY_SOURCE", "The requested Daily Task source is invalid."),
    (LongFileNotFoundError, "LONG_FILE_NOT_FOUND", "A required Long Task collection file does not exist."),
    (InvalidLongCollectionError, "INVALID_LONG_COLLECTION", "The requested Long Task collection is invalid."),
    (InvalidLongDeadlineError, "INVALID_LONG_DEADLINE", "The requested Long Task deadline is invalid."),
    (InvalidLongStageError, "INVALID_LONG_STAGE", "The requested Long Task stage is invalid."),
    (InvalidTimelineEventError, "INVALID_TIMELINE_EVENT", "The requested Long Task timeline event is invalid."),
    (InvalidLongStateError, "INVALID_LONG_STATE", "The requested Long Task state transition is invalid."),
    (LongCollectionConflictError, "LONG_COLLECTION_CONFLICT", "The Long Task exists in conflicting active and archived states."),
    (InvalidLongDocumentError, "INVALID_LONG_DOCUMENT", "The Long Task document is invalid."),
    (StandingFileNotFoundError, "STANDING_FILE_NOT_FOUND", "The Standing Task file does not exist."),
    (InvalidStandingDateError, "INVALID_STANDING_DATE", "The Standing Task target date is invalid."),
    (InvalidStandingScheduleError, "INVALID_STANDING_SCHEDULE", "The Standing Task schedule is invalid."),
    (StandingNotScheduledError, "STANDING_NOT_SCHEDULED", "The Standing Task is not scheduled for the requested date."),
    (StandingGenerationDateRegressionError, "STANDING_GENERATION_DATE_REGRESSION", "The Standing generation date cannot move backward."),
    (InvalidStandingDocumentError, "INVALID_STANDING_DOCUMENT", "The Standing Task document is invalid."),
    (UnsupportedSchemaVersionError, "UNSUPPORTED_SCHEMA_VERSION", "The Task document uses an unsupported schema version."),
    (DuplicateTaskIdError, "DUPLICATE_TASK_ID", "The Task document contains duplicate Task IDs."),
    (InvalidTaskIdError, "INVALID_TASK_ID", "The Task ID is invalid for this operation."),
    (TaskNotFoundError, "TASK_NOT_FOUND", "The requested Task ID was not found."),
    (TaskReadError, "TASK_READ_FAILED", "MuseAI could not read the Task document."),
    (TaskWriteError, "TASK_WRITE_FAILED", "MuseAI could not write the Task document."),
    (InvalidDailyDocumentError, "INVALID_DAILY_DOCUMENT", "The Daily Task document is invalid."),
    (InvalidTaskDocumentError, "INVALID_TASK_DOCUMENT", "The Task document is invalid."),
    (DailyTaskError, "DAILY_TASK_ERROR", "The Daily Task service failed."),
    (LongTaskError, "LONG_TASK_ERROR", "The Long Task service failed."),
    (StandingTaskError, "STANDING_TASK_ERROR", "The Standing Task service failed."),
    (TaskServiceError, "TASK_SERVICE_ERROR", "The Task service failed."),
    (UserConfigNotFoundError, "USER_CONFIG_NOT_FOUND", "MuseAI user configuration file was not found."),
    (TimezoneNotConfiguredError, "TIMEZONE_NOT_CONFIGURED", "The `timezone` field is missing from the MuseAI user configuration."),
    (InvalidTimezoneError, "INVALID_TIMEZONE", "The configured IANA timezone could not be resolved."),
    (UserConfigReadError, "USER_CONFIG_READ_FAILED", "MuseAI could not read the user configuration file."),
    (InvalidUserConfigError, "INVALID_USER_CONFIG", "MuseAI user configuration is invalid."),
    (TimeServiceError, "TIME_SERVICE_ERROR", "MuseAI time service failed."),
)


def map_task_exception(
    operation: str,
    exc: Exception,
) -> dict[str, Any]:
    """Map one service exception to the stable Task Tool failure contract."""
    for error_type, code, message in ERROR_MAPPINGS:
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
