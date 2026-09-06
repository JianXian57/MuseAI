#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unified read-only Task facade for MuseAI internal programs.

Recommended location:
    MuseAI/tools/task_ops/task_read_service.py

Purpose
-------
Provide one program-facing read entry point for validated Daily, Long, and
Standing Task data.

This facade reuses the authoritative kind-specific services:
- daily_service.read_daily()
- long_service.read_long()
- standing_service.read_standing()

It does not parse Task JSON directly and does not duplicate kind-specific
schema validation.

Boundary
--------
This module:
- reads validated Task data;
- normalizes missing files into `exists=False` when allow_missing=True;
- preserves invalid/corrupt-data failures;
- aggregates warning lists;
- resolves one stable context date for read_task_context();
- discovers the nearest previous Daily collection without parsing it directly.

This module does not:
- write Task data;
- create missing Task files;
- change Task status;
- archive/unarchive;
- generate Standing occurrences;
- calculate Standing due state;
- calculate overdue state;
- perform user-facing query/filter semantics;
- build MuseAI public Tool results;
- parse CLI arguments;
- print output;
- write lifecycle logs.
"""

from __future__ import annotations

from datetime import date as date_type
from pathlib import Path
from typing import Any, Iterable

from common.time_service import get_current_time

from task_ops.daily_service import (
    DailyFileNotFoundError,
    read_daily,
    resolve_daily_path,
)
from task_ops.long_service import (
    ACTIVE_COLLECTION,
    ARCHIVED_COLLECTION,
    LongFileNotFoundError,
    read_long,
    resolve_long_path,
)
from task_ops.standing_service import (
    StandingFileNotFoundError,
    read_standing,
    resolve_standing_path,
)
from task_ops.task_service import TaskReadError, TaskServiceError, validate_date


class TaskReadServiceError(TaskServiceError):
    """Base exception for unified Task read-facade failures."""


class InvalidTaskReadDateError(TaskReadServiceError):
    """The requested Task read context date is invalid."""


class InvalidTaskReadOptionError(TaskReadServiceError):
    """A Task read-facade option has an invalid value."""


def resolve_task_read_date(value: str | None = None) -> str:
    """
    Resolve one stable context date.

    When value is None, MuseAI's configured current date is read exactly once.
    """
    if value is None:
        return str(get_current_time()["current_date"])

    try:
        return validate_date(value)
    except (TypeError, ValueError) as exc:
        raise InvalidTaskReadDateError(str(exc)) from exc


def _require_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidTaskReadOptionError(
            f"`{field_name}` must be a boolean."
        )
    return value


def _merge_warnings(*groups: Iterable[str]) -> list[str]:
    merged: list[str] = []

    for group in groups:
        for warning in group:
            text = str(warning)
            if text not in merged:
                merged.append(text)

    return merged


def _daily_missing_result(
    *,
    date: str,
    daily_dir: str | Path | None,
) -> dict[str, Any]:
    path = resolve_daily_path(
        date,
        daily_dir=daily_dir,
    )
    return {
        "kind": "daily",
        "exists": False,
        "date": date,
        "path": str(path),
        "schema_version": None,
        "tasks": [],
        "retired_carryover_from_task_ids": [],
    }


def _long_missing_collection_result(
    collection: str,
    *,
    long_dir: str | Path | None,
) -> dict[str, Any]:
    path = resolve_long_path(
        collection,
        long_dir=long_dir,
    )
    return {
        "collection": collection,
        "exists": False,
        "path": str(path),
        "schema_version": None,
        "tasks": [],
    }


def _standing_missing_result(
    *,
    standing_dir: str | Path | None,
) -> dict[str, Any]:
    path = resolve_standing_path(
        standing_dir=standing_dir,
    )
    return {
        "kind": "standing",
        "exists": False,
        "path": str(path),
        "schema_version": None,
        "tasks": [],
    }


def read_daily_tasks(
    date: str | None = None,
    *,
    allow_missing: bool = True,
    daily_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Read one validated Daily Task collection through the Daily service.

    Missing file:
    - allow_missing=True  -> exists=False, tasks=[]
    - allow_missing=False -> DailyFileNotFoundError propagates

    Invalid/corrupt existing data always propagates as an error.
    """
    allow_missing = _require_bool(
        allow_missing,
        field_name="allow_missing",
    )
    target_date = resolve_task_read_date(date)

    try:
        result, warnings = read_daily(
            target_date,
            daily_dir=daily_dir,
        )
    except DailyFileNotFoundError:
        if not allow_missing:
            raise
        return (
            _daily_missing_result(
                date=target_date,
                daily_dir=daily_dir,
            ),
            [],
        )

    document = result["document"]

    return (
        {
            "kind": "daily",
            "exists": True,
            "date": target_date,
            "path": result["path"],
            "schema_version": document["schema_version"],
            "tasks": document["tasks"],
            "retired_carryover_from_task_ids": list(
                document["retired_carryover_from_task_ids"]
            ),
        },
        list(warnings),
    )


def _read_long_collection(
    collection: str,
    *,
    allow_missing: bool,
    long_dir: str | Path | None,
) -> tuple[dict[str, Any], list[str]]:
    try:
        result, warnings = read_long(
            collection,
            long_dir=long_dir,
        )
    except LongFileNotFoundError:
        if not allow_missing:
            raise
        return (
            _long_missing_collection_result(
                collection,
                long_dir=long_dir,
            ),
            [],
        )

    document = result["document"]

    return (
        {
            "collection": collection,
            "exists": True,
            "path": result["path"],
            "schema_version": document["schema_version"],
            "tasks": document["tasks"],
        },
        list(warnings),
    )


