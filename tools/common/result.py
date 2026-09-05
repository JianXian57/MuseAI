#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI shared Tool result helpers.

Recommended location:
    MuseAI/tools/common/result.py

Purpose
-------
Provide the single implementation of MuseAI's Tool result protocol.

Protocol
--------
{
    "ok": true,
    "operation": "time.current",
    "data": {},
    "warnings": [],
    "error": null
}

This module contains no CLI output, Tool routing, logging, or business logic.
"""

from __future__ import annotations

from typing import Any


def success(
    operation: str,
    data: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build a successful MuseAI Tool result."""
    return {
        "ok": True,
        "operation": operation,
        "data": data or {},
        "warnings": list(warnings or []),
        "error": None,
    }


def failure(
    operation: str,
    code: str,
    message: str,
    details: Any = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build a failed MuseAI Tool result."""
    return {
        "ok": False,
        "operation": operation,
        "data": {},
        "warnings": list(warnings or []),
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
    }


def normalize_tool_result(
    operation: str,
    result: Any,
) -> dict[str, Any]:
    """
    Normalize a Tool return value into the MuseAI Tool protocol.

    A plain dict without an `ok` field is temporarily accepted and wrapped
    into `data` for compatibility with simple or transitional Tool modules.
    """
    if not isinstance(result, dict):
        return failure(
            operation,
            "INVALID_TOOL_RESULT",
            "Tool returned an unsupported result type.",
            {"type": type(result).__name__},
        )

    if "ok" not in result:
        return success(
            operation=operation,
            data=result,
        )

    normalized = {
        "ok": bool(result.get("ok")),
        "operation": result.get("operation") or operation,
        "data": result.get("data") or {},
        "warnings": list(result.get("warnings") or []),
        "error": result.get("error"),
    }

    if normalized["ok"]:
        normalized["error"] = None
    elif normalized["error"] is None:
        normalized["error"] = {
            "code": "TOOL_ERROR",
            "message": "Tool reported failure without error details.",
            "details": None,
        }

    return normalized


def append_warning(
    result: dict[str, Any],
    warning: str | None,
) -> dict[str, Any]:
    """Append one warning without changing the Tool success/failure state."""
    if not warning:
        return result

    warnings = result.setdefault("warnings", [])

    if warning not in warnings:
        warnings.append(warning)

    return result
