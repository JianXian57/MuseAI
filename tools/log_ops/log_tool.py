#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI public log Tool.

Recommended location:
    MuseAI/tools/log_ops/log_tool.py

Log format
----------
YYYY-MM-DD｜HH:mm:ss｜PURPOSE｜OPERATION｜DESCRIPTION

Example:
2026-09-03｜22:12:35｜每日汇报｜time.current｜SUCCESS Get current time.

Log files are split by calendar month:
    data/logs/YYYYMM.log

Responsibilities
----------------
- Write structured MuseAI log entries.
- Read and filter MuseAI log entries.
- Use the shared time service for timestamps.
- Return the unified MuseAI Tool protocol.

This module does not:
- parse CLI arguments;
- print output;
- decide when an operation should be logged.

`muse.py` is responsible for deciding when to call this Tool.
Other Tools should not write logs directly.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from common.result import failure, success
from common.time_service import get_log_time


# File location:
#   <project-root>/tools/log_ops/log_tool.py
#
# parents[0] -> tools/log_ops
# parents[1] -> tools
# parents[2] -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_DIR = PROJECT_ROOT / "data" / "logs"

DELIMITER = "｜"
MONTH_PATTERN = re.compile(r"^\d{6}$")
KNOWN_STATUSES = {"START", "SUCCESS", "FAILED", "INFO", "WARNING"}


def _normalize_required_field(name: str, value: str) -> str:
    """Validate and normalize one required text field."""
    if not isinstance(value, str):
        raise TypeError(f"`{name}` must be a string.")

    value = value.strip()

    if not value:
        raise ValueError(f"`{name}` must not be empty.")

    return value


def _escape_field(value: str) -> str:
    """
    Keep one logical field on one physical log line.

    Escape rules:
    - backslash -> \\\\
    - newline   -> \\n
    - carriage  -> \\r
    - delimiter -> \\uFF5C

    The real full-width delimiter character is therefore reserved for
    separating fields.
    """
    return (
        value
        .replace("\\", "\\\\")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace(DELIMITER, "\\uFF5C")
    )


def _unescape_field(value: str) -> str:
    """Reverse the escaping performed by `_escape_field`."""
    result: list[str] = []
    index = 0

    while index < len(value):
        if value.startswith("\\uFF5C", index):
            result.append(DELIMITER)
            index += 6
        elif value.startswith("\\n", index):
            result.append("\n")
            index += 2
        elif value.startswith("\\r", index):
            result.append("\r")
            index += 2
        elif value.startswith("\\\\", index):
            result.append("\\")
            index += 2
        else:
            result.append(value[index])
            index += 1

    return "".join(result)


def _extract_status(description: str) -> str | None:
    """
    Return a known status when DESCRIPTION starts with one.

    Examples:
        "SUCCESS Get current time." -> "SUCCESS"
        "FAILED INVALID_TIMEZONE."  -> "FAILED"
    """
    first_token = description.lstrip().split(maxsplit=1)[0].rstrip(".:")

    if first_token in KNOWN_STATUSES:
        return first_token

    return None


def _resolve_log_path(
    month: str,
    log_dir: str | Path | None = None,
) -> Path:
    """Resolve `data/logs/YYYYMM.log`."""
    if not MONTH_PATTERN.fullmatch(month):
        raise ValueError("`month` must use YYYYMM format.")

    directory = (
        Path(log_dir).expanduser().resolve()
        if log_dir is not None
        else DEFAULT_LOG_DIR
    )

    return directory / f"{month}.log"


