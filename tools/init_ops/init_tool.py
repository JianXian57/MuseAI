#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI public Initialization Tool.

Recommended location:
    MuseAI/tools/init_ops/init_tool.py

Responsibilities
----------------
- Expose deterministic initialization operations through the MuseAI Tool
  protocol.
- Delegate Daily initialization to daily_init_service.
- Preserve the existing stable Task/Time error mapping for delegated
  Maintenance failures.

This module does not:
- parse CLI arguments;
- print output;
- write lifecycle logs;
- parse or directly modify Task JSON;
- reimplement Daily-maintenance business logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common.result import success
from init_ops.daily_init_service import (
    initialize_daily as service_initialize_daily,
)
from task_ops.task_errors import map_task_exception


def daily_init(
    date: str | None = None,
    *,
    daily_dir: str | Path | None = None,
    standing_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Ensure one Daily Task date is maintenance-ready."""
    operation = "init.daily"

    try:
        data, warnings = service_initialize_daily(
            date,
            daily_dir=daily_dir,
            standing_dir=standing_dir,
        )
    except Exception as exc:
        return map_task_exception(operation, exc)

    return success(
        operation,
        data,
        warnings,
    )
