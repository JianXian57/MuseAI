#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI public Task Tool.

Recommended location:
    MuseAI/tools/task_ops/task_tool.py

Responsibilities
----------------
- Expose public Daily, Long, and Standing Task operations.
- Convert service results/errors into the unified MuseAI Tool protocol.

This module does not:
- parse CLI arguments;
- print output;
- write lifecycle logs;
- directly manipulate Task JSON.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from common.result import success
from task_ops.daily_service import (
    add_daily as service_add_daily,
    ensure_daily as service_ensure_daily,
    read_daily as service_read_daily,
    remove_daily as service_remove_daily,
    set_daily_status as service_set_daily_status,
    update_daily as service_update_daily,
)
from task_ops.long_service import (
    add_long as service_add_long,
    archive_long as service_archive_long,
    ensure_long as service_ensure_long,
    read_long as service_read_long,
    record_long as service_record_long,
    set_long_active as service_set_long_active,
    set_long_deadline as service_set_long_deadline,
    set_long_stage as service_set_long_stage,
    set_long_status as service_set_long_status,
    unarchive_long as service_unarchive_long,
    update_long as service_update_long,
)
from task_ops.standing_service import (
    add_standing as service_add_standing,
    check_standing_due as service_check_standing_due,
    ensure_standing as service_ensure_standing,
    mark_standing_generated as service_mark_standing_generated,
    read_standing as service_read_standing,
    remove_standing as service_remove_standing,
    set_standing_enabled as service_set_standing_enabled,
    set_standing_schedule as service_set_standing_schedule,
    update_standing as service_update_standing,
)
from task_ops.task_errors import map_task_exception


