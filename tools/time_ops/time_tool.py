#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI public time Tool.

Recommended location:
    MuseAI/tools/time_ops/time_tool.py

Responsibilities
----------------
- Expose MuseAI's public `time.current` operation.
- Call the shared internal time service.
- Convert service results/errors into the unified MuseAI Tool protocol.

This module intentionally contains no timezone parsing or datetime logic.
Those responsibilities belong to:
    tools/common/time_service.py

This module does not:
- parse CLI arguments;
- print output;
- write logs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common.result import failure, success
from common.time_service import (
    InvalidTimezoneError,
    InvalidUserConfigError,
    TimeServiceError,
    TimezoneNotConfiguredError,
    UserConfigNotFoundError,
    UserConfigReadError,
    get_current_time,
)


def current_time(
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Return MuseAI's current configured local time.

    Parameters
    ----------
    config_path:
        Optional path to a user configuration file.
        When omitted, the shared time service uses:
        `<project-root>/config/user.yaml`

    Returns
    -------
    dict
        Unified MuseAI Tool result for operation `time.current`.
    """
    operation = "time.current"

    try:
        context = get_current_time(config_path)

    except UserConfigNotFoundError as exc:
        return failure(
            operation,
            "USER_CONFIG_NOT_FOUND",
            "MuseAI user configuration file was not found.",
            {
                "reason": str(exc),
                "required_field": "timezone",
            },
        )

    except TimezoneNotConfiguredError as exc:
        return failure(
            operation,
            "TIMEZONE_NOT_CONFIGURED",
            "The `timezone` field is missing from the MuseAI user configuration.",
            {
                "reason": str(exc),
                "expected_example": "timezone: Asia/Shanghai",
            },
        )

    except InvalidTimezoneError as exc:
        return failure(
            operation,
            "INVALID_TIMEZONE",
            "The configured IANA timezone could not be resolved.",
            {
                "reason": str(exc),
                "hint": (
                    "Verify the IANA timezone name. On Windows, install the "
                    "`tzdata` Python package if the timezone database is unavailable."
                ),
            },
        )

    except UserConfigReadError as exc:
        return failure(
            operation,
            "USER_CONFIG_READ_FAILED",
            "MuseAI could not read the user configuration file.",
            {
                "reason": str(exc),
            },
        )

    except InvalidUserConfigError as exc:
        return failure(
            operation,
            "INVALID_USER_CONFIG",
            "MuseAI user configuration is invalid.",
            {
                "reason": str(exc),
            },
        )

    except TimeServiceError as exc:
        return failure(
            operation,
            "TIME_SERVICE_ERROR",
            "MuseAI time service failed.",
            {
                "reason": str(exc),
            },
        )

    data = {
        "timezone": context["timezone"],
        "current_datetime": context["current_datetime"],
        "current_date": context["current_date"],
        "current_time": context["current_time"],
        "current_month": context["current_month"],
        "utc_offset": context["utc_offset"],
    }

    warnings: list[str] = []

    if context.get("warning"):
        warnings.append(str(context["warning"]))

    return success(
        operation=operation,
        data=data,
        warnings=warnings,
    )
