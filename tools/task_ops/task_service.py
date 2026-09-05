#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Shared deterministic services for MuseAI Task modules.

Recommended location:
    MuseAI/tools/task_ops/task_service.py

Responsibilities
----------------
- Validate common Task fields and dates.
- Read Task JSON documents.
- Atomically write Task JSON documents.
- Parse and generate stable Task IDs.
- Find Tasks by ID.
- Apply common status transitions.

This module does not:
- know where Daily / Long / Standing files are stored;
- know kind-specific fields such as Daily `source`;
- build MuseAI public Tool results;
- parse CLI arguments;
- print output;
- write lifecycle logs.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date as date_type
from pathlib import Path
from typing import Any, Iterable

from common.time_service import get_current_time


TASK_ID_PATTERN = re.compile(
    r"^(?P<prefix>[DLS])(?P<date>\d{8})-(?P<sequence>\d{3,})$"
)

KNOWN_STATUSES = {"pending", "done"}
DEFAULT_CATEGORY = "未分类"


class TaskServiceError(Exception):
    """Base exception for deterministic Task service failures."""


class TaskFileNotFoundError(TaskServiceError):
    """Requested Task JSON file does not exist."""


class TaskReadError(TaskServiceError):
    """Task JSON file could not be read."""


class TaskWriteError(TaskServiceError):
    """Task JSON file could not be written safely."""


class InvalidTaskDocumentError(TaskServiceError):
    """Task JSON document or Task object violates required structure."""


class UnsupportedSchemaVersionError(TaskServiceError):
    """The document declares a schema version unsupported by this service."""

    def __init__(
        self,
        version: Any,
        supported_versions: Iterable[str],
        *,
        kind: str | None = None,
    ) -> None:
        self.version = version
        self.supported_versions = tuple(supported_versions)
        self.kind = kind

        scope = f"{kind} " if kind else ""
        supported = ", ".join(self.supported_versions) or "(none)"
        super().__init__(
            f"Unsupported {scope}schema version {version!r}. "
            f"Supported: {supported}."
        )


class InvalidTaskIdError(TaskServiceError):
    """Task ID is malformed or does not match the expected kind/date."""


class DuplicateTaskIdError(TaskServiceError):
    """Two or more Tasks in one document use the same ID."""


class TaskNotFoundError(TaskServiceError):
    """Requested Task ID does not exist in the target document."""


def validate_date(value: str) -> str:
    """
    Validate an ISO calendar date and return its canonical YYYY-MM-DD form.
    """
    if not isinstance(value, str):
        raise ValueError("Date must be a string in YYYY-MM-DD format.")

    stripped = value.strip()

    try:
        parsed = date_type.fromisoformat(stripped)
    except ValueError as exc:
        raise ValueError("Date must use valid YYYY-MM-DD format.") from exc

    canonical = parsed.isoformat()

    if stripped != canonical:
        raise ValueError("Date must use canonical YYYY-MM-DD format.")

    return canonical


def get_task_timestamp() -> str:
    """
    Return a strict MuseAI business timestamp.

    Task data must use the configured user timezone. Unlike logging, this
    function intentionally does not use the system-time fallback.
    """
    context = get_current_time()
    aware_datetime = context.get("datetime")

    if aware_datetime is None:
        raise TaskServiceError(
            "Time service did not return an aware datetime object."
        )

    return aware_datetime.isoformat(timespec="seconds")


def read_json(path: str | Path) -> dict[str, Any]:
    """
    Read one UTF-8 JSON object from disk.

    Missing files are distinguished from malformed documents so public Tools
    can expose stable error codes.
    """
    resolved = Path(path)

    if not resolved.exists():
        raise TaskFileNotFoundError(
            f"Task file was not found: {resolved}"
        )

    if not resolved.is_file():
        raise TaskReadError(
            f"Task path is not a file: {resolved}"
        )

    try:
        raw = resolved.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise TaskReadError(
            f"Could not read Task file {resolved}: {exc}"
        ) from exc

    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidTaskDocumentError(
            f"Task file is not valid JSON: {resolved}; "
            f"line {exc.lineno}, column {exc.colno}."
        ) from exc

    if not isinstance(document, dict):
        raise InvalidTaskDocumentError(
            "Task JSON document root must be an object."
        )

    return document


