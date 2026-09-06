#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI Time CLI adapter.

Recommended location:
    MuseAI/tools/time_ops/time_cli.py

Responsibilities
----------------
- Register the public `time` CLI tree.
- Route parsed Time commands to the public Time Tool.
- Convert unexpected import/execution failures into the unified Tool protocol.

This module does not:
- implement time business logic;
- print final CLI output;
- choose process exit codes;
- write lifecycle logs.
"""

from __future__ import annotations

import argparse
from typing import Any

from common.result import failure, normalize_tool_result


def run_time_current(_: argparse.Namespace) -> dict[str, Any]:
    operation = "time.current"

    try:
        from time_ops.time_tool import current_time
    except Exception as exc:
        return failure(
            operation,
            "TOOL_NOT_AVAILABLE",
            "The time Tool is not available.",
            f"{type(exc).__name__}: {exc}",
        )

    try:
        result = current_time()
    except Exception as exc:
        return failure(
            operation,
            "TOOL_EXECUTION_FAILED",
            "The time Tool failed unexpectedly.",
            f"{type(exc).__name__}: {exc}",
        )

    return normalize_tool_result(operation, result)


def register_time_cli(modules: Any) -> argparse.ArgumentParser:
    """Register the complete `time` command tree."""
    time_parser = modules.add_parser(
        "time",
        help="Date and time operations.",
    )
    time_commands = time_parser.add_subparsers(
        dest="command",
        metavar="<command>",
    )

    time_current = time_commands.add_parser(
        "current",
        help="Return MuseAI's current configured local time context.",
    )
    time_current.set_defaults(
        handler=run_time_current,
        route_operation="time.current",
        auto_log=True,
    )

    return time_parser
