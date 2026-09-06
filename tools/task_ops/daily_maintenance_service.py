#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Deterministic Daily Task cross-day maintenance for MuseAI.

Recommended location:
    MuseAI/tools/task_ops/daily_maintenance_service.py

Purpose
-------
Prepare the target Daily Task state for one calendar day by:
1. carrying pending Tasks from the nearest previous Daily collection;
2. generating due Standing Task occurrences for the target date.

Boundary
--------
- check_daily_maintenance() is strictly read-only.
- apply_daily_maintenance() recalculates the plan and then applies it.
- This service never parses Task JSON directly.
- Daily writes are delegated to daily_service.
- Standing generation state writes are delegated to standing_service.
- Long Task data is never modified; Daily long_task_id relations are copied.
- No separate maintenance-state file is used.

Idempotence / recovery
----------------------
Carryover idempotence is keyed by Daily.carryover_from_task_id plus retired
carryover provenance tombstones.
Standing consistency is keyed by Daily.standing_task_id plus
Standing.last_generated_date; either side can be repaired when only one write
survived.

Re-running apply after a partial failure is therefore safe under MuseAI V1's
single-writer assumption.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from task_ops.daily_service import add_daily, ensure_daily
from task_ops.standing_service import (
    StandingGenerationDateRegressionError,
    build_daily_payload,
    mark_standing_generated,
    schedule_matches_date,
)
from task_ops.task_read_service import (
    read_daily_tasks,
    read_previous_daily_tasks,
    read_standing_tasks,
    resolve_task_read_date,
)


def _merge_warnings(*groups: Iterable[str]) -> list[str]:
    merged: list[str] = []

    for group in groups:
        for warning in group:
            text = str(warning)
            if text not in merged:
                merged.append(text)

    return merged


def _target_daily_maps(
    daily: dict[str, Any],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    set[str],
]:
    carryover_map: dict[str, dict[str, Any]] = {}
    standing_map: dict[str, dict[str, Any]] = {}

    for task in daily.get("tasks", []):
        carryover_from = task.get("carryover_from_task_id")
        if isinstance(carryover_from, str) and carryover_from:
            carryover_map[carryover_from] = task

        standing_task_id = task.get("standing_task_id")
        if isinstance(standing_task_id, str) and standing_task_id:
            standing_map[standing_task_id] = task

    retired_carryover_sources = {
        str(value)
        for value in daily.get("retired_carryover_from_task_ids", [])
        if isinstance(value, str) and value
    }

    return carryover_map, standing_map, retired_carryover_sources


