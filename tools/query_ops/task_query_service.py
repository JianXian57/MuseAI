#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Deterministic Task Query service for MuseAI.

Recommended location:
    MuseAI/tools/query_ops/task_query_service.py

Purpose
-------
Provide compact, high-frequency, strictly read-only Task retrieval for Main.

The Query service consumes validated Task facts through the Task read facade
and authoritative Task services. It deliberately returns compact projections
instead of complete Task documents so Main does not need to parse large
runtime JSON structures or Long timelines for ordinary information requests.

Boundary
--------
This service may:
- read;
- filter;
- derive deterministic date/schedule state;
- aggregate counts;
- resolve direct Task relationships.

This service must not:
- create, update, delete, complete, archive, or otherwise mutate Task data;
- run Daily Init or Task Maintenance;
- refresh external data;
- build MuseAI public Tool Results;
- parse CLI arguments;
- print output;
- write lifecycle logs.
"""

from __future__ import annotations

from datetime import date as date_type
from pathlib import Path
from typing import Any, Iterable

from query_ops.query_errors import (
    InvalidQueryDataError,
    InvalidQueryFilterError,
    QueryTaskNotFoundError,
)
from task_ops.long_service import LongFileNotFoundError, read_long
from task_ops.standing_service import schedule_matches_date
from task_ops.task_read_service import (
    read_daily_tasks,
    read_long_tasks,
    read_standing_tasks,
    read_task_context,
    resolve_task_read_date,
)
from task_ops.task_service import parse_task_id


DEFAULT_LIMIT = 50
MAX_LIMIT = 200

KNOWN_STATUSES = {"pending", "done"}
KNOWN_LONG_COLLECTIONS = {"active", "archived", "all"}
KNOWN_DEADLINE_STATES = {
    "none",
    "future",
    "due_today",
    "overdue",
    "completed",
}
KNOWN_SCHEDULE_TYPES = {"daily", "weekly", "monthly", "yearly"}


def _merge_warnings(*groups: Iterable[str]) -> list[str]:
    merged: list[str] = []

    for group in groups:
        for warning in group:
            text = str(warning)
            if text not in merged:
                merged.append(text)

    return merged


def _optional_text(
    value: Any,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str) or not value.strip():
        raise InvalidQueryFilterError(
            f"`{field_name}` must be null or a non-empty string."
        )

    return value.strip()


def _optional_bool(
    value: Any,
    *,
    field_name: str,
) -> bool | None:
    if value is None:
        return None

    if not isinstance(value, bool):
        raise InvalidQueryFilterError(
            f"`{field_name}` must be null or a boolean."
        )

    return value


def _choice(
    value: Any,
    *,
    field_name: str,
    choices: set[str],
) -> str | None:
    value = _optional_text(value, field_name=field_name)

    if value is None:
        return None

    normalized = value.lower()

    if normalized not in choices:
        raise InvalidQueryFilterError(
            f"`{field_name}` must be one of: {', '.join(sorted(choices))}."
        )

    return normalized


def _normalize_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidQueryFilterError("`limit` must be an integer.")

    if value < 1 or value > MAX_LIMIT:
        raise InvalidQueryFilterError(
            f"`limit` must be from 1 to {MAX_LIMIT}."
        )

    return value


def _contains_text(task: dict[str, Any], text: str | None) -> bool:
    if text is None:
        return True

    needle = text.casefold()
    haystack = "\n".join(
        str(task.get(field) or "")
        for field in ("title", "description")
    ).casefold()

    return needle in haystack


def _page(
    items: list[dict[str, Any]],
    *,
    limit: int,
) -> dict[str, Any]:
    total = len(items)
    returned = items[:limit]

    return {
        "total_count": total,
        "returned_count": len(returned),
        "truncated": total > len(returned),
        "items": returned,
    }


def _compact_daily(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "description": task.get("description"),
        "status": task.get("status"),
        "category": task.get("category"),
        "source": task.get("source"),
        "long_task_id": task.get("long_task_id"),
        "standing_task_id": task.get("standing_task_id"),
        "carryover_from_task_id": task.get("carryover_from_task_id"),
    }


def _deadline_state(
    task: dict[str, Any],
    *,
    target_date: str,
) -> tuple[str, int | None]:
    deadline = task.get("deadline")

    if deadline is None:
        return "none", None

    if task.get("status") == "done":
        return "completed", None

    target = date_type.fromisoformat(target_date)
    deadline_date = date_type.fromisoformat(str(deadline))

    if deadline_date < target:
        return "overdue", (target - deadline_date).days

    if deadline_date == target:
        return "due_today", None

    return "future", None


def _compact_long(
    task: dict[str, Any],
    *,
    collection: str,
    target_date: str,
) -> dict[str, Any]:
    state, days_overdue = _deadline_state(
        task,
        target_date=target_date,
    )

    result = {
        "id": task.get("id"),
        "title": task.get("title"),
        "description": task.get("description"),
        "status": task.get("status"),
        "category": task.get("category"),
        "active": task.get("active"),
        "stage": task.get("stage"),
        "deadline": task.get("deadline"),
        "deadline_state": state,
        "collection": collection,
        "archived_at": task.get("archived_at"),
        "timeline_count": len(task.get("timeline") or []),
    }

    if days_overdue is not None:
        result["days_overdue"] = days_overdue

    return result


def _standing_state(
    task: dict[str, Any],
    *,
    target_date: str,
) -> dict[str, Any]:
    schedule_match = bool(
        schedule_matches_date(
            task["schedule"],
            target_date,
        )
    )
    enabled = task.get("enabled") is True
    scheduled = bool(enabled and schedule_match)
    already_generated = task.get("last_generated_date") == target_date
    due = bool(scheduled and not already_generated)

    return {
        "schedule_match": schedule_match,
        "scheduled": scheduled,
        "already_generated": already_generated,
        "due": due,
    }


def _compact_standing(
    task: dict[str, Any],
    *,
    target_date: str,
) -> dict[str, Any]:
    state = _standing_state(
        task,
        target_date=target_date,
    )

    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "description": task.get("description"),
        "status": task.get("status"),
        "category": task.get("category"),
        "enabled": task.get("enabled"),
        "schedule": task.get("schedule"),
        "long_task_id": task.get("long_task_id"),
        "last_generated_date": task.get("last_generated_date"),
        "query_state": state,
    }


def _filters_dict(**values: Any) -> dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if value is not None
    }


def query_daily_tasks(
    date: str | None = None,
    *,
    status: str | None = None,
    source: str | None = None,
    category: str | None = None,
    long_task_id: str | None = None,
    standing_task_id: str | None = None,
    task_id: str | None = None,
    text: str | None = None,
    limit: int = DEFAULT_LIMIT,
    daily_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Query one Daily collection using compact read-only filters."""
    task_id = _optional_text(task_id, field_name="task_id")
    parsed_task_id = None

    if task_id is not None:
        parsed_task_id = parse_task_id(task_id, expected_prefix="D")

    if date is None and parsed_task_id is not None:
        target_date = str(parsed_task_id["date"])
    else:
        target_date = resolve_task_read_date(date)

    status = _choice(
        status,
        field_name="status",
        choices=KNOWN_STATUSES,
    )
    source = _optional_text(source, field_name="source")
    category = _optional_text(category, field_name="category")
    long_task_id = _optional_text(
        long_task_id,
        field_name="long_task_id",
    )
    standing_task_id = _optional_text(
        standing_task_id,
        field_name="standing_task_id",
    )
    text = _optional_text(text, field_name="text")
    limit = _normalize_limit(limit)

    if (
        parsed_task_id is not None
        and parsed_task_id["date"] != target_date
    ):
        raise InvalidQueryFilterError(
            f"Daily Task ID {task_id} belongs to {parsed_task_id['date']}, "
            f"not requested date {target_date}."
        )

    daily, warnings = read_daily_tasks(
        target_date,
        allow_missing=True,
        daily_dir=daily_dir,
    )

    matched: list[dict[str, Any]] = []

    for task in daily["tasks"]:
        if status is not None and task.get("status") != status:
            continue
        if source is not None and task.get("source") != source:
            continue
        if category is not None and task.get("category") != category:
            continue
        if long_task_id is not None and task.get("long_task_id") != long_task_id:
            continue
        if (
            standing_task_id is not None
            and task.get("standing_task_id") != standing_task_id
        ):
            continue
        if task_id is not None and task.get("id") != task_id:
            continue
        if not _contains_text(task, text):
            continue

        matched.append(_compact_daily(task))

    filters = _filters_dict(
        status=status,
        source=source,
        category=category,
        long_task_id=long_task_id,
        standing_task_id=standing_task_id,
        task_id=task_id,
        text=text,
    )

    return (
        {
            "query": "task.daily",
            "date": target_date,
            "exists": bool(daily["exists"]),
            "filters": filters,
            "limit": limit,
            **_page(matched, limit=limit),
        },
        warnings,
    )


