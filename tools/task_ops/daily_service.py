#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Deterministic Daily Task service for MuseAI.

Recommended location:
    MuseAI/tools/task_ops/daily_service.py

Daily V1
--------
File:
    data/tasks/daily-task/YYYYMMDD.json

Envelope:
    schema_version = "1.0"
    kind = "daily"
    date = "YYYY-MM-DD"
    tasks = [...]
    retired_task_ids = [...]

Daily-specific Task fields:
    source
    long_task_id
    standing_task_id

`long_task_id` is an optional relation to one Long Task.
`standing_task_id` is an optional relation to one Standing Task occurrence.

This service validates relation ID formats only; it does not require referenced
Long or Standing Tasks to exist, so Daily stays independent from their storage.

When `standing_task_id` is supplied to add_daily(), the operation is idempotent
within the target Daily file: an existing Daily Task with the same non-null
`standing_task_id` is returned instead of creating a duplicate.

This module returns plain Python data + warning lists and does not build
MuseAI public Tool results.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common.time_service import get_current_time

from task_ops.task_service import (
    DEFAULT_CATEGORY,
    InvalidTaskDocumentError,
    InvalidTaskIdError,
    TaskFileNotFoundError,
    TaskServiceError,
    UnsupportedSchemaVersionError,
    apply_status_change,
    atomic_write_json,
    find_task,
    generate_task_id,
    get_task_timestamp,
    normalize_optional_task_relation,
    normalize_retired_task_ids,
    parse_task_id,
    read_json,
    validate_common_task,
    validate_date,
    validate_unique_task_ids,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DAILY_DIR = PROJECT_ROOT / "data" / "tasks" / "daily-task"

DAILY_KIND = "daily"
DAILY_SCHEMA_VERSION = "1.0"
SUPPORTED_DAILY_SCHEMA_VERSIONS = {DAILY_SCHEMA_VERSION}
KNOWN_DAILY_SOURCES = {"manual", "carryover", "standing"}


class DailyTaskError(TaskServiceError):
    """Base exception for Daily-specific Task failures."""


class DailyFileNotFoundError(TaskFileNotFoundError, DailyTaskError):
    """Requested Daily Task file does not exist."""


class InvalidDailyDateError(DailyTaskError):
    """Daily target date is invalid."""


class DailyDateMismatchError(DailyTaskError):
    """Daily JSON `date` does not match the target file date."""


class InvalidDailySourceError(DailyTaskError):
    """A write operation requested an unsupported Daily source."""


class InvalidDailyDocumentError(InvalidTaskDocumentError, DailyTaskError):
    """Daily document violates Daily V1 structure."""


def resolve_daily_date(value: str | None = None) -> str:
    """Resolve an explicit date or MuseAI's configured current date."""
    if value is None:
        return str(get_current_time()["current_date"])

    try:
        return validate_date(value)
    except ValueError as exc:
        raise InvalidDailyDateError(str(exc)) from exc


def resolve_daily_path(
    date: str,
    *,
    daily_dir: str | Path | None = None,
) -> Path:
    """Resolve data/tasks/daily-task/YYYYMMDD.json."""
    date = resolve_daily_date(date)

    directory = (
        Path(daily_dir).expanduser().resolve()
        if daily_dir is not None
        else DEFAULT_DAILY_DIR
    )

    return directory / f"{date.replace('-', '')}.json"


def new_daily_document(date: str) -> dict[str, Any]:
    """Build a new empty Daily V1 document."""
    date = resolve_daily_date(date)

    return {
        "schema_version": DAILY_SCHEMA_VERSION,
        "kind": DAILY_KIND,
        "date": date,
        "tasks": [],
        "retired_task_ids": [],
    }


def validate_daily_document(
    document: dict[str, Any],
    *,
    expected_date: str,
) -> list[str]:
    """
    Validate Daily V1 while preserving unknown fields.

    Missing non-core Task fields are defaulted in memory where appropriate.
    `long_task_id` and `standing_task_id` are optional; missing relation fields
    are treated as null without warnings. Unknown fields are never removed.
    """
    if not isinstance(document, dict):
        raise InvalidDailyDocumentError(
            "Daily document root must be an object."
        )

    expected_date = resolve_daily_date(expected_date)

    for required in ("schema_version", "kind", "date", "tasks"):
        if required not in document:
            raise InvalidDailyDocumentError(
                f"Daily document is missing `{required}`."
            )

    version = document["schema_version"]

    if version not in SUPPORTED_DAILY_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersionError(
            version,
            sorted(SUPPORTED_DAILY_SCHEMA_VERSIONS),
            kind=DAILY_KIND,
        )

    if document["kind"] != DAILY_KIND:
        raise InvalidDailyDocumentError(
            f"Expected kind {DAILY_KIND!r}, got {document['kind']!r}."
        )

    try:
        document_date = validate_date(document["date"])
    except (TypeError, ValueError) as exc:
        raise InvalidDailyDocumentError(
            "Daily document has an invalid `date`."
        ) from exc

    if document_date != expected_date:
        raise DailyDateMismatchError(
            f"Daily document date {document_date} does not match "
            f"target date {expected_date}."
        )

    tasks = document["tasks"]

    if not isinstance(tasks, list):
        raise InvalidDailyDocumentError(
            "Daily document `tasks` must be an array."
        )

    validate_unique_task_ids(tasks)

    warnings: list[str] = []

    for task in tasks:
        try:
            task_warnings = validate_common_task(
                task,
                expected_prefix="D",
                expected_date=expected_date,
            )
        except InvalidTaskDocumentError as exc:
            raise InvalidDailyDocumentError(str(exc)) from exc

        warnings.extend(task_warnings)
        task_id = task["id"]

        if "source" not in task:
            task["source"] = "manual"
            warnings.append(
                f"MISSING_TASK_FIELD_DEFAULTED: {task_id}: source"
            )
        elif not isinstance(task["source"], str) or not task["source"].strip():
            raise InvalidDailyDocumentError(
                f"Task {task_id} has an invalid `source`."
            )
        elif task["source"] not in KNOWN_DAILY_SOURCES:
            warnings.append(
                f"UNKNOWN_DAILY_SOURCE: {task_id}: {task['source']}"
            )

        if "long_task_id" not in task:
            task["long_task_id"] = None
        else:
            try:
                task["long_task_id"] = normalize_optional_task_relation(
                    task["long_task_id"],
                    expected_prefix="L",
                    field_name="long_task_id",
                )
            except InvalidTaskIdError as exc:
                raise InvalidDailyDocumentError(
                    f"Task {task_id} has an invalid `long_task_id`: {exc}"
                ) from exc

        if "standing_task_id" not in task:
            task["standing_task_id"] = None
        else:
            try:
                task["standing_task_id"] = normalize_optional_task_relation(
                    task["standing_task_id"],
                    expected_prefix="S",
                    field_name="standing_task_id",
                )
            except InvalidTaskIdError as exc:
                raise InvalidDailyDocumentError(
                    f"Task {task_id} has an invalid `standing_task_id`: {exc}"
                ) from exc

    if "retired_task_ids" not in document:
        # Pre-v1.0 compatibility: old V1 development files did not persist
        # retirement tombstones. Missing means no retired IDs yet.
        document["retired_task_ids"] = []

    document["retired_task_ids"] = normalize_retired_task_ids(
        document["retired_task_ids"],
        expected_prefix="D",
        expected_date=expected_date,
        active_task_ids=(
            task.get("id")
            for task in tasks
            if isinstance(task, dict)
        ),
    )

    return warnings


def _load_daily(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
) -> tuple[str, Path, dict[str, Any], list[str]]:
    target_date = resolve_daily_date(date)
    path = resolve_daily_path(target_date, daily_dir=daily_dir)

    if not path.exists():
        raise DailyFileNotFoundError(
            f"Daily Task file was not found: {path}"
        )

    try:
        document = read_json(path)
    except TaskFileNotFoundError as exc:
        raise DailyFileNotFoundError(str(exc)) from exc

    warnings = validate_daily_document(
        document,
        expected_date=target_date,
    )

    return target_date, path, document, warnings


def ensure_daily(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Ensure one Daily file exists.

    Existing valid files are not modified.
    Existing invalid files fail instead of being overwritten.
    """
    target_date = resolve_daily_date(date)
    path = resolve_daily_path(target_date, daily_dir=daily_dir)

    if path.exists():
        _, _, document, warnings = _load_daily(
            target_date,
            daily_dir=daily_dir,
        )
        return (
            {
                "created": False,
                "date": target_date,
                "kind": document["kind"],
                "schema_version": document["schema_version"],
                "task_count": len(document["tasks"]),
                "path": str(path),
            },
            warnings,
        )

    document = new_daily_document(target_date)
    atomic_write_json(path, document)

    return (
        {
            "created": True,
            "date": target_date,
            "kind": DAILY_KIND,
            "schema_version": DAILY_SCHEMA_VERSION,
            "task_count": 0,
            "path": str(path),
        },
        [],
    )


def read_daily(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Read and validate one Daily JSON file without creating it."""
    target_date, path, document, warnings = _load_daily(
        date,
        daily_dir=daily_dir,
    )

    return (
        {
            "date": target_date,
            "path": str(path),
            "document": document,
        },
        warnings,
    )


def _normalize_new_task_text(
    *,
    title: str,
    description: str,
    category: str,
) -> tuple[str, str, str]:
    if not isinstance(title, str) or not title.strip():
        raise InvalidDailyDocumentError(
            "`title` must be a non-empty string."
        )

    if not isinstance(description, str):
        raise InvalidDailyDocumentError(
            "`description` must be a string."
        )

    if not isinstance(category, str) or not category.strip():
        raise InvalidDailyDocumentError(
            "`category` must be a non-empty string."
        )

    return title.strip(), description, category.strip()


def find_daily_by_standing_task_id(
    tasks: list[dict[str, Any]],
    standing_task_id: str,
) -> dict[str, Any] | None:
    """
    Find the Daily occurrence already associated with one Standing Task.

    A Standing rule may generate at most one Daily occurrence per Daily file.
    """
    standing_task_id = normalize_optional_task_relation(
        standing_task_id,
        expected_prefix="S",
        field_name="standing_task_id",
    )

    for task in tasks:
        if task.get("standing_task_id") == standing_task_id:
            return task

    return None


def add_daily(
    *,
    title: str,
    description: str = "",
    category: str = DEFAULT_CATEGORY,
    source: str = "manual",
    long_task_id: str | None = None,
    standing_task_id: str | None = None,
    date: str | None = None,
    meta: dict[str, Any] | None = None,
    daily_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Add one Task to an existing Daily file.

    This operation intentionally does NOT create a missing Daily file.
    Call ensure_daily() explicitly first.
    """
    target_date, path, document, warnings = _load_daily(
        date,
        daily_dir=daily_dir,
    )

    title, description, category = _normalize_new_task_text(
        title=title,
        description=description,
        category=category,
    )

    if not isinstance(source, str) or source not in KNOWN_DAILY_SOURCES:
        raise InvalidDailySourceError(
            f"`source` must be one of: "
            f"{', '.join(sorted(KNOWN_DAILY_SOURCES))}."
        )

    long_task_id = normalize_optional_task_relation(
        long_task_id,
        expected_prefix="L",
        field_name="long_task_id",
    )
    standing_task_id = normalize_optional_task_relation(
        standing_task_id,
        expected_prefix="S",
        field_name="standing_task_id",
    )

    if standing_task_id is not None:
        existing = find_daily_by_standing_task_id(
            document["tasks"],
            standing_task_id,
        )

        if existing is not None:
            return (
                {
                    "created": False,
                    "date": target_date,
                    "path": str(path),
                    "task": existing,
                },
                warnings,
            )

    if meta is None:
        meta = {}
    elif not isinstance(meta, dict):
        raise InvalidDailyDocumentError(
            "`meta` must be an object."
        )

    timestamp = get_task_timestamp()
    task_id = generate_task_id(
        document["tasks"],
        prefix="D",
        date=target_date,
        retired_task_ids=document["retired_task_ids"],
    )

    task = {
        "id": task_id,
        "title": title,
        "description": description,
        "status": "pending",
        "category": category,
        "source": source,
        "long_task_id": long_task_id,
        "standing_task_id": standing_task_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "completed_at": None,
        "meta": dict(meta),
    }

    document["tasks"].append(task)
    atomic_write_json(path, document)

    return (
        {
            "created": True,
            "date": target_date,
            "path": str(path),
            "task": task,
        },
        warnings,
    )


def update_daily(
    *,
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    category: str | None = None,
    long_task_id: str | None = None,
    clear_long_task_id: bool = False,
    standing_task_id: str | None = None,
    clear_standing_task_id: bool = False,
    date: str | None = None,
    daily_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Update user-editable Daily fields:
        title, description, category, long_task_id, standing_task_id

    `long_task_id=None` and `standing_task_id=None` mean "do not change".
    Use the corresponding clear flag to explicitly remove a relation.

    System-managed fields such as id/status/source/timestamps are not exposed
    here. No-op updates do not modify updated_at or rewrite the file.
    """
    target_date, path, document, warnings = _load_daily(
        date,
        daily_dir=daily_dir,
    )

    parse_task_id(
        task_id,
        expected_prefix="D",
        expected_date=target_date,
    )
    _, task = find_task(document["tasks"], task_id)

    if not isinstance(clear_long_task_id, bool):
        raise InvalidDailyDocumentError(
            "`clear_long_task_id` must be a boolean."
        )

    if long_task_id is not None and clear_long_task_id:
        raise InvalidDailyDocumentError(
            "`long_task_id` and `clear_long_task_id=True` cannot be used "
            "together."
        )

    if not isinstance(clear_standing_task_id, bool):
        raise InvalidDailyDocumentError(
            "`clear_standing_task_id` must be a boolean."
        )

    if standing_task_id is not None and clear_standing_task_id:
        raise InvalidDailyDocumentError(
            "`standing_task_id` and `clear_standing_task_id=True` cannot be "
            "used together."
        )

    requested: dict[str, Any] = {}

    if title is not None:
        if not isinstance(title, str) or not title.strip():
            raise InvalidDailyDocumentError(
                "`title` must be a non-empty string."
            )
        requested["title"] = title.strip()

    if description is not None:
        if not isinstance(description, str):
            raise InvalidDailyDocumentError(
                "`description` must be a string."
            )
        requested["description"] = description

    if category is not None:
        if not isinstance(category, str) or not category.strip():
            raise InvalidDailyDocumentError(
                "`category` must be a non-empty string."
            )
        requested["category"] = category.strip()

    if long_task_id is not None:
        requested["long_task_id"] = normalize_optional_task_relation(
            long_task_id,
            expected_prefix="L",
            field_name="long_task_id",
        )
    elif clear_long_task_id:
        requested["long_task_id"] = None

    if standing_task_id is not None:
        standing_task_id = normalize_optional_task_relation(
            standing_task_id,
            expected_prefix="S",
            field_name="standing_task_id",
        )

        existing = find_daily_by_standing_task_id(
            document["tasks"],
            standing_task_id,
        )
        if existing is not None and existing.get("id") != task_id:
            raise InvalidDailyDocumentError(
                f"Standing Task {standing_task_id} is already linked to "
                f"Daily Task {existing.get('id')} in {target_date}."
            )

        requested["standing_task_id"] = standing_task_id
    elif clear_standing_task_id:
        requested["standing_task_id"] = None

    changes = {
        field: value
        for field, value in requested.items()
        if task.get(field) != value
    }

    if not changes:
        return (
            {
                "changed": False,
                "date": target_date,
                "path": str(path),
                "task": task,
            },
            warnings,
        )

    for field, value in changes.items():
        task[field] = value

    task["updated_at"] = get_task_timestamp()
    atomic_write_json(path, document)

    return (
        {
            "changed": True,
            "changed_fields": sorted(changes),
            "date": target_date,
            "path": str(path),
            "task": task,
        },
        warnings,
    )


def set_daily_status(
    *,
    task_id: str,
    status: str,
    date: str | None = None,
    daily_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Set Daily status with idempotent completed_at semantics."""
    target_date, path, document, warnings = _load_daily(
        date,
        daily_dir=daily_dir,
    )

    parse_task_id(
        task_id,
        expected_prefix="D",
        expected_date=target_date,
    )
    _, task = find_task(document["tasks"], task_id)

    if not isinstance(status, str):
        raise InvalidDailyDocumentError(
            "`status` must be a string."
        )

    status = status.strip()

    if task.get("status") == status:
        return (
            {
                "changed": False,
                "date": target_date,
                "path": str(path),
                "task": task,
            },
            warnings,
        )

    timestamp = get_task_timestamp()

    try:
        changed = apply_status_change(
            task,
            status,
            timestamp=timestamp,
        )
    except InvalidTaskDocumentError as exc:
        raise InvalidDailyDocumentError(str(exc)) from exc

    if changed:
        atomic_write_json(path, document)

    return (
        {
            "changed": changed,
            "date": target_date,
            "path": str(path),
            "task": task,
        },
        warnings,
    )


def remove_daily(
    *,
    task_id: str,
    date: str | None = None,
    daily_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Physically remove one exact Daily Task from an existing file."""
    target_date, path, document, warnings = _load_daily(
        date,
        daily_dir=daily_dir,
    )

    parse_task_id(
        task_id,
        expected_prefix="D",
        expected_date=target_date,
    )
    index, task = find_task(document["tasks"], task_id)

    removed = document["tasks"].pop(index)
    document["retired_task_ids"].append(str(removed["id"]))
    atomic_write_json(path, document)

    return (
        {
            "removed": removed,
            "date": target_date,
            "path": str(path),
            "remaining_task_count": len(document["tasks"]),
        },
        warnings,
    )