def write_log(
    purpose: str,
    operation: str,
    description: str,
    *,
    log_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Append one MuseAI log entry.

    Parameters
    ----------
    purpose:
        Why the operation is being executed.
        Example: "每日汇报"

    operation:
        Stable logical operation identifier.
        Example: "time.current"

    description:
        Human-readable and script-friendly description.
        Prefer English and begin with a stable status such as:
        START, SUCCESS, FAILED, INFO, WARNING.

    log_dir:
        Optional log directory override, mainly useful for tests.

    Returns
    -------
    dict
        Unified MuseAI Tool result for operation `log.write`.
    """
    tool_operation = "log.write"

    try:
        purpose = _normalize_required_field("purpose", purpose)
        operation = _normalize_required_field("operation", operation)
        description = _normalize_required_field("description", description)
    except (TypeError, ValueError) as exc:
        return failure(
            tool_operation,
            "INVALID_LOG_FIELD",
            "A required log field is invalid.",
            {"reason": str(exc)},
        )

    try:
        time_context = get_log_time()
        log_path = _resolve_log_path(
            time_context["current_month"],
            log_dir,
        )

        log_path.parent.mkdir(parents=True, exist_ok=True)

        line = DELIMITER.join(
            (
                _escape_field(time_context["current_date"]),
                _escape_field(time_context["current_time"]),
                _escape_field(purpose),
                _escape_field(operation),
                _escape_field(description),
            )
        )

        with log_path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(line + "\n")
            handle.flush()

    except (OSError, UnicodeError, ValueError) as exc:
        return failure(
            tool_operation,
            "LOG_WRITE_FAILED",
            "MuseAI could not write the log entry.",
            {
                "reason": str(exc),
            },
        )

    warnings: list[str] = []

    if time_context.get("warning"):
        warnings.append(
            "TIME_FALLBACK: " + str(time_context["warning"])
        )

    return success(
        tool_operation,
        {
            "written": True,
            "date": time_context["current_date"],
            "time": time_context["current_time"],
            "month": time_context["current_month"],
            "purpose": purpose,
            "logged_operation": operation,
            "description": description,
            "status": _extract_status(description),
            "path": str(log_path),
            "timestamp_source": time_context["source"],
        },
        warnings,
    )


def read_log(
    *,
    month: str | None = None,
    purpose: str | None = None,
    operation: str | None = None,
    status: str | None = None,
    tail: int | None = None,
    log_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Read and optionally filter one monthly MuseAI log.

    Parameters
    ----------
    month:
        Calendar month in YYYYMM format.
        Defaults to the current MuseAI log month.

    purpose:
        Optional exact PURPOSE filter.

    operation:
        Optional exact OPERATION filter.

    status:
        Optional status filter:
        START, SUCCESS, FAILED, INFO, WARNING.

    tail:
        Optional positive integer. Applied after filtering.

    log_dir:
        Optional log directory override, mainly useful for tests.

    Returns
    -------
    dict
        Unified MuseAI Tool result for operation `log.read`.
    """
    tool_operation = "log.read"
    warnings: list[str] = []

    if month is None:
        time_context = get_log_time()
        month = time_context["current_month"]

        if time_context.get("warning"):
            warnings.append(
                "TIME_FALLBACK: " + str(time_context["warning"])
            )

    if not isinstance(month, str) or not MONTH_PATTERN.fullmatch(month):
        return failure(
            tool_operation,
            "INVALID_MONTH",
            "`month` must use YYYYMM format.",
            {"month": month},
            warnings,
        )

    if status is not None:
        if not isinstance(status, str):
            return failure(
                tool_operation,
                "INVALID_STATUS",
                "`status` must be a string.",
                {"status": status},
                warnings,
            )

        status = status.strip().upper()

        if status not in KNOWN_STATUSES:
            return failure(
                tool_operation,
                "INVALID_STATUS",
                "Unsupported log status.",
                {
                    "status": status,
                    "allowed": sorted(KNOWN_STATUSES),
                },
                warnings,
            )

    if tail is not None:
        if isinstance(tail, bool) or not isinstance(tail, int) or tail <= 0:
            return failure(
                tool_operation,
                "INVALID_TAIL",
                "`tail` must be a positive integer.",
                {"tail": tail},
                warnings,
            )

    try:
        log_path = _resolve_log_path(month, log_dir)
    except ValueError as exc:
        return failure(
            tool_operation,
            "INVALID_MONTH",
            str(exc),
            {"month": month},
            warnings,
        )

    if not log_path.exists():
        warnings.append("LOG_FILE_NOT_FOUND")

        return success(
            tool_operation,
            {
                "month": month,
                "path": str(log_path),
                "count": 0,
                "entries": [],
            },
            warnings,
        )

    try:
        lines = log_path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        return failure(
            tool_operation,
            "LOG_READ_FAILED",
            "MuseAI could not read the log file.",
            {
                "path": str(log_path),
                "reason": str(exc),
            },
            warnings,
        )

    entries: list[dict[str, Any]] = []
    malformed_lines = 0

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue

        parts = line.split(DELIMITER)

        if len(parts) != 5:
            malformed_lines += 1
            continue

        date, time_value, entry_purpose, entry_operation, description = (
            _unescape_field(part) for part in parts
        )

        entry_status = _extract_status(description)

        if purpose is not None and entry_purpose != purpose:
            continue

        if operation is not None and entry_operation != operation:
            continue

        if status is not None and entry_status != status:
            continue

        entries.append(
            {
                "line": line_number,
                "date": date,
                "time": time_value,
                "purpose": entry_purpose,
                "operation": entry_operation,
                "status": entry_status,
                "description": description,
            }
        )

    if malformed_lines:
        warnings.append(
            f"MALFORMED_LOG_LINES: {malformed_lines}"
        )

    if tail is not None:
        entries = entries[-tail:]

    return success(
        tool_operation,
        {
            "month": month,
            "path": str(log_path),
            "count": len(entries),
            "entries": entries,
        },
        warnings,
    )