def _read_long_collection_for_query(
    collection: str,
    *,
    allow_missing: bool,
    long_dir: str | Path | None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Read exactly one Long collection through the authoritative Long service.

    This helper exists so a scoped Query does not depend on unrelated Long
    collections. In particular, an archived-only Query must remain usable when
    the active collection is missing or invalid.

    No Task JSON is parsed directly here.
    """
    try:
        result, warnings = read_long(
            collection,
            long_dir=long_dir,
        )
    except LongFileNotFoundError:
        if not allow_missing:
            raise

        return (
            {
                "exists": False,
                "collection": collection,
                "tasks": [],
            },
            [],
        )

    document = result["document"]

    return (
        {
            "exists": True,
            "collection": collection,
            "tasks": document["tasks"],
        },
        warnings,
    )


def _long_collections(
    long_data: dict[str, Any],
    collection: str,
) -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []

    if collection in {"active", "all"}:
        result.append(("active", long_data["active"]))

    if collection in {"archived", "all"}:
        archived = long_data.get("archived")
        if archived is not None:
            result.append(("archived", archived))

    return result


def query_long_tasks(
    date: str | None = None,
    *,
    collection: str = "active",
    status: str | None = None,
    active: bool | None = None,
    category: str | None = None,
    stage: str | None = None,
    deadline_state: str | None = None,
    task_id: str | None = None,
    text: str | None = None,
    limit: int = DEFAULT_LIMIT,
    long_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Query Long Tasks across active and/or archived collections."""
    target_date = resolve_task_read_date(date)
    collection = _choice(
        collection,
        field_name="collection",
        choices=KNOWN_LONG_COLLECTIONS,
    ) or "active"
    status = _choice(
        status,
        field_name="status",
        choices=KNOWN_STATUSES,
    )
    active = _optional_bool(active, field_name="active")
    category = _optional_text(category, field_name="category")
    stage = _optional_text(stage, field_name="stage")
    deadline_state = _choice(
        deadline_state,
        field_name="deadline_state",
        choices=KNOWN_DEADLINE_STATES,
    )
    task_id = _optional_text(task_id, field_name="task_id")
    text = _optional_text(text, field_name="text")
    limit = _normalize_limit(limit)

    if task_id is not None:
        parse_task_id(task_id, expected_prefix="L")

    if collection == "archived":
        archived, warnings = _read_long_collection_for_query(
            "archived",
            allow_missing=True,
            long_dir=long_dir,
        )
        long_data = {
            "archived": archived,
        }
    else:
        include_archived = collection == "all"
        long_data, warnings = read_long_tasks(
            include_archived=include_archived,
            allow_missing=True,
            long_dir=long_dir,
        )

    matched: list[dict[str, Any]] = []
    collection_exists: dict[str, bool] = {}

    for collection_name, source_collection in _long_collections(
        long_data,
        collection,
    ):
        collection_exists[collection_name] = bool(
            source_collection["exists"]
        )

        for task in source_collection["tasks"]:
            state, _ = _deadline_state(
                task,
                target_date=target_date,
            )

            if status is not None and task.get("status") != status:
                continue
            if active is not None and task.get("active") is not active:
                continue
            if category is not None and task.get("category") != category:
                continue
            if stage is not None and task.get("stage") != stage:
                continue
            if deadline_state is not None and state != deadline_state:
                continue
            if task_id is not None and task.get("id") != task_id:
                continue
            if not _contains_text(task, text):
                continue

            matched.append(
                _compact_long(
                    task,
                    collection=collection_name,
                    target_date=target_date,
                )
            )

    filters = _filters_dict(
        collection=collection,
        status=status,
        active=active,
        category=category,
        stage=stage,
        deadline_state=deadline_state,
        task_id=task_id,
        text=text,
    )

    return (
        {
            "query": "task.long",
            "date": target_date,
            "collection_exists": collection_exists,
            "filters": filters,
            "limit": limit,
            **_page(matched, limit=limit),
        },
        warnings,
    )


def query_standing_tasks(
    date: str | None = None,
    *,
    enabled: bool | None = None,
    category: str | None = None,
    schedule_type: str | None = None,
    long_task_id: str | None = None,
    scheduled: bool | None = None,
    due: bool | None = None,
    task_id: str | None = None,
    text: str | None = None,
    limit: int = DEFAULT_LIMIT,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Query Standing rules plus deterministic state for one date."""
    target_date = resolve_task_read_date(date)
    enabled = _optional_bool(enabled, field_name="enabled")
    category = _optional_text(category, field_name="category")
    schedule_type = _choice(
        schedule_type,
        field_name="schedule_type",
        choices=KNOWN_SCHEDULE_TYPES,
    )
    long_task_id = _optional_text(
        long_task_id,
        field_name="long_task_id",
    )
    scheduled = _optional_bool(scheduled, field_name="scheduled")
    due = _optional_bool(due, field_name="due")
    task_id = _optional_text(task_id, field_name="task_id")
    text = _optional_text(text, field_name="text")
    limit = _normalize_limit(limit)

    if task_id is not None:
        parse_task_id(task_id, expected_prefix="S")

    standing, warnings = read_standing_tasks(
        allow_missing=True,
        standing_dir=standing_dir,
    )

    matched: list[dict[str, Any]] = []

    for task in standing["tasks"]:
        state = _standing_state(
            task,
            target_date=target_date,
        )

        if enabled is not None and task.get("enabled") is not enabled:
            continue
        if category is not None and task.get("category") != category:
            continue
        if (
            schedule_type is not None
            and (task.get("schedule") or {}).get("type") != schedule_type
        ):
            continue
        if long_task_id is not None and task.get("long_task_id") != long_task_id:
            continue
        if scheduled is not None and state["scheduled"] is not scheduled:
            continue
        if due is not None and state["due"] is not due:
            continue
        if task_id is not None and task.get("id") != task_id:
            continue
        if not _contains_text(task, text):
            continue

        matched.append(
            _compact_standing(
                task,
                target_date=target_date,
            )
        )

    filters = _filters_dict(
        enabled=enabled,
        category=category,
        schedule_type=schedule_type,
        long_task_id=long_task_id,
        scheduled=scheduled,
        due=due,
        task_id=task_id,
        text=text,
    )

    return (
        {
            "query": "task.standing",
            "date": target_date,
            "exists": bool(standing["exists"]),
            "filters": filters,
            "limit": limit,
            **_page(matched, limit=limit),
        },
        warnings,
    )


def _find_long_by_id(
    task_id: str,
    *,
    target_date: str,
    long_dir: str | Path | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    long_data, warnings = read_long_tasks(
        include_archived=True,
        allow_missing=True,
        long_dir=long_dir,
    )

    for collection_name in ("active", "archived"):
        collection = long_data.get(collection_name)
        if not collection:
            continue

        for task in collection["tasks"]:
            if task.get("id") == task_id:
                return (
                    _compact_long(
                        task,
                        collection=collection_name,
                        target_date=target_date,
                    ),
                    warnings,
                )

    return None, warnings


def _find_standing_by_id(
    task_id: str,
    *,
    target_date: str,
    standing_dir: str | Path | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    standing, warnings = read_standing_tasks(
        allow_missing=True,
        standing_dir=standing_dir,
    )

    for task in standing["tasks"]:
        if task.get("id") == task_id:
            return (
                _compact_standing(
                    task,
                    target_date=target_date,
                ),
                warnings,
            )

    return None, warnings


def _find_daily_by_id(
    task_id: str,
    *,
    daily_dir: str | Path | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    parsed = parse_task_id(task_id, expected_prefix="D")
    daily, warnings = read_daily_tasks(
        parsed["date"],
        allow_missing=True,
        daily_dir=daily_dir,
    )

    for task in daily["tasks"]:
        if task.get("id") == task_id:
            return _compact_daily(task), warnings

    return None, warnings


def _daily_dates(
    *,
    daily_dir: str | Path | None,
) -> list[str]:
    """
    Discover Daily dates by filename only.

    File contents are never parsed here; every selected collection is loaded
    and validated through read_daily_tasks().
    """
    # Resolve the authoritative Daily directory without importing or duplicating
    # its default constant: resolve a harmless valid Daily path through the
    # Task read facade's underlying path contract.
    from task_ops.daily_service import resolve_daily_path

    directory = resolve_daily_path(
        "2000-01-01",
        daily_dir=daily_dir,
    ).parent

    if not directory.exists():
        return []

    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        raise InvalidQueryDataError(
            f"Could not list Daily Task directory {directory}: {exc}"
        ) from exc

    dates: list[str] = []

    for path in entries:
        if not path.is_file() or path.suffix.lower() != ".json":
            continue

        stem = path.stem
        if len(stem) != 8 or not stem.isdigit():
            continue

        try:
            date_value = date_type(
                int(stem[0:4]),
                int(stem[4:6]),
                int(stem[6:8]),
            ).isoformat()
        except ValueError:
            # Match Task Read Facade discovery semantics: malformed numeric
            # filenames are not valid Daily collections and are ignored.
            continue

        dates.append(date_value)

    dates.sort()
    return dates


def _read_all_daily_tasks(
    *,
    daily_dir: str | Path | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    all_items: list[dict[str, Any]] = []
    warning_groups: list[list[str]] = []

    for date_value in _daily_dates(daily_dir=daily_dir):
        daily, warnings = read_daily_tasks(
            date_value,
            allow_missing=True,
            daily_dir=daily_dir,
        )
        warning_groups.append(warnings)

        if not daily["exists"]:
            continue

        for task in daily["tasks"]:
            item = _compact_daily(task)
            item["date"] = date_value
            all_items.append(item)

    # Relationships are usually most useful with recent occurrences first.
    all_items.sort(
        key=lambda item: str(item.get("id") or ""),
        reverse=True,
    )

    return all_items, _merge_warnings(*warning_groups)


def _missing_relation(task_id: str) -> dict[str, Any]:
    return {
        "id": task_id,
        "exists": False,
    }


def query_related_tasks(
    task_id: str,
    *,
    date: str | None = None,
    limit: int = DEFAULT_LIMIT,
    daily_dir: str | Path | None = None,
    long_dir: str | Path | None = None,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Resolve direct relationships for one exact Daily / Long / Standing Task.

    This is intentionally a one-hop relationship query, not a recursive graph
    traversal.
    """
    task_id = _optional_text(task_id, field_name="task_id")
    if task_id is None:
        raise InvalidQueryFilterError("`task_id` is required.")

    parsed = parse_task_id(task_id)
    target_date = resolve_task_read_date(date)
    limit = _normalize_limit(limit)

    warnings: list[str] = []
    prefix = parsed["prefix"]

    if prefix == "D":
        target, target_warnings = _find_daily_by_id(
            task_id,
            daily_dir=daily_dir,
        )
    elif prefix == "L":
        target, target_warnings = _find_long_by_id(
            task_id,
            target_date=target_date,
            long_dir=long_dir,
        )
    else:
        target, target_warnings = _find_standing_by_id(
            task_id,
            target_date=target_date,
            standing_dir=standing_dir,
        )

    warnings = _merge_warnings(warnings, target_warnings)

    if target is None:
        raise QueryTaskNotFoundError(
            f"Task {task_id} was not found."
        )

    relations: dict[str, Any] = {}

    if prefix == "D":
        long_id = target.get("long_task_id")
        standing_id = target.get("standing_task_id")
        carryover_parent_id = target.get("carryover_from_task_id")

        linked_long = None
        if long_id:
            linked_long, linked_warnings = _find_long_by_id(
                long_id,
                target_date=target_date,
                long_dir=long_dir,
            )
            warnings = _merge_warnings(warnings, linked_warnings)
            if linked_long is None:
                linked_long = _missing_relation(long_id)

        linked_standing = None
        if standing_id:
            linked_standing, linked_warnings = _find_standing_by_id(
                standing_id,
                target_date=target_date,
                standing_dir=standing_dir,
            )
            warnings = _merge_warnings(warnings, linked_warnings)
            if linked_standing is None:
                linked_standing = _missing_relation(standing_id)

        carryover_parent = None
        if carryover_parent_id:
            carryover_parent, linked_warnings = _find_daily_by_id(
                carryover_parent_id,
                daily_dir=daily_dir,
            )
            warnings = _merge_warnings(warnings, linked_warnings)
            if carryover_parent is None:
                carryover_parent = _missing_relation(
                    carryover_parent_id
                )

        all_daily, daily_warnings = _read_all_daily_tasks(
            daily_dir=daily_dir,
        )
        warnings = _merge_warnings(warnings, daily_warnings)
        children = [
            item
            for item in all_daily
            if item.get("carryover_from_task_id") == task_id
        ]

        relations = {
            "long": linked_long,
            "standing": linked_standing,
            "carryover_parent": carryover_parent,
            "carryover_children": _page(children, limit=limit),
        }

    elif prefix == "L":
        all_daily, daily_warnings = _read_all_daily_tasks(
            daily_dir=daily_dir,
        )
        standing, standing_warnings = read_standing_tasks(
            allow_missing=True,
            standing_dir=standing_dir,
        )
        warnings = _merge_warnings(
            warnings,
            daily_warnings,
            standing_warnings,
        )

        daily_relations = [
            item
            for item in all_daily
            if item.get("long_task_id") == task_id
        ]
        standing_relations = [
            _compact_standing(
                task,
                target_date=target_date,
            )
            for task in standing["tasks"]
            if task.get("long_task_id") == task_id
        ]

        relations = {
            "daily": _page(daily_relations, limit=limit),
            "standing": _page(standing_relations, limit=limit),
        }

    else:
        long_id = target.get("long_task_id")

        linked_long = None
        if long_id:
            linked_long, linked_warnings = _find_long_by_id(
                long_id,
                target_date=target_date,
                long_dir=long_dir,
            )
            warnings = _merge_warnings(warnings, linked_warnings)
            if linked_long is None:
                linked_long = _missing_relation(long_id)

        all_daily, daily_warnings = _read_all_daily_tasks(
            daily_dir=daily_dir,
        )
        warnings = _merge_warnings(warnings, daily_warnings)
        daily_relations = [
            item
            for item in all_daily
            if item.get("standing_task_id") == task_id
        ]

        relations = {
            "long": linked_long,
            "daily": _page(daily_relations, limit=limit),
        }

    return (
        {
            "query": "task.related",
            "task_id": task_id,
            "kind": {
                "D": "daily",
                "L": "long",
                "S": "standing",
            }[prefix],
            "date": target_date,
            "limit": limit,
            "task": target,
            "relations": relations,
        },
        warnings,
    )


def query_task_overview(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
    long_dir: str | Path | None = None,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Build a compact machine-fact overview without Report semantics."""
    target_date = resolve_task_read_date(date)

    context, warnings = read_task_context(
        target_date,
        include_archived_long=False,
        allow_missing=True,
        daily_dir=daily_dir,
        long_dir=long_dir,
        standing_dir=standing_dir,
    )

    daily = context["daily"]
    long_active = context["long"]["active"]
    standing = context["standing"]

    daily_tasks = daily["tasks"] if daily["exists"] else []
    long_tasks = (
        long_active["tasks"]
        if long_active["exists"]
        else []
    )
    standing_tasks = (
        standing["tasks"]
        if standing["exists"]
        else []
    )

    long_states = [
        _deadline_state(
            task,
            target_date=target_date,
        )[0]
        for task in long_tasks
    ]
    standing_states = [
        _standing_state(
            task,
            target_date=target_date,
        )
        for task in standing_tasks
    ]

    return (
        {
            "query": "task.overview",
            "date": target_date,
            "daily": {
                "exists": bool(daily["exists"]),
                "total": len(daily_tasks),
                "pending": sum(
                    1
                    for task in daily_tasks
                    if task.get("status") == "pending"
                ),
                "done": sum(
                    1
                    for task in daily_tasks
                    if task.get("status") == "done"
                ),
                "manual": sum(
                    1
                    for task in daily_tasks
                    if task.get("source") == "manual"
                ),
                "carryover": sum(
                    1
                    for task in daily_tasks
                    if task.get("source") == "carryover"
                ),
                "standing": sum(
                    1
                    for task in daily_tasks
                    if task.get("source") == "standing"
                ),
            },
            "long": {
                "exists": bool(long_active["exists"]),
                "total": len(long_tasks),
                "pending": sum(
                    1
                    for task in long_tasks
                    if task.get("status") == "pending"
                ),
                "done": sum(
                    1
                    for task in long_tasks
                    if task.get("status") == "done"
                ),
                "active": sum(
                    1
                    for task in long_tasks
                    if task.get("active") is True
                ),
                "due_today": long_states.count("due_today"),
                "overdue": long_states.count("overdue"),
            },
            "standing": {
                "exists": bool(standing["exists"]),
                "total": len(standing_tasks),
                "enabled": sum(
                    1
                    for task in standing_tasks
                    if task.get("enabled") is True
                ),
                "disabled": sum(
                    1
                    for task in standing_tasks
                    if task.get("enabled") is False
                ),
                "scheduled": sum(
                    1
                    for state in standing_states
                    if state["scheduled"]
                ),
                "due": sum(
                    1
                    for state in standing_states
                    if state["due"]
                ),
                "already_generated_today": sum(
                    1
                    for state in standing_states
                    if state["already_generated"]
                ),
            },
        },
        warnings,
    )