def atomic_write_json(
    path: str | Path,
    document: dict[str, Any],
) -> None:
    """
    Atomically write one UTF-8 JSON document.

    A temporary file is created in the destination directory, flushed and
    fsynced, then atomically replaced into the final path with os.replace().
    """
    if not isinstance(document, dict):
        raise InvalidTaskDocumentError(
            "Task JSON document root must be an object."
        )

    resolved = Path(path)
    parent = resolved.parent

    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TaskWriteError(
            f"Could not create Task directory {parent}: {exc}"
        ) from exc

    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(
                document,
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, resolved)
        temp_path = None

    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise TaskWriteError(
            f"Could not atomically write Task file {resolved}: {exc}"
        ) from exc

    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def parse_task_id(
    task_id: str,
    *,
    expected_prefix: str | None = None,
    expected_date: str | None = None,
) -> dict[str, Any]:
    """
    Parse and validate IDs such as D20260905-001.
    """
    if not isinstance(task_id, str):
        raise InvalidTaskIdError("Task ID must be a string.")

    task_id = task_id.strip()
    match = TASK_ID_PATTERN.fullmatch(task_id)

    if match is None:
        raise InvalidTaskIdError(
            "Task ID must match [DLS]YYYYMMDD-NNN."
        )

    prefix = match.group("prefix")
    compact_date = match.group("date")
    sequence = int(match.group("sequence"))

    try:
        canonical_date = date_type(
            int(compact_date[0:4]),
            int(compact_date[4:6]),
            int(compact_date[6:8]),
        ).isoformat()
    except ValueError as exc:
        raise InvalidTaskIdError(
            f"Task ID contains an invalid date: {task_id}"
        ) from exc

    if expected_prefix is not None and prefix != expected_prefix:
        raise InvalidTaskIdError(
            f"Task ID {task_id} does not use expected prefix "
            f"{expected_prefix!r}."
        )

    if expected_date is not None:
        try:
            expected_date = validate_date(expected_date)
        except ValueError as exc:
            raise InvalidTaskIdError(str(exc)) from exc

        if canonical_date != expected_date:
            raise InvalidTaskIdError(
                f"Task ID date {canonical_date} does not match "
                f"expected date {expected_date}."
            )

    return {
        "id": task_id,
        "prefix": prefix,
        "date": canonical_date,
        "sequence": sequence,
    }


def generate_task_id(
    tasks: list[dict[str, Any]],
    *,
    prefix: str,
    date: str,
) -> str:
    """
    Generate the next non-reused Task ID for one kind/date.

    Sequence numbers are based on the maximum existing sequence, never on
    len(tasks), so deleting a Task does not cause an old ID to be reused.
    """
    if prefix not in {"D", "L", "S"}:
        raise InvalidTaskIdError(
            "Task ID prefix must be D, L, or S."
        )

    try:
        date = validate_date(date)
    except ValueError as exc:
        raise InvalidTaskIdError(str(exc)) from exc

    compact_date = date.replace("-", "")
    maximum = 0

    for task in tasks:
        if not isinstance(task, dict):
            continue

        value = task.get("id")

        if not isinstance(value, str):
            continue

        match = TASK_ID_PATTERN.fullmatch(value.strip())

        if match is None:
            continue

        if (
            match.group("prefix") == prefix
            and match.group("date") == compact_date
        ):
            maximum = max(maximum, int(match.group("sequence")))

    next_sequence = maximum + 1
    return f"{prefix}{compact_date}-{next_sequence:03d}"


def find_task(
    tasks: list[dict[str, Any]],
    task_id: str,
) -> tuple[int, dict[str, Any]]:
    """Return (index, task) for one exact Task ID."""
    for index, task in enumerate(tasks):
        if isinstance(task, dict) and task.get("id") == task_id:
            return index, task

    raise TaskNotFoundError(
        f"Task ID was not found: {task_id}"
    )


