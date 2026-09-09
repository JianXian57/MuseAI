#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI public Query Tool.

Recommended location:
    MuseAI/tools/query_ops/query_tool.py

Query is strictly read-only. It exposes compact deterministic information
access to Main while Domain Tools continue to own mutations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from common.result import failure, success
from character_ops.character_service import (
    CharacterConfigError,
    CharacterManifestError,
    CharacterProfileDataError,
    CharacterProfileNotFoundError,
    CharacterServiceError,
    resolve_current_character as service_resolve_current_character,
)
from query_ops.query_errors import map_query_exception
from query_ops.task_query_service import (
    query_daily_tasks as service_query_daily_tasks,
    query_long_tasks as service_query_long_tasks,
    query_related_tasks as service_query_related_tasks,
    query_standing_tasks as service_query_standing_tasks,
    query_task_overview as service_query_task_overview,
)


def _run(
    operation: str,
    action: Callable[..., tuple[dict[str, Any], list[str]]],
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        data, warnings = action(**kwargs)
    except Exception as exc:
        return map_query_exception(operation, exc)

    return success(
        operation,
        data,
        warnings,
    )


def task_daily(
    date: str | None = None,
    *,
    status: str | None = None,
    source: str | None = None,
    category: str | None = None,
    long_task_id: str | None = None,
    standing_task_id: str | None = None,
    task_id: str | None = None,
    text: str | None = None,
    limit: int = 50,
    daily_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "query.task.daily",
        service_query_daily_tasks,
        date=date,
        status=status,
        source=source,
        category=category,
        long_task_id=long_task_id,
        standing_task_id=standing_task_id,
        task_id=task_id,
        text=text,
        limit=limit,
        daily_dir=daily_dir,
    )


def task_long(
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
    limit: int = 50,
    long_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "query.task.long",
        service_query_long_tasks,
        date=date,
        collection=collection,
        status=status,
        active=active,
        category=category,
        stage=stage,
        deadline_state=deadline_state,
        task_id=task_id,
        text=text,
        limit=limit,
        long_dir=long_dir,
    )


def task_standing(
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
    limit: int = 50,
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "query.task.standing",
        service_query_standing_tasks,
        date=date,
        enabled=enabled,
        category=category,
        schedule_type=schedule_type,
        long_task_id=long_task_id,
        scheduled=scheduled,
        due=due,
        task_id=task_id,
        text=text,
        limit=limit,
        standing_dir=standing_dir,
    )


def task_related(
    *,
    task_id: str,
    date: str | None = None,
    limit: int = 50,
    daily_dir: str | Path | None = None,
    long_dir: str | Path | None = None,
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "query.task.related",
        service_query_related_tasks,
        task_id=task_id,
        date=date,
        limit=limit,
        daily_dir=daily_dir,
        long_dir=long_dir,
        standing_dir=standing_dir,
    )


def task_overview(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
    long_dir: str | Path | None = None,
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "query.task.overview",
        service_query_task_overview,
        date=date,
        daily_dir=daily_dir,
        long_dir=long_dir,
        standing_dir=standing_dir,
    )


def _map_character_exception(
    operation: str,
    exc: Exception,
) -> dict[str, Any]:
    """Map Character Service failures to stable Query Tool errors."""
    if isinstance(exc, CharacterConfigError):
        return failure(
            operation,
            "QUERY_CHARACTER_CONFIG_ERROR",
            "MuseAI Character user configuration is invalid.",
            {
                "reason": str(exc),
                "exception": type(exc).__name__,
            },
        )

    if isinstance(exc, CharacterProfileNotFoundError):
        return failure(
            operation,
            "QUERY_CHARACTER_PROFILE_NOT_FOUND",
            "The configured MuseAI Character Profile could not be found.",
            {
                "reason": str(exc),
                "exception": type(exc).__name__,
            },
        )

    if isinstance(exc, CharacterProfileDataError):
        return failure(
            operation,
            "QUERY_CHARACTER_PROFILE_DATA_ERROR",
            "The configured MuseAI Character Profile defaults are invalid.",
            {
                "reason": str(exc),
                "exception": type(exc).__name__,
            },
        )

    if isinstance(exc, CharacterManifestError):
        return failure(
            operation,
            "QUERY_CHARACTER_MANIFEST_ERROR",
            "The configured MuseAI Character Reaction manifest is invalid.",
            {
                "reason": str(exc),
                "exception": type(exc).__name__,
            },
        )

    if isinstance(exc, CharacterServiceError):
        return failure(
            operation,
            "QUERY_CHARACTER_DATA_ERROR",
            "MuseAI Character data could not be resolved.",
            {
                "reason": str(exc),
                "exception": type(exc).__name__,
            },
        )

    return failure(
        operation,
        "QUERY_UNEXPECTED_ERROR",
        "The Query Tool failed unexpectedly.",
        {
            "reason": str(exc),
            "exception": type(exc).__name__,
        },
    )


def character_current(
    *,
    user_config_path: str | Path | None = None,
    character_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return the effective current MuseAI Character runtime snapshot."""
    operation = "query.character.current"

    try:
        data, warnings = service_resolve_current_character(
            user_config_path=user_config_path,
            character_root=character_root,
        )
    except Exception as exc:
        return _map_character_exception(operation, exc)

    return success(
        operation,
        data,
        warnings,
    )