def _build_daily_maintenance_plan(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Build public and internal maintenance plans without writing data."""
    target_date = resolve_task_read_date(date)

    target_daily, target_warnings = read_daily_tasks(
        target_date,
        allow_missing=True,
        daily_dir=daily_dir,
    )
    previous_daily, previous_warnings = read_previous_daily_tasks(
        target_date,
        allow_missing=True,
        daily_dir=daily_dir,
    )
    standing, standing_warnings = read_standing_tasks(
        allow_missing=True,
        standing_dir=standing_dir,
    )

    (
        carryover_map,
        standing_map,
        retired_carryover_sources,
    ) = _target_daily_maps(target_daily)

    carryover_items: list[dict[str, Any]] = []
    carryover_actions: list[dict[str, Any]] = []

    for source_task in previous_daily.get("tasks", []):
        if source_task.get("status") != "pending":
            continue

        source_task_id = str(source_task["id"])
        existing = carryover_map.get(source_task_id)
        retired = source_task_id in retired_carryover_sources
        needs_create = existing is None and not retired

        item = {
            "source_task_id": source_task_id,
            "source_date": previous_daily.get("date"),
            "title": source_task.get("title"),
            "already_carried": existing is not None,
            "retired": retired,
            "target_task_id": None if existing is None else existing.get("id"),
            "needs_create": needs_create,
        }
        carryover_items.append(item)

        if needs_create:
            carryover_actions.append(
                {
                    "source_task": source_task,
                }
            )

    standing_items: list[dict[str, Any]] = []
    standing_actions: list[dict[str, Any]] = []
    scheduled_count = 0
    already_generated_count = 0

    for standing_task in standing.get("tasks", []):
        if not standing_task.get("enabled", True):
            continue

        if not schedule_matches_date(
            standing_task["schedule"],
            target_date,
        ):
            continue

        scheduled_count += 1
        standing_task_id = str(standing_task["id"])
        existing = standing_map.get(standing_task_id)
        last_generated_date = standing_task.get("last_generated_date")
        generated = last_generated_date == target_date

        if (
            last_generated_date is not None
            and last_generated_date > target_date
        ):
            raise StandingGenerationDateRegressionError(
                f"Standing Task {standing_task_id} generation date cannot move "
                f"backward from {last_generated_date} to {target_date}."
            )

        if generated and existing is not None:
            already_generated_count += 1
            standing_items.append(
                {
                    "standing_task_id": standing_task_id,
                    "title": standing_task.get("title"),
                    "state": "already_generated",
                    "daily_task_id": existing.get("id"),
                    "needs_daily": False,
                    "needs_mark_generated": False,
                }
            )
            continue

        if generated and existing is None:
            needs_daily = True
            needs_mark_generated = False
            state = "recovery_daily_required"
        else:
            needs_daily = existing is None
            needs_mark_generated = True
            state = "due" if needs_daily else "recovery_mark_required"

        standing_items.append(
            {
                "standing_task_id": standing_task_id,
                "title": standing_task.get("title"),
                "state": state,
                "daily_task_id": None if existing is None else existing.get("id"),
                "needs_daily": needs_daily,
                "needs_mark_generated": needs_mark_generated,
            }
        )
        standing_actions.append(
            {
                "standing_task": standing_task,
                "needs_daily": needs_daily,
                "needs_mark_generated": needs_mark_generated,
                "existing_daily_task_id": (
                    None if existing is None else existing.get("id")
                ),
            }
        )

    ensure_daily_required = not bool(target_daily.get("exists"))
    actions_required = bool(
        ensure_daily_required
        or carryover_actions
        or standing_actions
    )

    public_plan = {
        "date": target_date,
        "source_date": previous_daily.get("date"),
        "target_daily": {
            "exists": bool(target_daily.get("exists")),
            "path": target_daily.get("path"),
        },
        "ensure_daily_required": ensure_daily_required,
        "carryover": {
            "pending_count": len(carryover_items),
            "create_count": len(carryover_actions),
            "already_carried_count": sum(
                1 for item in carryover_items if item["already_carried"]
            ),
            "retired_count": sum(
                1 for item in carryover_items if item["retired"]
            ),
            "items": carryover_items,
        },
        "standing": {
            "scheduled_count": scheduled_count,
            "action_count": len(standing_actions),
            "already_generated_count": already_generated_count,
            "items": standing_items,
        },
        "actions_required": actions_required,
    }

    internal_plan = {
        "target_date": target_date,
        "carryover_actions": carryover_actions,
        "standing_actions": standing_actions,
    }

    return (
        public_plan,
        internal_plan,
        _merge_warnings(
            target_warnings,
            previous_warnings,
            standing_warnings,
        ),
    )


def check_daily_maintenance(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Read-only calculation of the cross-day Task maintenance plan."""
    public_plan, _, warnings = _build_daily_maintenance_plan(
        date,
        daily_dir=daily_dir,
        standing_dir=standing_dir,
    )
    return public_plan, warnings


def apply_daily_maintenance(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Recalculate and apply one day's deterministic Task maintenance.

    The target Daily file is always ensured. Each carryover and Standing action
    is individually idempotent, allowing the full operation to be safely rerun
    after interruption.
    """
    public_plan, internal_plan, plan_warnings = _build_daily_maintenance_plan(
        date,
        daily_dir=daily_dir,
        standing_dir=standing_dir,
    )
    target_date = str(internal_plan["target_date"])

    ensure_result, ensure_warnings = ensure_daily(
        target_date,
        daily_dir=daily_dir,
    )

    changed = bool(ensure_result.get("created"))
    carryover_results: list[dict[str, Any]] = []
    standing_results: list[dict[str, Any]] = []
    write_warnings: list[str] = []

    for action in internal_plan["carryover_actions"]:
        source_task = action["source_task"]
        add_result, current_warnings = add_daily(
            title=source_task["title"],
            description=source_task.get("description", ""),
            category=source_task.get("category", "未分类"),
            source="carryover",
            long_task_id=source_task.get("long_task_id"),
            standing_task_id=None,
            carryover_from_task_id=source_task["id"],
            date=target_date,
            meta=dict(source_task.get("meta", {})),
            daily_dir=daily_dir,
        )
        write_warnings = _merge_warnings(write_warnings, current_warnings)
        created = bool(add_result.get("created"))
        changed = changed or created
        carryover_results.append(
            {
                "source_task_id": source_task["id"],
                "target_task_id": add_result["task"]["id"],
                "created": created,
            }
        )

    for action in internal_plan["standing_actions"]:
        standing_task = action["standing_task"]
        needs_daily = bool(action["needs_daily"])
        needs_mark_generated = bool(action["needs_mark_generated"])

        daily_created = False
        generation_mark_changed = False
        daily_task_id = action.get("existing_daily_task_id")

        if needs_daily:
            payload = build_daily_payload(standing_task)
            add_result, add_warnings = add_daily(
                **payload,
                carryover_from_task_id=None,
                date=target_date,
                daily_dir=daily_dir,
            )
            write_warnings = _merge_warnings(write_warnings, add_warnings)
            daily_created = bool(add_result.get("created"))
            daily_task_id = add_result["task"]["id"]

        if needs_mark_generated:
            mark_result, mark_warnings = mark_standing_generated(
                task_id=standing_task["id"],
                date=target_date,
                standing_dir=standing_dir,
            )
            write_warnings = _merge_warnings(write_warnings, mark_warnings)
            generation_mark_changed = bool(mark_result.get("changed"))

        changed = changed or daily_created or generation_mark_changed

        standing_results.append(
            {
                "standing_task_id": standing_task["id"],
                "daily_task_id": daily_task_id,
                "daily_created": daily_created,
                "generation_mark_changed": generation_mark_changed,
            }
        )

    return (
        {
            "date": target_date,
            "changed": changed,
            "plan": public_plan,
            "daily": {
                "created": bool(ensure_result.get("created")),
                "path": ensure_result.get("path"),
            },
            "carryover": carryover_results,
            "standing": standing_results,
        },
        _merge_warnings(
            plan_warnings,
            ensure_warnings,
            write_warnings,
        ),
    )