def validate_common_task(
    task: Any,
    *,
    expected_prefix: str | None = None,
    expected_date: str | None = None,
) -> list[str]:
    """
    Validate the Common Task Core in a forward-compatible way.

    Required reader fields:
        id, title, status

    Missing non-core V1 fields receive in-memory defaults plus warnings.
    Unknown fields are intentionally untouched.
    """
    if not isinstance(task, dict):
        raise InvalidTaskDocumentError(
            "Each item in `tasks` must be an object."
        )

    warnings: list[str] = []

    for required in ("id", "title", "status"):
        if required not in task:
            raise InvalidTaskDocumentError(
                f"Task is missing required field `{required}`."
            )

    task_id = task["id"]
    parse_task_id(
        task_id,
        expected_prefix=expected_prefix,
        expected_date=expected_date,
    )

    if not isinstance(task["title"], str) or not task["title"].strip():
        raise InvalidTaskDocumentError(
            f"Task {task_id} has an invalid `title`."
        )

    if not isinstance(task["status"], str) or not task["status"].strip():
        raise InvalidTaskDocumentError(
            f"Task {task_id} has an invalid `status`."
        )

    if task["status"] not in KNOWN_STATUSES:
        warnings.append(
            f"UNKNOWN_STATUS: {task_id}: {task['status']}"
        )

    defaults: dict[str, Any] = {
        "description": "",
        "category": DEFAULT_CATEGORY,
        "created_at": None,
        "updated_at": None,
        "completed_at": None,
        "meta": {},
    }

    for field, default in defaults.items():
        if field not in task:
            task[field] = default
            warnings.append(
                f"MISSING_TASK_FIELD_DEFAULTED: {task_id}: {field}"
            )

    if not isinstance(task["description"], str):
        raise InvalidTaskDocumentError(
            f"Task {task_id} has an invalid `description`."
        )

    if not isinstance(task["category"], str) or not task["category"].strip():
        raise InvalidTaskDocumentError(
            f"Task {task_id} has an invalid `category`."
        )

    for field in ("created_at", "updated_at"):
        value = task[field]
        if value is not None and not isinstance(value, str):
            raise InvalidTaskDocumentError(
                f"Task {task_id} has an invalid `{field}`."
            )

    completed_at = task["completed_at"]
    if completed_at is not None and not isinstance(completed_at, str):
        raise InvalidTaskDocumentError(
            f"Task {task_id} has an invalid `completed_at`."
        )

    if not isinstance(task["meta"], dict):
        raise InvalidTaskDocumentError(
            f"Task {task_id} has an invalid `meta`; expected object."
        )

    if task["status"] == "pending" and completed_at is not None:
        warnings.append(
            f"STATUS_COMPLETION_MISMATCH: {task_id}: "
            "pending task has completed_at."
        )

    if task["status"] == "done" and completed_at is None:
        warnings.append(
            f"STATUS_COMPLETION_MISMATCH: {task_id}: "
            "done task has no completed_at."
        )

    return warnings


def validate_unique_task_ids(
    tasks: list[dict[str, Any]],
) -> None:
    """Reject duplicate Task IDs in one document."""
    seen: set[str] = set()

    for task in tasks:
        if not isinstance(task, dict):
            continue

        task_id = task.get("id")

        if not isinstance(task_id, str):
            continue

        if task_id in seen:
            raise DuplicateTaskIdError(
                f"Duplicate Task ID: {task_id}"
            )

        seen.add(task_id)


def apply_status_change(
    task: dict[str, Any],
    status: str,
    *,
    timestamp: str,
) -> bool:
    """
    Apply a supported status transition.

    Returns True only when the Task actually changed.

    pending -> done:
        status=done, updated_at=timestamp, completed_at=timestamp

    done -> pending:
        status=pending, updated_at=timestamp, completed_at=None

    same status:
        no mutation, False
    """
    if status not in KNOWN_STATUSES:
        raise InvalidTaskDocumentError(
            f"Unsupported Task status: {status!r}."
        )

    current = task.get("status")

    if current == status:
        return False

    task["status"] = status
    task["updated_at"] = timestamp

    if status == "done":
        task["completed_at"] = timestamp
    else:
        task["completed_at"] = None

    return True