def read_long_tasks(
    *,
    include_archived: bool = False,
    allow_missing: bool = True,
    long_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Read validated Long Task collections through the Long service.

    Active is always requested. Archived is read only when explicitly enabled.
    """
    include_archived = _require_bool(
        include_archived,
        field_name="include_archived",
    )
    allow_missing = _require_bool(
        allow_missing,
        field_name="allow_missing",
    )

    active, active_warnings = _read_long_collection(
        ACTIVE_COLLECTION,
        allow_missing=allow_missing,
        long_dir=long_dir,
    )

    archived: dict[str, Any] | None = None
    archived_warnings: list[str] = []

    if include_archived:
        archived, archived_warnings = _read_long_collection(
            ARCHIVED_COLLECTION,
            allow_missing=allow_missing,
            long_dir=long_dir,
        )

    return (
        {
            "kind": "long",
            "active": active,
            "archived": archived,
        },
        _merge_warnings(
            active_warnings,
            archived_warnings,
        ),
    )


def read_standing_tasks(
    *,
    allow_missing: bool = True,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Read the validated Standing Task collection through the Standing service.

    This returns stored Standing facts only. It does not evaluate due state.
    """
    allow_missing = _require_bool(
        allow_missing,
        field_name="allow_missing",
    )

    try:
        result, warnings = read_standing(
            standing_dir=standing_dir,
        )
    except StandingFileNotFoundError:
        if not allow_missing:
            raise
        return (
            _standing_missing_result(
                standing_dir=standing_dir,
            ),
            [],
        )

    document = result["document"]

    return (
        {
            "kind": "standing",
            "exists": True,
            "path": result["path"],
            "schema_version": document["schema_version"],
            "tasks": document["tasks"],
        },
        list(warnings),
    )


def read_previous_daily_tasks(
    before: str | None = None,
    *,
    allow_missing: bool = True,
    daily_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Read the nearest existing Daily collection strictly before one date.

    Discovery uses Daily filenames only to locate candidate dates. Candidate
    contents are always loaded and validated through read_daily_tasks().

    Missing directory / no earlier Daily:
    - allow_missing=True  -> exists=False
    - allow_missing=False -> DailyFileNotFoundError for the immediately prior
      calendar date path, preserving strict caller semantics.

    Existing invalid candidate data is never skipped in favor of an older file.
    """
    allow_missing = _require_bool(
        allow_missing,
        field_name="allow_missing",
    )
    target_date = resolve_task_read_date(before)
    target = date_type.fromisoformat(target_date)
    directory = resolve_daily_path(
        target_date,
        daily_dir=daily_dir,
    ).parent

    candidate_dates: list[str] = []

    if directory.exists():
        try:
            entries = list(directory.iterdir())
        except OSError as exc:
            raise TaskReadError(
                f"Could not list Daily Task directory {directory}: {exc}"
            ) from exc

        for path in entries:
            if not path.is_file() or path.suffix.lower() != ".json":
                continue

            stem = path.stem
            if len(stem) != 8 or not stem.isdigit():
                continue

            try:
                candidate = date_type(
                    int(stem[0:4]),
                    int(stem[4:6]),
                    int(stem[6:8]),
                )
            except ValueError:
                continue

            if candidate < target:
                candidate_dates.append(candidate.isoformat())

    candidate_dates.sort(reverse=True)

    for candidate_date in candidate_dates:
        try:
            daily, warnings = read_daily_tasks(
                candidate_date,
                allow_missing=False,
                daily_dir=daily_dir,
            )
        except DailyFileNotFoundError:
            # A file may disappear between directory listing and read. MuseAI V1
            # assumes one writer, so continuing to the next candidate is enough.
            continue

        return (
            {
                **daily,
                "before": target_date,
            },
            warnings,
        )

    if not allow_missing:
        previous_calendar_date = date_type.fromordinal(
            target.toordinal() - 1
        ).isoformat()
        # Reuse the authoritative Daily missing exception and path formatting.
        read_daily_tasks(
            previous_calendar_date,
            allow_missing=False,
            daily_dir=daily_dir,
        )
        raise AssertionError("unreachable")

    return (
        {
            "kind": "daily",
            "exists": False,
            "before": target_date,
            "date": None,
            "path": None,
            "schema_version": None,
            "tasks": [],
            "retired_carryover_from_task_ids": [],
        },
        [],
    )


def read_task_context(
    date: str | None = None,
    *,
    include_archived_long: bool = False,
    allow_missing: bool = True,
    daily_dir: str | Path | None = None,
    long_dir: str | Path | None = None,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Read one unified Task context for internal program consumers.

    `date=None` is resolved exactly once at the beginning of this function.
    Complete validated Task objects are returned without filtering or counts.
    """
    include_archived_long = _require_bool(
        include_archived_long,
        field_name="include_archived_long",
    )
    allow_missing = _require_bool(
        allow_missing,
        field_name="allow_missing",
    )

    target_date = resolve_task_read_date(date)

    daily, daily_warnings = read_daily_tasks(
        target_date,
        allow_missing=allow_missing,
        daily_dir=daily_dir,
    )
    long_data, long_warnings = read_long_tasks(
        include_archived=include_archived_long,
        allow_missing=allow_missing,
        long_dir=long_dir,
    )
    standing, standing_warnings = read_standing_tasks(
        allow_missing=allow_missing,
        standing_dir=standing_dir,
    )

    return (
        {
            "date": target_date,
            "daily": daily,
            "long": long_data,
            "standing": standing,
        },
        _merge_warnings(
            daily_warnings,
            long_warnings,
            standing_warnings,
        ),
    )
