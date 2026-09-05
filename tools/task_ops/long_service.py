#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Deterministic Long Task service for MuseAI.

Recommended location:
    MuseAI/tools/task_ops/long_service.py

Long V1
-------
Files:
    data/tasks/long-task/long-task.json
    data/tasks/long-task/long-task-archived.json

Envelope:
    schema_version = "1.0"
    kind = "long"
    collection = "active" | "archived"
    tasks = [...]

Long-specific Task fields:
    active
    stage
    deadline
    archived_at
    timeline

Timeline event fields:
    id
    type
    origin
    text
    at
    meta

Design notes
------------
- Active and archived Long Tasks are stored separately.
- Archive/unarchive use a safe copy-first, delete-second migration.
- If the process stops between the two writes, the next matching archive or
  unarchive call can recover the interrupted migration.
- Completion and archive are independent.
- Long Task IDs are never generated from only the active collection; both
  active and archived IDs participate in sequence generation.
- This module returns plain Python data + warning lists and does not build
  MuseAI public Tool results.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from task_ops.task_service import (
    DEFAULT_CATEGORY,
    InvalidTaskDocumentError,
    InvalidTaskIdError,
    TaskFileNotFoundError,
    TaskNotFoundError,
    TaskServiceError,
    UnsupportedSchemaVersionError,
    apply_status_change,
    atomic_write_json,
    find_task,
    generate_task_id,
    get_task_timestamp,
    parse_task_id,
    read_json,
    validate_common_task,
    validate_date,
    validate_unique_task_ids,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LONG_DIR = PROJECT_ROOT / "data" / "tasks" / "long-task"

ACTIVE_FILENAME = "long-task.json"
ARCHIVED_FILENAME = "long-task-archived.json"

LONG_KIND = "long"
LONG_SCHEMA_VERSION = "1.0"
SUPPORTED_LONG_SCHEMA_VERSIONS = {LONG_SCHEMA_VERSION}

ACTIVE_COLLECTION = "active"
ARCHIVED_COLLECTION = "archived"
KNOWN_COLLECTIONS = {ACTIVE_COLLECTION, ARCHIVED_COLLECTION}

KNOWN_TIMELINE_TYPES = {
    "progress",
    "note",
    "stage",
    "status",
    "active",
    "deadline",
    "archive",
}
KNOWN_TIMELINE_ORIGINS = {"user", "system"}
USER_RECORD_TYPES = {"progress", "note"}

EVENT_ID_PATTERN = re.compile(r"^E(?P<sequence>\d{3,})$")


class LongTaskError(TaskServiceError):
    """Base exception for Long-specific Task failures."""


class LongFileNotFoundError(TaskFileNotFoundError, LongTaskError):
    """A required Long Task collection file does not exist."""

    def __init__(self, collection: str, path: Path) -> None:
        self.collection = collection
        self.path = path
        super().__init__(
            f"Long Task {collection!r} collection file was not found: {path}"
        )


class InvalidLongCollectionError(LongTaskError):
    """Requested Long collection is invalid."""


class InvalidLongDocumentError(InvalidTaskDocumentError, LongTaskError):
    """Long document violates Long V1 structure."""


class InvalidLongDeadlineError(LongTaskError):
    """Long deadline is invalid."""


class InvalidLongStageError(LongTaskError):
    """Long stage is invalid."""


class InvalidTimelineEventError(LongTaskError):
    """Long timeline event is invalid."""


class InvalidLongStateError(LongTaskError):
    """Requested Long state transition is invalid."""


class LongCollectionConflictError(LongTaskError):
    """The same Long Task exists in both collections unexpectedly."""


def resolve_long_dir(long_dir: str | Path | None = None) -> Path:
    """Resolve the Long Task storage directory."""
    if long_dir is None:
        return DEFAULT_LONG_DIR

    return Path(long_dir).expanduser().resolve()


def resolve_long_path(
    collection: str,
    *,
    long_dir: str | Path | None = None,
) -> Path:
    """Resolve one Long collection file path."""
    if collection not in KNOWN_COLLECTIONS:
        raise InvalidLongCollectionError(
            f"`collection` must be one of: {', '.join(sorted(KNOWN_COLLECTIONS))}."
        )

    directory = resolve_long_dir(long_dir)

    if collection == ACTIVE_COLLECTION:
        return directory / ACTIVE_FILENAME

    return directory / ARCHIVED_FILENAME


def new_long_document(collection: str) -> dict[str, Any]:
    """Build one empty Long V1 collection document."""
    if collection not in KNOWN_COLLECTIONS:
        raise InvalidLongCollectionError(
            f"`collection` must be one of: {', '.join(sorted(KNOWN_COLLECTIONS))}."
        )

    return {
        "schema_version": LONG_SCHEMA_VERSION,
        "kind": LONG_KIND,
        "collection": collection,
        "tasks": [],
    }


def _normalize_title_description_category(
    *,
    title: str,
    description: str,
    category: str,
) -> tuple[str, str, str]:
    if not isinstance(title, str) or not title.strip():
        raise InvalidLongDocumentError(
            "`title` must be a non-empty string."
        )

    if not isinstance(description, str):
        raise InvalidLongDocumentError(
            "`description` must be a string."
        )

    if not isinstance(category, str) or not category.strip():
        raise InvalidLongDocumentError(
            "`category` must be a non-empty string."
        )

    return title.strip(), description, category.strip()


def normalize_stage(value: str | None) -> str | None:
    """Normalize an optional open-string Long stage."""
    if value is None:
        return None

    if not isinstance(value, str) or not value.strip():
        raise InvalidLongStageError(
            "`stage` must be null or a non-empty string."
        )

    return value.strip()


def normalize_deadline(value: str | None) -> str | None:
    """Normalize an optional YYYY-MM-DD Long deadline."""
    if value is None:
        return None

    try:
        return validate_date(value)
    except (TypeError, ValueError) as exc:
        raise InvalidLongDeadlineError(
            "`deadline` must be null or a valid YYYY-MM-DD date."
        ) from exc


def _validate_timeline_event(
    event: Any,
    *,
    task_id: str,
) -> list[str]:
    """Validate one Long timeline event and preserve unknown fields."""
    if not isinstance(event, dict):
        raise InvalidTimelineEventError(
            f"Task {task_id} timeline entries must be objects."
        )

    for required in ("id", "type", "origin", "text", "at"):
        if required not in event:
            raise InvalidTimelineEventError(
                f"Task {task_id} timeline event is missing `{required}`."
            )

    event_id = event["id"]

    if not isinstance(event_id, str) or EVENT_ID_PATTERN.fullmatch(event_id) is None:
        raise InvalidTimelineEventError(
            f"Task {task_id} has an invalid timeline event ID: {event_id!r}."
        )

    event_type = event["type"]
    if not isinstance(event_type, str) or not event_type.strip():
        raise InvalidTimelineEventError(
            f"Task {task_id} event {event_id} has an invalid `type`."
        )

    origin = event["origin"]
    if not isinstance(origin, str) or not origin.strip():
        raise InvalidTimelineEventError(
            f"Task {task_id} event {event_id} has an invalid `origin`."
        )

    text = event["text"]
    if not isinstance(text, str) or not text.strip():
        raise InvalidTimelineEventError(
            f"Task {task_id} event {event_id} has invalid `text`."
        )

    at = event["at"]
    if not isinstance(at, str) or not at.strip():
        raise InvalidTimelineEventError(
            f"Task {task_id} event {event_id} has invalid `at`."
        )

    warnings: list[str] = []

    if event_type not in KNOWN_TIMELINE_TYPES:
        warnings.append(
            f"UNKNOWN_TIMELINE_TYPE: {task_id}: {event_id}: {event_type}"
        )

    if origin not in KNOWN_TIMELINE_ORIGINS:
        warnings.append(
            f"UNKNOWN_TIMELINE_ORIGIN: {task_id}: {event_id}: {origin}"
        )

    if "meta" not in event:
        event["meta"] = {}
        warnings.append(
            f"MISSING_TIMELINE_FIELD_DEFAULTED: {task_id}: {event_id}: meta"
        )
    elif not isinstance(event["meta"], dict):
        raise InvalidTimelineEventError(
            f"Task {task_id} event {event_id} has invalid `meta`; expected object."
        )

    return warnings


def _validate_timeline(
    timeline: Any,
    *,
    task_id: str,
) -> list[str]:
    if not isinstance(timeline, list):
        raise InvalidTimelineEventError(
            f"Task {task_id} has invalid `timeline`; expected array."
        )

    warnings: list[str] = []
    seen: set[str] = set()

    for event in timeline:
        event_warnings = _validate_timeline_event(
            event,
            task_id=task_id,
        )
        warnings.extend(event_warnings)

        event_id = event["id"]
        if event_id in seen:
            raise InvalidTimelineEventError(
                f"Task {task_id} contains duplicate timeline event ID {event_id}."
            )
        seen.add(event_id)

    return warnings


def validate_long_document(
    document: dict[str, Any],
    *,
    expected_collection: str,
) -> list[str]:
    """
    Validate Long V1 while preserving unknown fields.

    Reader behavior is tolerant for missing non-core fields where a safe
    default exists. Archived membership itself is not guessed: archived
    tasks must carry a non-null `archived_at`.
    """
    if expected_collection not in KNOWN_COLLECTIONS:
        raise InvalidLongCollectionError(
            f"Unsupported Long collection: {expected_collection!r}."
        )

    if not isinstance(document, dict):
        raise InvalidLongDocumentError(
            "Long document root must be an object."
        )

    for required in ("schema_version", "kind", "collection", "tasks"):
        if required not in document:
            raise InvalidLongDocumentError(
                f"Long document is missing `{required}`."
            )

    version = document["schema_version"]
    if version not in SUPPORTED_LONG_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersionError(
            version,
            sorted(SUPPORTED_LONG_SCHEMA_VERSIONS),
            kind=LONG_KIND,
        )

    if document["kind"] != LONG_KIND:
        raise InvalidLongDocumentError(
            f"Expected kind {LONG_KIND!r}, got {document['kind']!r}."
        )

    if document["collection"] != expected_collection:
        raise InvalidLongDocumentError(
            f"Expected collection {expected_collection!r}, "
            f"got {document['collection']!r}."
        )

    tasks = document["tasks"]
    if not isinstance(tasks, list):
        raise InvalidLongDocumentError(
            "Long document `tasks` must be an array."
        )

    validate_unique_task_ids(tasks)

    warnings: list[str] = []

    for task in tasks:
        try:
            task_warnings = validate_common_task(
                task,
                expected_prefix="L",
            )
        except InvalidTaskDocumentError as exc:
            raise InvalidLongDocumentError(str(exc)) from exc

        warnings.extend(task_warnings)
        task_id = task["id"]

        if "active" not in task:
            task["active"] = expected_collection == ACTIVE_COLLECTION
            warnings.append(
                f"MISSING_TASK_FIELD_DEFAULTED: {task_id}: active"
            )
        elif not isinstance(task["active"], bool):
            raise InvalidLongDocumentError(
                f"Task {task_id} has invalid `active`; expected boolean."
            )

        if "stage" not in task:
            task["stage"] = None
            warnings.append(
                f"MISSING_TASK_FIELD_DEFAULTED: {task_id}: stage"
            )
        else:
            try:
                task["stage"] = normalize_stage(task["stage"])
            except InvalidLongStageError as exc:
                raise InvalidLongDocumentError(
                    f"Task {task_id} has invalid `stage`: {exc}"
                ) from exc

        if "deadline" not in task:
            task["deadline"] = None
            warnings.append(
                f"MISSING_TASK_FIELD_DEFAULTED: {task_id}: deadline"
            )
        else:
            try:
                task["deadline"] = normalize_deadline(task["deadline"])
            except InvalidLongDeadlineError as exc:
                raise InvalidLongDocumentError(
                    f"Task {task_id} has invalid `deadline`: {exc}"
                ) from exc

        if "archived_at" not in task:
            if expected_collection == ARCHIVED_COLLECTION:
                raise InvalidLongDocumentError(
                    f"Archived Task {task_id} is missing `archived_at`."
                )
            task["archived_at"] = None
            warnings.append(
                f"MISSING_TASK_FIELD_DEFAULTED: {task_id}: archived_at"
            )
        else:
            archived_at = task["archived_at"]
            if archived_at is not None and not isinstance(archived_at, str):
                raise InvalidLongDocumentError(
                    f"Task {task_id} has invalid `archived_at`."
                )

        if "timeline" not in task:
            task["timeline"] = []
            warnings.append(
                f"MISSING_TASK_FIELD_DEFAULTED: {task_id}: timeline"
            )

        try:
            warnings.extend(
                _validate_timeline(
                    task["timeline"],
                    task_id=task_id,
                )
            )
        except InvalidTimelineEventError as exc:
            raise InvalidLongDocumentError(str(exc)) from exc

        if expected_collection == ACTIVE_COLLECTION:
            if task["archived_at"] is not None:
                raise InvalidLongDocumentError(
                    f"Active collection Task {task_id} must have archived_at=null."
                )
        else:
            if task["archived_at"] is None:
                raise InvalidLongDocumentError(
                    f"Archived collection Task {task_id} must have archived_at."
                )
            if task["active"] is not False:
                raise InvalidLongDocumentError(
                    f"Archived collection Task {task_id} must have active=false."
                )

        if task.get("status") == "done" and task["active"] is True:
            warnings.append(
                f"DONE_TASK_ACTIVE: {task_id}"
            )

    return warnings


def _load_collection(
    collection: str,
    *,
    long_dir: str | Path | None = None,
) -> tuple[Path, dict[str, Any], list[str]]:
    path = resolve_long_path(
        collection,
        long_dir=long_dir,
    )

    if not path.exists():
        raise LongFileNotFoundError(collection, path)

    try:
        document = read_json(path)
    except TaskFileNotFoundError as exc:
        raise LongFileNotFoundError(collection, path) from exc

    warnings = validate_long_document(
        document,
        expected_collection=collection,
    )

    return path, document, warnings


def _load_both(
    *,
    long_dir: str | Path | None = None,
) -> tuple[
    Path,
    dict[str, Any],
    list[str],
    Path,
    dict[str, Any],
    list[str],
]:
    active_path, active_doc, active_warnings = _load_collection(
        ACTIVE_COLLECTION,
        long_dir=long_dir,
    )
    archived_path, archived_doc, archived_warnings = _load_collection(
        ARCHIVED_COLLECTION,
        long_dir=long_dir,
    )
    return (
        active_path,
        active_doc,
        active_warnings,
        archived_path,
        archived_doc,
        archived_warnings,
    )


def _merge_warnings(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for warning in group:
            if warning not in merged:
                merged.append(warning)
    return merged


def ensure_long(
    *,
    long_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Ensure both Long collection files exist.

    Existing files are validated and never overwritten when invalid.
    Missing collection files are created independently.
    """
    created: list[str] = []
    paths: dict[str, str] = {}
    counts: dict[str, int] = {}
    warnings: list[str] = []

    for collection in (ACTIVE_COLLECTION, ARCHIVED_COLLECTION):
        path = resolve_long_path(
            collection,
            long_dir=long_dir,
        )
        paths[collection] = str(path)

        if path.exists():
            _, document, current_warnings = _load_collection(
                collection,
                long_dir=long_dir,
            )
            counts[collection] = len(document["tasks"])
            warnings = _merge_warnings(warnings, current_warnings)
            continue

        document = new_long_document(collection)
        atomic_write_json(path, document)
        created.append(collection)
        counts[collection] = 0

    return (
        {
            "created": created,
            "schema_version": LONG_SCHEMA_VERSION,
            "kind": LONG_KIND,
            "paths": paths,
            "task_counts": counts,
        },
        warnings,
    )


def read_long(
    collection: str = ACTIVE_COLLECTION,
    *,
    long_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Read Long Tasks.

    Default reads only the active collection.
    `collection="archived"` reads only archived Tasks.
    `collection="all"` explicitly reads both.
    """
    if collection == "all":
        (
            active_path,
            active_doc,
            active_warnings,
            archived_path,
            archived_doc,
            archived_warnings,
        ) = _load_both(long_dir=long_dir)

        return (
            {
                "collection": "all",
                "documents": {
                    ACTIVE_COLLECTION: active_doc,
                    ARCHIVED_COLLECTION: archived_doc,
                },
                "paths": {
                    ACTIVE_COLLECTION: str(active_path),
                    ARCHIVED_COLLECTION: str(archived_path),
                },
                "task_counts": {
                    ACTIVE_COLLECTION: len(active_doc["tasks"]),
                    ARCHIVED_COLLECTION: len(archived_doc["tasks"]),
                },
            },
            _merge_warnings(active_warnings, archived_warnings),
        )

    if collection not in KNOWN_COLLECTIONS:
        raise InvalidLongCollectionError(
            "`collection` must be active, archived, or all."
        )

    path, document, warnings = _load_collection(
        collection,
        long_dir=long_dir,
    )

    return (
        {
            "collection": collection,
            "path": str(path),
            "document": document,
        },
        warnings,
    )


def _next_event_id(timeline: list[dict[str, Any]]) -> str:
    maximum = 0

    for event in timeline:
        if not isinstance(event, dict):
            continue

        value = event.get("id")
        if not isinstance(value, str):
            continue

        match = EVENT_ID_PATTERN.fullmatch(value.strip())
        if match is None:
            continue

        maximum = max(maximum, int(match.group("sequence")))

    return f"E{maximum + 1:03d}"


def _append_timeline_event(
    task: dict[str, Any],
    *,
    event_type: str,
    origin: str,
    text: str,
    timestamp: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timeline = task.setdefault("timeline", [])

    if not isinstance(timeline, list):
        raise InvalidLongDocumentError(
            f"Task {task.get('id')} has invalid `timeline`."
        )

    event = {
        "id": _next_event_id(timeline),
        "type": event_type,
        "origin": origin,
        "text": text,
        "at": timestamp,
        "meta": dict(meta or {}),
    }
    timeline.append(event)
    return event


def add_long(
    *,
    title: str,
    description: str = "",
    category: str = DEFAULT_CATEGORY,
    active: bool = True,
    stage: str | None = None,
    deadline: str | None = None,
    meta: dict[str, Any] | None = None,
    long_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Add one Long Task to the active collection.

    This operation intentionally does NOT create missing collection files.
    Call ensure_long() explicitly first.
    """
    (
        active_path,
        active_doc,
        active_warnings,
        _archived_path,
        archived_doc,
        archived_warnings,
    ) = _load_both(long_dir=long_dir)

    title, description, category = _normalize_title_description_category(
        title=title,
        description=description,
        category=category,
    )

    if not isinstance(active, bool):
        raise InvalidLongDocumentError(
            "`active` must be a boolean."
        )

    stage = normalize_stage(stage)
    deadline = normalize_deadline(deadline)

    if meta is None:
        meta = {}
    elif not isinstance(meta, dict):
        raise InvalidLongDocumentError(
            "`meta` must be an object."
        )

    timestamp = get_task_timestamp()

    try:
        creation_date = validate_date(timestamp[:10])
    except ValueError as exc:
        raise LongTaskError(
            "Task timestamp did not contain a valid creation date."
        ) from exc

    task_id = generate_task_id(
        active_doc["tasks"] + archived_doc["tasks"],
        prefix="L",
        date=creation_date,
    )

    task = {
        "id": task_id,
        "title": title,
        "description": description,
        "status": "pending",
        "category": category,
        "active": active,
        "stage": stage,
        "deadline": deadline,
        "archived_at": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "completed_at": None,
        "timeline": [],
        "meta": dict(meta),
    }

    active_doc["tasks"].append(task)
    atomic_write_json(active_path, active_doc)

    return (
        {
            "collection": ACTIVE_COLLECTION,
            "path": str(active_path),
            "task": task,
        },
        _merge_warnings(active_warnings, archived_warnings),
    )


def update_long(
    *,
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    category: str | None = None,
    long_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Update ordinary user-editable Long fields only:
        title, description, category

    Semantic state fields use dedicated operations.
    """
    active_path, document, warnings = _load_collection(
        ACTIVE_COLLECTION,
        long_dir=long_dir,
    )

    parse_task_id(
        task_id,
        expected_prefix="L",
    )
    _, task = find_task(document["tasks"], task_id)

    requested: dict[str, Any] = {}

    if title is not None:
        if not isinstance(title, str) or not title.strip():
            raise InvalidLongDocumentError(
                "`title` must be a non-empty string."
            )
        requested["title"] = title.strip()

    if description is not None:
        if not isinstance(description, str):
            raise InvalidLongDocumentError(
                "`description` must be a string."
            )
        requested["description"] = description

    if category is not None:
        if not isinstance(category, str) or not category.strip():
            raise InvalidLongDocumentError(
                "`category` must be a non-empty string."
            )
        requested["category"] = category.strip()

    changes = {
        field: value
        for field, value in requested.items()
        if task.get(field) != value
    }

    if not changes:
        return (
            {
                "changed": False,
                "collection": ACTIVE_COLLECTION,
                "path": str(active_path),
                "task": task,
            },
            warnings,
        )

    for field, value in changes.items():
        task[field] = value

    task["updated_at"] = get_task_timestamp()
    atomic_write_json(active_path, document)

    return (
        {
            "changed": True,
            "changed_fields": sorted(changes),
            "collection": ACTIVE_COLLECTION,
            "path": str(active_path),
            "task": task,
        },
        warnings,
    )


def set_long_status(
    *,
    task_id: str,
    status: str,
    long_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Set Long status.

    Completing a Long Task automatically deactivates it, but does not archive it.
    Reopening a completed Task does not automatically reactivate it.
    """
    active_path, document, warnings = _load_collection(
        ACTIVE_COLLECTION,
        long_dir=long_dir,
    )

    parse_task_id(task_id, expected_prefix="L")
    _, task = find_task(document["tasks"], task_id)

    if not isinstance(status, str):
        raise InvalidLongDocumentError(
            "`status` must be a string."
        )

    status = status.strip()
    current_status = task.get("status")

    if current_status == status:
        return (
            {
                "changed": False,
                "collection": ACTIVE_COLLECTION,
                "path": str(active_path),
                "task": task,
            },
            warnings,
        )

    timestamp = get_task_timestamp()
    previous_active = task.get("active")

    try:
        changed = apply_status_change(
            task,
            status,
            timestamp=timestamp,
        )
    except InvalidTaskDocumentError as exc:
        raise InvalidLongDocumentError(str(exc)) from exc

    if not changed:
        return (
            {
                "changed": False,
                "collection": ACTIVE_COLLECTION,
                "path": str(active_path),
                "task": task,
            },
            warnings,
        )

    _append_timeline_event(
        task,
        event_type="status",
        origin="system",
        text=f"Status changed from {current_status!r} to {status!r}.",
        timestamp=timestamp,
        meta={
            "from": current_status,
            "to": status,
        },
    )

    if status == "done" and previous_active is True:
        task["active"] = False
        _append_timeline_event(
            task,
            event_type="active",
            origin="system",
            text="Task deactivated after completion.",
            timestamp=timestamp,
            meta={
                "from": True,
                "to": False,
                "reason": "completed",
            },
        )

    atomic_write_json(active_path, document)

    return (
        {
            "changed": True,
            "collection": ACTIVE_COLLECTION,
            "path": str(active_path),
            "task": task,
        },
        warnings,
    )


def set_long_active(
    *,
    task_id: str,
    active: bool,
    long_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Activate or deactivate one non-archived Long Task."""
    active_path, document, warnings = _load_collection(
        ACTIVE_COLLECTION,
        long_dir=long_dir,
    )

    parse_task_id(task_id, expected_prefix="L")
    _, task = find_task(document["tasks"], task_id)

    if not isinstance(active, bool):
        raise InvalidLongDocumentError(
            "`active` must be a boolean."
        )

    if active is True and task.get("status") == "done":
        raise InvalidLongStateError(
            "A completed Long Task cannot be activated. Reopen it first."
        )

    current = task.get("active")
    if current == active:
        return (
            {
                "changed": False,
                "collection": ACTIVE_COLLECTION,
                "path": str(active_path),
                "task": task,
            },
            warnings,
        )

    timestamp = get_task_timestamp()
    task["active"] = active
    task["updated_at"] = timestamp

    _append_timeline_event(
        task,
        event_type="active",
        origin="system",
        text=f"Active state changed from {current!r} to {active!r}.",
        timestamp=timestamp,
        meta={
            "from": current,
            "to": active,
        },
    )

    atomic_write_json(active_path, document)

    return (
        {
            "changed": True,
            "collection": ACTIVE_COLLECTION,
            "path": str(active_path),
            "task": task,
        },
        warnings,
    )


def set_long_stage(
    *,
    task_id: str,
    stage: str | None,
    long_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Set or clear one Long stage.

    Stage progression is treated as a user-origin timeline event.
    """
    active_path, document, warnings = _load_collection(
        ACTIVE_COLLECTION,
        long_dir=long_dir,
    )

    parse_task_id(task_id, expected_prefix="L")
    _, task = find_task(document["tasks"], task_id)

    stage = normalize_stage(stage)
    current = task.get("stage")

    if current == stage:
        return (
            {
                "changed": False,
                "collection": ACTIVE_COLLECTION,
                "path": str(active_path),
                "task": task,
            },
            warnings,
        )

    timestamp = get_task_timestamp()
    task["stage"] = stage
    task["updated_at"] = timestamp

    _append_timeline_event(
        task,
        event_type="stage",
        origin="user",
        text=f"Stage changed from {current!r} to {stage!r}.",
        timestamp=timestamp,
        meta={
            "from": current,
            "to": stage,
        },
    )

    atomic_write_json(active_path, document)

    return (
        {
            "changed": True,
            "collection": ACTIVE_COLLECTION,
            "path": str(active_path),
            "task": task,
        },
        warnings,
    )


def set_long_deadline(
    *,
    task_id: str,
    deadline: str | None,
    long_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Set or clear one Long deadline."""
    active_path, document, warnings = _load_collection(
        ACTIVE_COLLECTION,
        long_dir=long_dir,
    )

    parse_task_id(task_id, expected_prefix="L")
    _, task = find_task(document["tasks"], task_id)

    deadline = normalize_deadline(deadline)
    current = task.get("deadline")

    if current == deadline:
        return (
            {
                "changed": False,
                "collection": ACTIVE_COLLECTION,
                "path": str(active_path),
                "task": task,
            },
            warnings,
        )

    timestamp = get_task_timestamp()
    task["deadline"] = deadline
    task["updated_at"] = timestamp

    _append_timeline_event(
        task,
        event_type="deadline",
        origin="system",
        text=f"Deadline changed from {current!r} to {deadline!r}.",
        timestamp=timestamp,
        meta={
            "from": current,
            "to": deadline,
        },
    )

    atomic_write_json(active_path, document)

    return (
        {
            "changed": True,
            "collection": ACTIVE_COLLECTION,
            "path": str(active_path),
            "task": task,
        },
        warnings,
    )


def record_long(
    *,
    task_id: str,
    text: str,
    entry_type: str = "progress",
    meta: dict[str, Any] | None = None,
    long_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Append a user-origin progress or note event to one active Long Task.
    """
    active_path, document, warnings = _load_collection(
        ACTIVE_COLLECTION,
        long_dir=long_dir,
    )

    parse_task_id(task_id, expected_prefix="L")
    _, task = find_task(document["tasks"], task_id)

    if not isinstance(text, str) or not text.strip():
        raise InvalidTimelineEventError(
            "`text` must be a non-empty string."
        )

    if not isinstance(entry_type, str) or entry_type not in USER_RECORD_TYPES:
        raise InvalidTimelineEventError(
            f"`entry_type` must be one of: "
            f"{', '.join(sorted(USER_RECORD_TYPES))}."
        )

    if meta is None:
        meta = {}
    elif not isinstance(meta, dict):
        raise InvalidTimelineEventError(
            "`meta` must be an object."
        )

    timestamp = get_task_timestamp()
    event = _append_timeline_event(
        task,
        event_type=entry_type,
        origin="user",
        text=text.strip(),
        timestamp=timestamp,
        meta=meta,
    )
    task["updated_at"] = timestamp

    atomic_write_json(active_path, document)

    return (
        {
            "changed": True,
            "collection": ACTIVE_COLLECTION,
            "path": str(active_path),
            "event": event,
            "task": task,
        },
        warnings,
    )


def _find_optional(
    tasks: list[dict[str, Any]],
    task_id: str,
) -> tuple[int, dict[str, Any]] | None:
    try:
        return find_task(tasks, task_id)
    except TaskNotFoundError:
        return None


def _base_task_for_migration_compare(
    task: dict[str, Any],
) -> dict[str, Any]:
    clone = copy.deepcopy(task)
    for field in ("active", "archived_at", "updated_at", "timeline"):
        clone.pop(field, None)
    return clone


def _is_archive_event(
    event: Any,
    *,
    action: str,
) -> bool:
    return (
        isinstance(event, dict)
        and event.get("type") == "archive"
        and event.get("origin") == "system"
        and isinstance(event.get("meta"), dict)
        and event["meta"].get("action") == action
    )


def _archive_recovery_matches(
    active_task: dict[str, Any],
    archived_task: dict[str, Any],
) -> bool:
    if archived_task.get("active") is not False:
        return False
    if archived_task.get("archived_at") is None:
        return False
    if _base_task_for_migration_compare(active_task) != _base_task_for_migration_compare(archived_task):
        return False

    active_timeline = active_task.get("timeline", [])
    archived_timeline = archived_task.get("timeline", [])

    if not isinstance(active_timeline, list) or not isinstance(archived_timeline, list):
        return False

    if archived_timeline[: len(active_timeline)] != active_timeline:
        return False

    suffix = archived_timeline[len(active_timeline):]

    if len(suffix) not in {1, 2}:
        return False

    if len(suffix) == 2:
        active_event, archive_event = suffix
        if not (
            isinstance(active_event, dict)
            and active_event.get("type") == "active"
            and active_event.get("origin") == "system"
            and active_event.get("meta", {}).get("to") is False
        ):
            return False
    else:
        archive_event = suffix[0]

    return _is_archive_event(
        archive_event,
        action="archive",
    )


def _unarchive_recovery_matches(
    active_task: dict[str, Any],
    archived_task: dict[str, Any],
) -> bool:
    if active_task.get("active") is not False:
        return False
    if active_task.get("archived_at") is not None:
        return False
    if _base_task_for_migration_compare(active_task) != _base_task_for_migration_compare(archived_task):
        return False

    archived_timeline = archived_task.get("timeline", [])
    active_timeline = active_task.get("timeline", [])

    if not isinstance(active_timeline, list) or not isinstance(archived_timeline, list):
        return False

    if active_timeline[: len(archived_timeline)] != archived_timeline:
        return False

    suffix = active_timeline[len(archived_timeline):]

    return (
        len(suffix) == 1
        and _is_archive_event(
            suffix[0],
            action="restore",
        )
    )


def archive_long(
    *,
    task_id: str,
    long_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Move one Long Task from active to archived.

    Safe order:
        1. write archived copy
        2. delete active copy

    If interrupted after step 1, the next archive call recognizes the
    migration copy and completes step 2.
    """
    parse_task_id(task_id, expected_prefix="L")

    (
        active_path,
        active_doc,
        active_warnings,
        archived_path,
        archived_doc,
        archived_warnings,
    ) = _load_both(long_dir=long_dir)

    warnings = _merge_warnings(active_warnings, archived_warnings)

    active_match = _find_optional(active_doc["tasks"], task_id)
    archived_match = _find_optional(archived_doc["tasks"], task_id)

    if active_match is None and archived_match is None:
        raise TaskNotFoundError(
            f"Task ID was not found: {task_id}"
        )

    if active_match is None and archived_match is not None:
        return (
            {
                "changed": False,
                "collection": ARCHIVED_COLLECTION,
                "path": str(archived_path),
                "task": archived_match[1],
            },
            warnings,
        )

    if active_match is not None and archived_match is not None:
        active_index, active_task = active_match
        _archived_index, archived_task = archived_match

        if not _archive_recovery_matches(active_task, archived_task):
            raise LongCollectionConflictError(
                f"Task {task_id} exists in both Long collections and does not "
                "match a recoverable interrupted archive."
            )

        active_doc["tasks"].pop(active_index)
        atomic_write_json(active_path, active_doc)

        warnings = _merge_warnings(
            warnings,
            ["ARCHIVE_RECOVERED"],
        )

        return (
            {
                "changed": True,
                "recovered": True,
                "collection": ARCHIVED_COLLECTION,
                "active_path": str(active_path),
                "archived_path": str(archived_path),
                "task": archived_task,
            },
            warnings,
        )

    active_index, active_task = active_match  # type: ignore[misc]
    timestamp = get_task_timestamp()

    archived_task = copy.deepcopy(active_task)
    previous_active = archived_task.get("active")

    if previous_active is True:
        archived_task["active"] = False
        _append_timeline_event(
            archived_task,
            event_type="active",
            origin="system",
            text="Task deactivated for archive.",
            timestamp=timestamp,
            meta={
                "from": True,
                "to": False,
                "reason": "archive",
            },
        )

    archived_task["archived_at"] = timestamp
    archived_task["updated_at"] = timestamp

    _append_timeline_event(
        archived_task,
        event_type="archive",
        origin="system",
        text="Task moved to archived collection.",
        timestamp=timestamp,
        meta={
            "action": "archive",
        },
    )

    archived_doc["tasks"].append(archived_task)

    # Copy first. If the process stops here, recovery is possible.
    atomic_write_json(archived_path, archived_doc)

    active_doc["tasks"].pop(active_index)
    atomic_write_json(active_path, active_doc)

    return (
        {
            "changed": True,
            "recovered": False,
            "collection": ARCHIVED_COLLECTION,
            "active_path": str(active_path),
            "archived_path": str(archived_path),
            "task": archived_task,
        },
        warnings,
    )


def unarchive_long(
    *,
    task_id: str,
    long_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Restore one Long Task from archived to active collection.

    Safe order:
        1. write active copy
        2. delete archived copy

    Restored Tasks remain active=false. Reactivation is explicit.
    """
    parse_task_id(task_id, expected_prefix="L")

    (
        active_path,
        active_doc,
        active_warnings,
        archived_path,
        archived_doc,
        archived_warnings,
    ) = _load_both(long_dir=long_dir)

    warnings = _merge_warnings(active_warnings, archived_warnings)

    active_match = _find_optional(active_doc["tasks"], task_id)
    archived_match = _find_optional(archived_doc["tasks"], task_id)

    if active_match is None and archived_match is None:
        raise TaskNotFoundError(
            f"Task ID was not found: {task_id}"
        )

    if active_match is not None and archived_match is None:
        return (
            {
                "changed": False,
                "collection": ACTIVE_COLLECTION,
                "path": str(active_path),
                "task": active_match[1],
            },
            warnings,
        )

    if active_match is not None and archived_match is not None:
        _active_index, active_task = active_match
        archived_index, archived_task = archived_match

        if not _unarchive_recovery_matches(active_task, archived_task):
            raise LongCollectionConflictError(
                f"Task {task_id} exists in both Long collections and does not "
                "match a recoverable interrupted unarchive."
            )

        archived_doc["tasks"].pop(archived_index)
        atomic_write_json(archived_path, archived_doc)

        warnings = _merge_warnings(
            warnings,
            ["UNARCHIVE_RECOVERED"],
        )

        return (
            {
                "changed": True,
                "recovered": True,
                "collection": ACTIVE_COLLECTION,
                "active_path": str(active_path),
                "archived_path": str(archived_path),
                "task": active_task,
            },
            warnings,
        )

    archived_index, archived_task = archived_match  # type: ignore[misc]
    timestamp = get_task_timestamp()

    active_task = copy.deepcopy(archived_task)
    active_task["active"] = False
    active_task["archived_at"] = None
    active_task["updated_at"] = timestamp

    _append_timeline_event(
        active_task,
        event_type="archive",
        origin="system",
        text="Task restored from archived collection.",
        timestamp=timestamp,
        meta={
            "action": "restore",
        },
    )

    active_doc["tasks"].append(active_task)

    # Copy first. If the process stops here, recovery is possible.
    atomic_write_json(active_path, active_doc)

    archived_doc["tasks"].pop(archived_index)
    atomic_write_json(archived_path, archived_doc)

    return (
        {
            "changed": True,
            "recovered": False,
            "collection": ACTIVE_COLLECTION,
            "active_path": str(active_path),
            "archived_path": str(archived_path),
            "task": active_task,
        },
        warnings,
    )
