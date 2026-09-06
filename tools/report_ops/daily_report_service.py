#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Deterministic Daily Report snapshot service for MuseAI.

Recommended location:
    MuseAI/tools/report_ops/daily_report_service.py

Purpose
-------
Build one compact, read-only Daily Report snapshot for Main.

The service consumes validated Task facts through task_read_service.py:
- today's Daily Tasks;
- the nearest previous Daily collection;
- current Long Tasks.

It deliberately does not read Standing directly. The normal MuseAI daily
workflow runs Task Maintenance before Daily Report, so Standing occurrences
that matter today are already represented in today's Daily Tasks.

Boundary
--------
This service:
- reads Task data only through the Task read facade;
- calculates deterministic report counts and date-derived states;
- trims Task objects to report-relevant fields;
- returns plain Python data plus warnings.

This service does not:
- write or create Task data;
- run Task Maintenance;
- read Task JSON directly;
- calculate Standing recurrence;
- perform general-purpose Task query;
- write natural-language reports;
- print output;
- build MuseAI public Tool results;
- write lifecycle logs.
"""

from __future__ import annotations

from datetime import date as date_type
from pathlib import Path
from typing import Any, Iterable

from common.time_service import get_current_time
from task_ops.task_read_service import (
    read_daily_tasks,
    read_long_tasks,
    read_previous_daily_tasks,
    resolve_task_read_date,
)


TARGET_DAILY_NOT_INITIALIZED = "TARGET_DAILY_NOT_INITIALIZED"


class DailyReportServiceError(Exception):
    """Base exception for deterministic Daily Report snapshot failures."""


class InvalidDailyReportDataError(DailyReportServiceError):
    """Validated Task data is internally inconsistent for report building."""


def _merge_warnings(*groups: Iterable[str]) -> list[str]:
    merged: list[str] = []

    for group in groups:
        for warning in group:
            text = str(warning)
            if text not in merged:
                merged.append(text)

    return merged


def _resolve_report_context(
    date: str | None,
    *,
    config_path: str | Path | None,
) -> tuple[str, str]:
    """
    Resolve report date and generation timestamp from one time snapshot.

    For date=None, the configured current date is taken from the same
    get_current_time() result used for generated_at, avoiding a midnight split.
    """
    time_context = get_current_time(config_path)

    if date is None:
        target_date = str(time_context["current_date"])
    else:
        target_date = resolve_task_read_date(date)

    now = time_context["datetime"]
    generated_at = now.isoformat(timespec="seconds")

    return target_date, generated_at


def _trim_daily_task(task: dict[str, Any]) -> dict[str, Any]:
    """Return only fields useful to the Daily Report reasoning layer."""
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


def _trim_previous_completed_task(task: dict[str, Any]) -> dict[str, Any]:
    """Keep previous-day completion context intentionally compact."""
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "category": task.get("category"),
        "source": task.get("source"),
    }


def _trim_long_task(
    task: dict[str, Any],
    *,
    days_overdue: int | None = None,
) -> dict[str, Any]:
    result = {
        "id": task.get("id"),
        "title": task.get("title"),
        "description": task.get("description"),
        "status": task.get("status"),
        "category": task.get("category"),
        "active": task.get("active"),
        "stage": task.get("stage"),
        "deadline": task.get("deadline"),
    }

    if days_overdue is not None:
        result["days_overdue"] = days_overdue

    return result


def _build_today_snapshot(
    daily: dict[str, Any],
) -> dict[str, Any]:
    tasks = daily["tasks"] if daily["exists"] else []

    pending: list[dict[str, Any]] = []
    done: list[dict[str, Any]] = []
    carryover: list[dict[str, Any]] = []
    standing: list[dict[str, Any]] = []

    source_counts = {
        "manual": 0,
        "carryover": 0,
        "standing": 0,
        "other": 0,
    }

    for task in tasks:
        item = _trim_daily_task(task)
        status = task.get("status")
        source = task.get("source")

        if status == "pending":
            pending.append(item)
        elif status == "done":
            done.append(item)
        else:
            raise InvalidDailyReportDataError(
                f"Daily Task {task.get('id')!r} has unsupported status "
                f"{status!r} after validation."
            )

        if source in ("manual", "carryover", "standing"):
            source_counts[source] += 1
        else:
            source_counts["other"] += 1

        if source == "carryover":
            carryover.append(item)
        elif source == "standing":
            standing.append(item)

    return {
        "exists": bool(daily["exists"]),
        "path": daily.get("path"),
        "counts": {
            "total": len(tasks),
            "pending": len(pending),
            "done": len(done),
            "manual": source_counts["manual"],
            "carryover": source_counts["carryover"],
            "standing": source_counts["standing"],
            "other_source": source_counts["other"],
        },
        "pending": pending,
        "done": done,
        "carryover": carryover,
        "standing": standing,
    }


def _build_previous_snapshot(
    previous: dict[str, Any],
    *,
    target_date: str,
) -> dict[str, Any]:
    if not previous["exists"]:
        return {
            "exists": False,
            "date": None,
            "days_gap": None,
            "counts": {
                "total": 0,
                "pending": 0,
                "done": 0,
            },
            "completed": [],
        }

    previous_date = str(previous["date"])
    target = date_type.fromisoformat(target_date)
    prior = date_type.fromisoformat(previous_date)
    days_gap = (target - prior).days

    if days_gap <= 0:
        raise InvalidDailyReportDataError(
            "Previous Daily date must be earlier than the report date."
        )

    tasks = previous["tasks"]
    completed = [
        _trim_previous_completed_task(task)
        for task in tasks
        if task.get("status") == "done"
    ]
    pending_count = sum(
        1 for task in tasks if task.get("status") == "pending"
    )

    return {
        "exists": True,
        "date": previous_date,
        "days_gap": days_gap,
        "counts": {
            "total": len(tasks),
            "pending": pending_count,
            "done": len(completed),
        },
        "completed": completed,
    }


def _build_long_snapshot(
    long_data: dict[str, Any],
    *,
    target_date: str,
) -> dict[str, Any]:
    active_collection = long_data["active"]
    tasks = (
        active_collection["tasks"]
        if active_collection["exists"]
        else []
    )

    target = date_type.fromisoformat(target_date)

    active: list[dict[str, Any]] = []
    due_today: list[dict[str, Any]] = []
    overdue: list[dict[str, Any]] = []

    for task in tasks:
        status = task.get("status")
        is_active = task.get("active") is True
        deadline = task.get("deadline")

        if status == "pending" and is_active:
            active.append(_trim_long_task(task))

        if status != "pending" or deadline is None:
            continue

        deadline_date = date_type.fromisoformat(str(deadline))

        if deadline_date == target:
            due_today.append(_trim_long_task(task))
        elif deadline_date < target:
            overdue.append(
                _trim_long_task(
                    task,
                    days_overdue=(target - deadline_date).days,
                )
            )

    return {
        "exists": bool(active_collection["exists"]),
        "active": active,
        "due_today": due_today,
        "overdue": overdue,
    }


def build_daily_report(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
    long_dir: str | Path | None = None,
    config_path: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Build one deterministic Daily Report snapshot.

    Missing Task collections are treated as empty read states by the Task read
    facade. A missing target Daily produces a report warning because the normal
    MuseAI daily workflow is expected to run Task Maintenance first.

    Existing invalid Task data is not suppressed and propagates as an error.
    """
    target_date, generated_at = _resolve_report_context(
        date,
        config_path=config_path,
    )

    today, today_warnings = read_daily_tasks(
        target_date,
        allow_missing=True,
        daily_dir=daily_dir,
    )
    previous, previous_warnings = read_previous_daily_tasks(
        before=target_date,
        allow_missing=True,
        daily_dir=daily_dir,
    )
    long_data, long_warnings = read_long_tasks(
        include_archived=False,
        allow_missing=True,
        long_dir=long_dir,
    )

    warnings = _merge_warnings(
        today_warnings,
        previous_warnings,
        long_warnings,
    )

    if not today["exists"]:
        warnings = _merge_warnings(
            warnings,
            [f"{TARGET_DAILY_NOT_INITIALIZED}: {target_date}"],
        )

    today_snapshot = _build_today_snapshot(today)
    previous_snapshot = _build_previous_snapshot(
        previous,
        target_date=target_date,
    )
    long_snapshot = _build_long_snapshot(
        long_data,
        target_date=target_date,
    )

    pending_carryover_count = sum(
        1
        for task in today_snapshot["pending"]
        if task.get("source") == "carryover"
    )

    attention = {
        "has_attention": bool(
            pending_carryover_count
            or long_snapshot["due_today"]
            or long_snapshot["overdue"]
        ),
        "carryover_count": pending_carryover_count,
        "due_today_long_count": len(long_snapshot["due_today"]),
        "overdue_long_count": len(long_snapshot["overdue"]),
    }

    return (
        {
            "date": target_date,
            "generated_at": generated_at,
            "today": today_snapshot,
            "previous": previous_snapshot,
            "long": long_snapshot,
            "attention": attention,
        },
        warnings,
    )
