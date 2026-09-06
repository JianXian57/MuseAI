#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Deterministic Standing Task service for MuseAI.

Recommended location:
    MuseAI/tools/task_ops/standing_service.py

Standing V1
-----------
File:
    data/tasks/standing-task/standing-task.json

Envelope:
    schema_version = "1.0"
    kind = "standing"
    tasks = [...]

Standing-specific fields:
    enabled
    schedule
    long_task_id
    last_generated_date

Supported schedules:
    {"type": "daily"}

    {
        "type": "weekly",
        "weekdays": ["monday", "friday"]
    }

    {
        "type": "monthly",
        "day": 15
    }

    {
        "type": "yearly",
        "month": 9,
        "day": 5
    }

Boundary:
- This service writes Standing data only.
- It never creates or edits Daily Task JSON.
- Due checks return a deterministic `daily_payload`.
- Main orchestrates Daily creation, then calls mark_standing_generated().
"""

from __future__ import annotations

from datetime import date as date_type
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
    atomic_write_json,
    find_task,
    generate_task_id,
    get_task_timestamp,
    normalize_optional_task_relation,
    parse_task_id,
    read_json,
    validate_common_task,
    validate_date,
    validate_unique_task_ids,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STANDING_DIR = PROJECT_ROOT / "data" / "tasks" / "standing-task"
STANDING_FILENAME = "standing-task.json"

STANDING_KIND = "standing"
STANDING_SCHEMA_VERSION = "1.0"
SUPPORTED_STANDING_SCHEMA_VERSIONS = {STANDING_SCHEMA_VERSION}

KNOWN_SCHEDULE_TYPES = {"daily", "weekly", "monthly", "yearly"}

WEEKDAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
WEEKDAY_SET = set(WEEKDAY_NAMES)


class StandingTaskError(TaskServiceError):
    """Base exception for Standing-specific Task failures."""


class StandingFileNotFoundError(TaskFileNotFoundError, StandingTaskError):
    """Standing Task JSON file does not exist."""


class InvalidStandingDateError(StandingTaskError):
    """Standing target date is invalid."""


class InvalidStandingDocumentError(
    InvalidTaskDocumentError,
    StandingTaskError,
):
    """Standing document violates Standing V1 structure."""


class InvalidStandingScheduleError(StandingTaskError):
    """Standing schedule is invalid or unsupported."""


class StandingNotScheduledError(StandingTaskError):
    """Requested generation date does not match the Standing schedule."""


class StandingGenerationDateRegressionError(StandingTaskError):
    """Generation state would move backward in calendar time."""


def resolve_standing_date(value: str | None = None) -> str:
    """Resolve an explicit date or MuseAI's configured current date."""
    if value is None:
        return str(get_current_time()["current_date"])

    try:
        return validate_date(value)
    except ValueError as exc:
        raise InvalidStandingDateError(str(exc)) from exc


def resolve_standing_dir(
    standing_dir: str | Path | None = None,
) -> Path:
    """Resolve the Standing Task storage directory."""
    if standing_dir is None:
        return DEFAULT_STANDING_DIR

    return Path(standing_dir).expanduser().resolve()


def resolve_standing_path(
    *,
    standing_dir: str | Path | None = None,
) -> Path:
    """Resolve data/tasks/standing-task/standing-task.json."""
    return resolve_standing_dir(standing_dir) / STANDING_FILENAME


def new_standing_document() -> dict[str, Any]:
    """Build a new empty Standing V1 document."""
    return {
        "schema_version": STANDING_SCHEMA_VERSION,
        "kind": STANDING_KIND,
        "tasks": [],
    }