def _run(
    operation: str,
    action: Callable[..., tuple[dict[str, Any], list[str]]],
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        data, warnings = action(**kwargs)
    except Exception as exc:
        return map_task_exception(operation, exc)

    return success(
        operation,
        data,
        warnings,
    )


def daily_ensure(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.daily.ensure",
        service_ensure_daily,
        date=date,
        daily_dir=daily_dir,
    )


def daily_read(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.daily.read",
        service_read_daily,
        date=date,
        daily_dir=daily_dir,
    )


def daily_add(
    *,
    title: str,
    description: str = "",
    category: str = "未分类",
    source: str = "manual",
    long_task_id: str | None = None,
    standing_task_id: str | None = None,
    date: str | None = None,
    meta: dict[str, Any] | None = None,
    daily_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.daily.add",
        service_add_daily,
        title=title,
        description=description,
        category=category,
        source=source,
        long_task_id=long_task_id,
        standing_task_id=standing_task_id,
        date=date,
        meta=meta,
        daily_dir=daily_dir,
    )


def daily_update(
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
) -> dict[str, Any]:
    return _run(
        "task.daily.update",
        service_update_daily,
        task_id=task_id,
        title=title,
        description=description,
        category=category,
        long_task_id=long_task_id,
        clear_long_task_id=clear_long_task_id,
        standing_task_id=standing_task_id,
        clear_standing_task_id=clear_standing_task_id,
        date=date,
        daily_dir=daily_dir,
    )


def daily_status(
    *,
    task_id: str,
    status: str,
    date: str | None = None,
    daily_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.daily.status",
        service_set_daily_status,
        task_id=task_id,
        status=status,
        date=date,
        daily_dir=daily_dir,
    )


def daily_remove(
    *,
    task_id: str,
    date: str | None = None,
    daily_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.daily.remove",
        service_remove_daily,
        task_id=task_id,
        date=date,
        daily_dir=daily_dir,
    )


def long_ensure(
    *,
    long_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.long.ensure",
        service_ensure_long,
        long_dir=long_dir,
    )


def long_read(
    collection: str = "active",
    *,
    long_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.long.read",
        service_read_long,
        collection=collection,
        long_dir=long_dir,
    )


def long_add(
    *,
    title: str,
    description: str = "",
    category: str = "未分类",
    active: bool = True,
    stage: str | None = None,
    deadline: str | None = None,
    meta: dict[str, Any] | None = None,
    long_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.long.add",
        service_add_long,
        title=title,
        description=description,
        category=category,
        active=active,
        stage=stage,
        deadline=deadline,
        meta=meta,
        long_dir=long_dir,
    )


def long_update(
    *,
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    category: str | None = None,
    long_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.long.update",
        service_update_long,
        task_id=task_id,
        title=title,
        description=description,
        category=category,
        long_dir=long_dir,
    )


def long_status(
    *,
    task_id: str,
    status: str,
    long_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.long.status",
        service_set_long_status,
        task_id=task_id,
        status=status,
        long_dir=long_dir,
    )


def long_activate(
    *,
    task_id: str,
    long_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.long.activate",
        service_set_long_active,
        task_id=task_id,
        active=True,
        long_dir=long_dir,
    )


def long_deactivate(
    *,
    task_id: str,
    long_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.long.deactivate",
        service_set_long_active,
        task_id=task_id,
        active=False,
        long_dir=long_dir,
    )


def long_stage(
    *,
    task_id: str,
    stage: str | None,
    long_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.long.stage",
        service_set_long_stage,
        task_id=task_id,
        stage=stage,
        long_dir=long_dir,
    )


def long_deadline(
    *,
    task_id: str,
    deadline: str | None,
    long_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.long.deadline",
        service_set_long_deadline,
        task_id=task_id,
        deadline=deadline,
        long_dir=long_dir,
    )


def long_record(
    *,
    task_id: str,
    text: str,
    entry_type: str = "progress",
    meta: dict[str, Any] | None = None,
    long_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.long.record",
        service_record_long,
        task_id=task_id,
        text=text,
        entry_type=entry_type,
        meta=meta,
        long_dir=long_dir,
    )


def long_archive(
    *,
    task_id: str,
    long_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.long.archive",
        service_archive_long,
        task_id=task_id,
        long_dir=long_dir,
    )


def long_unarchive(
    *,
    task_id: str,
    long_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.long.unarchive",
        service_unarchive_long,
        task_id=task_id,
        long_dir=long_dir,
    )


def standing_ensure(
    *,
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.standing.ensure",
        service_ensure_standing,
        standing_dir=standing_dir,
    )


def standing_read(
    *,
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.standing.read",
        service_read_standing,
        standing_dir=standing_dir,
    )


def standing_add(
    *,
    title: str,
    schedule: dict[str, Any],
    description: str = "",
    category: str = "未分类",
    enabled: bool = True,
    long_task_id: str | None = None,
    meta: dict[str, Any] | None = None,
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.standing.add",
        service_add_standing,
        title=title,
        schedule=schedule,
        description=description,
        category=category,
        enabled=enabled,
        long_task_id=long_task_id,
        meta=meta,
        standing_dir=standing_dir,
    )


def standing_update(
    *,
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    category: str | None = None,
    long_task_id: str | None = None,
    clear_long_task_id: bool = False,
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.standing.update",
        service_update_standing,
        task_id=task_id,
        title=title,
        description=description,
        category=category,
        long_task_id=long_task_id,
        clear_long_task_id=clear_long_task_id,
        standing_dir=standing_dir,
    )


def standing_enable(
    *,
    task_id: str,
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.standing.enable",
        service_set_standing_enabled,
        task_id=task_id,
        enabled=True,
        standing_dir=standing_dir,
    )


def standing_disable(
    *,
    task_id: str,
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.standing.disable",
        service_set_standing_enabled,
        task_id=task_id,
        enabled=False,
        standing_dir=standing_dir,
    )


def standing_schedule(
    *,
    task_id: str,
    schedule: dict[str, Any],
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.standing.schedule",
        service_set_standing_schedule,
        task_id=task_id,
        schedule=schedule,
        standing_dir=standing_dir,
    )


def standing_due(
    date: str | None = None,
    *,
    include_not_due: bool = False,
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.standing.due",
        service_check_standing_due,
        date=date,
        include_not_due=include_not_due,
        standing_dir=standing_dir,
    )


def standing_mark_generated(
    *,
    task_id: str,
    date: str | None = None,
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.standing.mark-generated",
        service_mark_standing_generated,
        task_id=task_id,
        date=date,
        standing_dir=standing_dir,
    )


def standing_remove(
    *,
    task_id: str,
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "task.standing.remove",
        service_remove_standing,
        task_id=task_id,
        standing_dir=standing_dir,
    )

