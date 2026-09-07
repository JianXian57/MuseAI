#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Deterministic Daily initialization orchestration for MuseAI.

Recommended location:
    MuseAI/tools/init_ops/daily_init_service.py

Purpose
-------
Prepare the current or explicitly requested Daily Task state by reusing the
existing Daily-maintenance service:

    maintenance check
    -> apply only when actions are required

Boundary
--------
- This service does not reimplement carryover or Standing recurrence logic.
- This service does not parse or write Task JSON directly.
- All Task mutations remain owned by task_ops.daily_maintenance_service and
  the Task services it delegates to.
- No separate "already initialized today" state file is used.
- Repeated calls rely on Maintenance idempotence.

This module contains no CLI parsing, printing, Tool Result construction, or
lifecycle logging.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from task_ops.daily_maintenance_service import (
    apply_daily_maintenance,
    check_daily_maintenance,
)


def _merge_warnings(*groups: Iterable[str]) -> list[str]:
    merged: list[str] = []

    for group in groups:
        for warning in group:
            text = str(warning)
            if text not in merged:
                merged.append(text)

    return merged


def initialize_daily(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
    standing_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Initialize one Daily Task date through the existing Maintenance service.

    The check phase is read-only. Maintenance apply is called only when the
    calculated plan reports actions_required=true.
    """
    plan, check_warnings = check_daily_maintenance(
        date,
        daily_dir=daily_dir,
        standing_dir=standing_dir,
    )

    target_date = str(plan["date"])
    actions_required = bool(plan.get("actions_required"))

    if not actions_required:
        return (
            {
                "date": target_date,
                "changed": False,
                "maintenance": {
                    "applied": False,
                    "actions_required_before": False,
                    "source_date": plan.get("source_date"),
                    "daily_created": False,
                    "carryover_created_count": 0,
                    "standing_daily_created_count": 0,
                    "standing_generation_mark_changed_count": 0,
                },
            },
            list(check_warnings),
        )

    apply_result, apply_warnings = apply_daily_maintenance(
        target_date,
        daily_dir=daily_dir,
        standing_dir=standing_dir,
    )

    carryover_results = list(apply_result.get("carryover") or [])
    standing_results = list(apply_result.get("standing") or [])
    daily_result = dict(apply_result.get("daily") or {})

    return (
        {
            "date": str(apply_result.get("date") or target_date),
            "changed": bool(apply_result.get("changed")),
            "maintenance": {
                "applied": True,
                "actions_required_before": True,
                "source_date": plan.get("source_date"),
                "daily_created": bool(daily_result.get("created")),
                "carryover_created_count": sum(
                    1
                    for item in carryover_results
                    if bool(item.get("created"))
                ),
                "standing_daily_created_count": sum(
                    1
                    for item in standing_results
                    if bool(item.get("daily_created"))
                ),
                "standing_generation_mark_changed_count": sum(
                    1
                    for item in standing_results
                    if bool(item.get("generation_mark_changed"))
                ),
            },
        },
        _merge_warnings(
            check_warnings,
            apply_warnings,
        ),
    )