def _normalize_weekdays(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise InvalidStandingScheduleError(
            "Weekly schedule `weekdays` must be a non-empty array."
        )

    normalized: list[str] = []

    for item in value:
        if not isinstance(item, str):
            raise InvalidStandingScheduleError(
                "Weekly schedule weekdays must be strings."
            )

        weekday = item.strip().lower()

        if weekday not in WEEKDAY_SET:
            raise InvalidStandingScheduleError(
                "Weekly weekday must be one of: "
                + ", ".join(WEEKDAY_NAMES)
                + "."
            )

        if weekday not in normalized:
            normalized.append(weekday)

    normalized.sort(key=WEEKDAY_NAMES.index)
    return normalized


def _validate_yearly_month_day(month: int, day: int) -> None:
    """
    Validate month/day using leap year 2000.

    This intentionally allows 02-29 as a yearly schedule; it will trigger
    only in leap years.
    """
    try:
        date_type(2000, month, day)
    except ValueError as exc:
        raise InvalidStandingScheduleError(
            "Yearly schedule must contain a valid month/day pair."
        ) from exc


def normalize_schedule(schedule: Any) -> dict[str, Any]:
    """Validate and canonicalize one Standing schedule."""
    if not isinstance(schedule, dict):
        raise InvalidStandingScheduleError(
            "`schedule` must be an object."
        )

    schedule_type = schedule.get("type")

    if not isinstance(schedule_type, str):
        raise InvalidStandingScheduleError(
            "Standing schedule is missing string field `type`."
        )

    schedule_type = schedule_type.strip().lower()

    if schedule_type not in KNOWN_SCHEDULE_TYPES:
        raise InvalidStandingScheduleError(
            "`schedule.type` must be one of: "
            + ", ".join(sorted(KNOWN_SCHEDULE_TYPES))
            + "."
        )

    if schedule_type == "daily":
        return {"type": "daily"}

    if schedule_type == "weekly":
        return {
            "type": "weekly",
            "weekdays": _normalize_weekdays(
                schedule.get("weekdays")
            ),
        }

    if schedule_type == "monthly":
        day = schedule.get("day")

        if isinstance(day, bool) or not isinstance(day, int):
            raise InvalidStandingScheduleError(
                "Monthly schedule `day` must be an integer from 1 to 31."
            )

        if day < 1 or day > 31:
            raise InvalidStandingScheduleError(
                "Monthly schedule `day` must be from 1 to 31."
            )

        return {
            "type": "monthly",
            "day": day,
        }

    month = schedule.get("month")
    day = schedule.get("day")

    if (
        isinstance(month, bool)
        or not isinstance(month, int)
        or isinstance(day, bool)
        or not isinstance(day, int)
    ):
        raise InvalidStandingScheduleError(
            "Yearly schedule `month` and `day` must be integers."
        )

    if month < 1 or month > 12:
        raise InvalidStandingScheduleError(
            "Yearly schedule `month` must be from 1 to 12."
        )

    _validate_yearly_month_day(month, day)

    return {
        "type": "yearly",
        "month": month,
        "day": day,
    }


def schedule_matches_date(
    schedule: dict[str, Any],
    date: str,
) -> bool:
    """
    Return whether one schedule matches one exact date.

    Monthly day=31 does not slide to month-end.
    Yearly 02-29 triggers only in leap years.
    """
    schedule = normalize_schedule(schedule)
    date = resolve_standing_date(date)
    target = date_type.fromisoformat(date)

    schedule_type = schedule["type"]

    if schedule_type == "daily":
        return True

    if schedule_type == "weekly":
        weekday = WEEKDAY_NAMES[target.weekday()]
        return weekday in schedule["weekdays"]

    if schedule_type == "monthly":
        return target.day == schedule["day"]

    return (
        target.month == schedule["month"]
        and target.day == schedule["day"]
    )


def validate_standing_document(
    document: dict[str, Any],
) -> list[str]:
    """
    Validate Standing V1 while preserving unknown Task-level fields.

    Standing V1 keeps Common Task Core compatibility:
    status must remain pending and completed_at must remain null.
    Recurrence participation is controlled by enabled.
    """
    if not isinstance(document, dict):
        raise InvalidStandingDocumentError(
            "Standing document root must be an object."
        )

    for required in ("schema_version", "kind", "tasks"):
        if required not in document:
            raise InvalidStandingDocumentError(
                f"Standing document is missing `{required}`."
            )

    version = document["schema_version"]

    if version not in SUPPORTED_STANDING_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersionError(
            version,
            sorted(SUPPORTED_STANDING_SCHEMA_VERSIONS),
            kind=STANDING_KIND,
        )

    if document["kind"] != STANDING_KIND:
        raise InvalidStandingDocumentError(
            f"Expected kind {STANDING_KIND!r}, "
            f"got {document['kind']!r}."
        )

    tasks = document["tasks"]

    if not isinstance(tasks, list):
        raise InvalidStandingDocumentError(
            "Standing document `tasks` must be an array."
        )

    validate_unique_task_ids(tasks)

    warnings: list[str] = []

    for task in tasks:
        try:
            warnings.extend(
                validate_common_task(
                    task,
                    expected_prefix="S",
                )
            )
        except InvalidTaskDocumentError as exc:
            raise InvalidStandingDocumentError(str(exc)) from exc

        task_id = task["id"]

        if task.get("status") != "pending":
            raise InvalidStandingDocumentError(
                f"Standing Task {task_id} must use status='pending' in V1."
            )

        if task.get("completed_at") is not None:
            raise InvalidStandingDocumentError(
                f"Standing Task {task_id} must use completed_at=null in V1."
            )

        if "enabled" not in task:
            task["enabled"] = True
            warnings.append(
                f"MISSING_TASK_FIELD_DEFAULTED: {task_id}: enabled"
            )
        elif not isinstance(task["enabled"], bool):
            raise InvalidStandingDocumentError(
                f"Standing Task {task_id} has invalid `enabled`."
            )

        if "schedule" not in task:
            raise InvalidStandingDocumentError(
                f"Standing Task {task_id} is missing `schedule`."
            )

        try:
            task["schedule"] = normalize_schedule(task["schedule"])
        except InvalidStandingScheduleError as exc:
            raise InvalidStandingDocumentError(
                f"Standing Task {task_id} has invalid `schedule`: {exc}"
            ) from exc

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
                raise InvalidStandingDocumentError(
                    f"Standing Task {task_id} has invalid "
                    f"`long_task_id`: {exc}"
                ) from exc

        if "last_generated_date" not in task:
            task["last_generated_date"] = None
            warnings.append(
                f"MISSING_TASK_FIELD_DEFAULTED: "
                f"{task_id}: last_generated_date"
            )
        elif task["last_generated_date"] is not None:
            try:
                task["last_generated_date"] = validate_date(
                    task["last_generated_date"]
                )
            except (TypeError, ValueError) as exc:
                raise InvalidStandingDocumentError(
                    f"Standing Task {task_id} has invalid "
                    "`last_generated_date`."
                ) from exc

    return warnings


def _load_standing(
    *,
    standing_dir: str | Path | None = None,
) -> tuple[Path, dict[str, Any], list[str]]:
    path = resolve_standing_path(
        standing_dir=standing_dir,
    )

    if not path.exists():
        raise StandingFileNotFoundError(
            f"Standing Task file was not found: {path}"
        )

    try:
        document = read_json(path)
    except TaskFileNotFoundError as exc:
        raise StandingFileNotFoundError(str(exc)) from exc

    warnings = validate_standing_document(document)
    return path, document, warnings


def ensure_standing(
    *,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Ensure the Standing Task JSON exists."""
    path = resolve_standing_path(
        standing_dir=standing_dir,
    )

    if path.exists():
        _, document, warnings = _load_standing(
            standing_dir=standing_dir,
        )
        return (
            {
                "created": False,
                "kind": document["kind"],
                "schema_version": document["schema_version"],
                "task_count": len(document["tasks"]),
                "path": str(path),
            },
            warnings,
        )

    document = new_standing_document()
    atomic_write_json(path, document)

    return (
        {
            "created": True,
            "kind": STANDING_KIND,
            "schema_version": STANDING_SCHEMA_VERSION,
            "task_count": 0,
            "path": str(path),
        },
        [],
    )


def read_standing(
    *,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Read and validate the Standing Task JSON."""
    path, document, warnings = _load_standing(
        standing_dir=standing_dir,
    )

    return (
        {
            "path": str(path),
            "document": document,
        },
        warnings,
    )


def _normalize_text_fields(
    *,
    title: str,
    description: str,
    category: str,
) -> tuple[str, str, str]:
    if not isinstance(title, str) or not title.strip():
        raise InvalidStandingDocumentError(
            "`title` must be a non-empty string."
        )

    if not isinstance(description, str):
        raise InvalidStandingDocumentError(
            "`description` must be a string."
        )

    if not isinstance(category, str) or not category.strip():
        raise InvalidStandingDocumentError(
            "`category` must be a non-empty string."
        )

    return title.strip(), description, category.strip()


def add_standing(
    *,
    title: str,
    schedule: dict[str, Any],
    description: str = "",
    category: str = DEFAULT_CATEGORY,
    enabled: bool = True,
    long_task_id: str | None = None,
    meta: dict[str, Any] | None = None,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Add one Standing Task.

    This operation intentionally does NOT create a missing Standing file.
    Call ensure_standing() explicitly first.
    """
    path, document, warnings = _load_standing(
        standing_dir=standing_dir,
    )

    title, description, category = _normalize_text_fields(
        title=title,
        description=description,
        category=category,
    )

    schedule = normalize_schedule(schedule)

    if not isinstance(enabled, bool):
        raise InvalidStandingDocumentError(
            "`enabled` must be a boolean."
        )

    long_task_id = normalize_optional_task_relation(
        long_task_id,
        expected_prefix="L",
        field_name="long_task_id",
    )

    if meta is None:
        meta = {}
    elif not isinstance(meta, dict):
        raise InvalidStandingDocumentError(
            "`meta` must be an object."
        )

    timestamp = get_task_timestamp()
    creation_date = validate_date(timestamp[:10])

    task_id = generate_task_id(
        document["tasks"],
        prefix="S",
        date=creation_date,
    )

    task = {
        "id": task_id,
        "title": title,
        "description": description,
        "status": "pending",
        "category": category,
        "enabled": enabled,
        "schedule": schedule,
        "long_task_id": long_task_id,
        "last_generated_date": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "completed_at": None,
        "meta": dict(meta),
    }

    document["tasks"].append(task)
    atomic_write_json(path, document)

    return (
        {
            "path": str(path),
            "task": task,
        },
        warnings,
    )


def update_standing(
    *,
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    category: str | None = None,
    long_task_id: str | None = None,
    clear_long_task_id: bool = False,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Update ordinary Standing fields."""
    path, document, warnings = _load_standing(
        standing_dir=standing_dir,
    )

    parse_task_id(task_id, expected_prefix="S")
    _, task = find_task(document["tasks"], task_id)

    if not isinstance(clear_long_task_id, bool):
        raise InvalidStandingDocumentError(
            "`clear_long_task_id` must be a boolean."
        )

    if long_task_id is not None and clear_long_task_id:
        raise InvalidStandingDocumentError(
            "`long_task_id` and `clear_long_task_id=True` "
            "cannot be used together."
        )

    requested: dict[str, Any] = {}

    if title is not None:
        if not isinstance(title, str) or not title.strip():
            raise InvalidStandingDocumentError(
                "`title` must be a non-empty string."
            )
        requested["title"] = title.strip()

    if description is not None:
        if not isinstance(description, str):
            raise InvalidStandingDocumentError(
                "`description` must be a string."
            )
        requested["description"] = description

    if category is not None:
        if not isinstance(category, str) or not category.strip():
            raise InvalidStandingDocumentError(
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

    changes = {
        field: value
        for field, value in requested.items()
        if task.get(field) != value
    }

    if not changes:
        return (
            {
                "changed": False,
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
            "path": str(path),
            "task": task,
        },
        warnings,
    )


def set_standing_enabled(
    *,
    task_id: str,
    enabled: bool,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Enable or disable one Standing Task."""
    path, document, warnings = _load_standing(
        standing_dir=standing_dir,
    )

    parse_task_id(task_id, expected_prefix="S")
    _, task = find_task(document["tasks"], task_id)

    if not isinstance(enabled, bool):
        raise InvalidStandingDocumentError(
            "`enabled` must be a boolean."
        )

    if task.get("enabled") == enabled:
        return (
            {
                "changed": False,
                "path": str(path),
                "task": task,
            },
            warnings,
        )

    task["enabled"] = enabled
    task["updated_at"] = get_task_timestamp()
    atomic_write_json(path, document)

    return (
        {
            "changed": True,
            "path": str(path),
            "task": task,
        },
        warnings,
    )


def set_standing_schedule(
    *,
    task_id: str,
    schedule: dict[str, Any],
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Replace one Standing schedule.

    Schedule changes do not clear last_generated_date automatically.
    """
    path, document, warnings = _load_standing(
        standing_dir=standing_dir,
    )

    parse_task_id(task_id, expected_prefix="S")
    _, task = find_task(document["tasks"], task_id)

    schedule = normalize_schedule(schedule)

    if task.get("schedule") == schedule:
        return (
            {
                "changed": False,
                "path": str(path),
                "task": task,
            },
            warnings,
        )

    task["schedule"] = schedule
    task["updated_at"] = get_task_timestamp()
    atomic_write_json(path, document)

    return (
        {
            "changed": True,
            "path": str(path),
            "task": task,
        },
        warnings,
    )


def build_daily_payload(
    task: dict[str, Any],
) -> dict[str, Any]:
    """
    Build the Daily add payload for one Standing Task.

    The Daily Tool remains the only Daily writer.
    """
    task_id = task.get("id")
    parse_task_id(task_id, expected_prefix="S")

    return {
        "title": task["title"],
        "description": task["description"],
        "category": task["category"],
        "source": "standing",
        "standing_task_id": task_id,
        "long_task_id": task.get("long_task_id"),
    }


def _due_state(
    task: dict[str, Any],
    *,
    date: str,
) -> dict[str, Any]:
    schedule_match = schedule_matches_date(
        task["schedule"],
        date,
    )
    enabled = task["enabled"]
    already_generated = (
        task.get("last_generated_date") == date
    )

    due = bool(
        enabled
        and schedule_match
        and not already_generated
    )

    if not enabled:
        reason = "disabled"
    elif not schedule_match:
        reason = "schedule_not_matched"
    elif already_generated:
        reason = "already_generated"
    else:
        reason = "due"

    return {
        "task_id": task["id"],
        "due": due,
        "reason": reason,
        "enabled": enabled,
        "schedule_match": schedule_match,
        "already_generated": already_generated,
        "last_generated_date": task.get("last_generated_date"),
    }


def check_standing_due(
    date: str | None = None,
    *,
    include_not_due: bool = False,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Check Standing rules for one calendar date.

    Due items include a ready-to-forward `daily_payload`.
    This function never writes Standing or Daily data.
    """
    target_date = resolve_standing_date(date)
    path, document, warnings = _load_standing(
        standing_dir=standing_dir,
    )

    due_items: list[dict[str, Any]] = []
    checked_items: list[dict[str, Any]] = []

    for task in document["tasks"]:
        state = _due_state(
            task,
            date=target_date,
        )

        item: dict[str, Any] = {
            "state": state,
            "task": task,
        }

        if state["due"]:
            item["daily_payload"] = build_daily_payload(task)
            due_items.append(item)

        if include_not_due or state["due"]:
            checked_items.append(item)

    return (
        {
            "date": target_date,
            "path": str(path),
            "due_count": len(due_items),
            "due_items": due_items,
            "checked_count": len(checked_items),
            "checked_items": checked_items,
        },
        warnings,
    )


def mark_standing_generated(
    *,
    task_id: str,
    date: str | None = None,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Record that one Standing Task generated its Daily occurrence.

    Main should call this only after the Daily Tool confirms that the Daily
    occurrence exists. This operation is idempotent for the same date.
    """
    target_date = resolve_standing_date(date)
    path, document, warnings = _load_standing(
        standing_dir=standing_dir,
    )

    parse_task_id(task_id, expected_prefix="S")
    _, task = find_task(document["tasks"], task_id)

    if not schedule_matches_date(
        task["schedule"],
        target_date,
    ):
        raise StandingNotScheduledError(
            f"Standing Task {task_id} is not scheduled for {target_date}."
        )

    previous = task.get("last_generated_date")

    if previous == target_date:
        return (
            {
                "changed": False,
                "date": target_date,
                "path": str(path),
                "task": task,
            },
            warnings,
        )

    if previous is not None:
        previous_date = date_type.fromisoformat(previous)
        target = date_type.fromisoformat(target_date)

        if target < previous_date:
            raise StandingGenerationDateRegressionError(
                f"Standing Task {task_id} generation date cannot move "
                f"backward from {previous} to {target_date}."
            )

    task["last_generated_date"] = target_date
    task["updated_at"] = get_task_timestamp()
    atomic_write_json(path, document)

    return (
        {
            "changed": True,
            "date": target_date,
            "previous_generated_date": previous,
            "path": str(path),
            "task": task,
        },
        warnings,
    )


def remove_standing(
    *,
    task_id: str,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Physically remove one Standing Task rule."""
    path, document, warnings = _load_standing(
        standing_dir=standing_dir,
    )

    parse_task_id(task_id, expected_prefix="S")
    index, task = find_task(document["tasks"], task_id)

    removed = document["tasks"].pop(index)
    atomic_write_json(path, document)

    return (
        {
            "removed": removed,
            "path": str(path),
            "remaining_task_count": len(document["tasks"]),
        },
        warnings,
    )
