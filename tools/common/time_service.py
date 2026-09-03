#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI internal time service.

Recommended location:
    MuseAI/tools/common/time_service.py

Purpose
-------
This module provides the shared low-level time logic used by MuseAI Tools.

It is an internal service, not a public Tool:
- it does not parse CLI arguments;
- it does not print output;
- it does not return the MuseAI Tool JSON protocol;
- it does not write logs.

Public Tools such as `time_tool.py` and `log_tool.py` should call this module.

Time policy
-----------
1. `get_current_time()` is strict:
   it requires a valid IANA timezone in `config/user.yaml`.
2. `get_log_time()` is resilient:
   it prefers the configured timezone, but falls back to the operating
   system's local timezone so that logging can still work when the user
   configuration is broken.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# File location:
#   <project-root>/tools/common/time_service.py
#
# parents[0] -> tools/common
# parents[1] -> tools
# parents[2] -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_USER_CONFIG = PROJECT_ROOT / "config" / "user.yaml"


class TimeServiceError(Exception):
    """Base exception for MuseAI time service errors."""


class UserConfigNotFoundError(TimeServiceError):
    """Raised when the user configuration file does not exist."""


class UserConfigReadError(TimeServiceError):
    """Raised when the user configuration file cannot be read."""


class InvalidUserConfigError(TimeServiceError):
    """Raised when the user configuration file contains invalid data."""


class TimezoneNotConfiguredError(TimeServiceError):
    """Raised when the timezone field is missing."""


class InvalidTimezoneError(TimeServiceError):
    """Raised when the configured IANA timezone cannot be resolved."""


def _resolve_config_path(config_path: str | Path | None = None) -> Path:
    """Return the absolute path of the user configuration file."""
    if config_path is None:
        return DEFAULT_USER_CONFIG

    return Path(config_path).expanduser().resolve()


def _strip_inline_comment(value: str) -> str:
    """
    Remove a simple YAML inline comment while preserving `#` inside quotes.

    Examples
    --------
    Asia/Shanghai # local timezone
    "America/Chicago" # work timezone
    """
    quote: str | None = None

    for index, char in enumerate(value):
        if char in ('"', "'"):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
        elif char == "#" and quote is None:
            return value[:index].rstrip()

    return value.strip()


def read_timezone(config_path: str | Path | None = None) -> str:
    """
    Read the top-level `timezone` scalar from `config/user.yaml`.

    Supported examples
    ------------------
    timezone: Asia/Shanghai
    timezone: "Asia/Shanghai"
    timezone: 'America/Chicago'

    This intentionally avoids a YAML dependency because MuseAI currently
    needs only one simple scalar value from this file.
    """
    path = _resolve_config_path(config_path)

    if not path.exists():
        raise UserConfigNotFoundError(
            f"User configuration file not found: {path}"
        )

    if not path.is_file():
        raise InvalidUserConfigError(
            f"User configuration path is not a file: {path}"
        )

    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise UserConfigReadError(
            f"Could not read user configuration file: {path}"
        ) from exc

    for raw_line in text.splitlines():
        stripped = raw_line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        if raw_line[:1].isspace():
            continue

        key, separator, raw_value = stripped.partition(":")
        if not separator or key.strip() != "timezone":
            continue

        value = _strip_inline_comment(raw_value.strip())

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ('"', "'")
        ):
            value = value[1:-1].strip()

        if not value:
            raise InvalidUserConfigError(
                "The `timezone` value is empty."
            )

        return value

    raise TimezoneNotConfiguredError(
        "The `timezone` field is missing from the user configuration."
    )


def _build_time_context(
    now: datetime,
    *,
    timezone_name: str,
    source: str,
    warning: str | None = None,
) -> dict[str, Any]:
    """Build one normalized internal time context."""
    utc_offset = now.strftime("%z")

    if len(utc_offset) == 5:
        utc_offset = f"{utc_offset[:3]}:{utc_offset[3:]}"

    return {
        "timezone": timezone_name,
        "datetime": now,
        "current_datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "current_date": now.strftime("%Y-%m-%d"),
        "current_time": now.strftime("%H:%M:%S"),
        "current_month": now.strftime("%Y%m"),
        "utc_offset": utc_offset,
        "source": source,
        "warning": warning,
    }


def get_current_time(
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Return MuseAI's authoritative current time.

    This function is strict. A valid IANA timezone must exist in the user
    configuration. Any configuration problem raises a TimeServiceError.
    """
    timezone_name = read_timezone(config_path)

    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise InvalidTimezoneError(
            f"Configured IANA timezone could not be resolved: {timezone_name}"
        ) from exc

    now = datetime.now(timezone)

    return _build_time_context(
        now,
        timezone_name=timezone_name,
        source="configured_timezone",
    )


def get_log_time(
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Return a timestamp suitable for the logging subsystem.

    Preferred behavior:
        use MuseAI's configured IANA timezone.

    Fallback behavior:
        if the user time configuration is unavailable or invalid, use the
        operating system's local timezone so that a failure can still be
        written to the log.
    """
    try:
        return get_current_time(config_path)

    except TimeServiceError as exc:
        now = datetime.now().astimezone()

        tzinfo = now.tzinfo
        timezone_name = (
            getattr(tzinfo, "key", None)
            or now.tzname()
            or "system-local"
        )

        return _build_time_context(
            now,
            timezone_name=str(timezone_name),
            source="system_fallback",
            warning=f"{type(exc).__name__}: {exc}",
        )
