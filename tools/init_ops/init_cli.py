#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI Initialization CLI adapter.

Recommended location:
    MuseAI/tools/init_ops/init_cli.py

Responsibilities
----------------
- Register the public `init` CLI tree.
- Route `init daily` to the public Initialization Tool.
- Convert unexpected import/execution failures into the MuseAI Tool protocol.

This module does not:
- implement Daily initialization logic;
- parse or modify Task JSON;
- print final CLI output;
- choose process exit codes;
- write lifecycle logs.
"""

from __future__ import annotations

import argparse
from typing import Any

from common.result import failure, normalize_tool_result


def run_init_daily(args: argparse.Namespace) -> dict[str, Any]:
    operation = "init.daily"

    try:
        from init_ops.init_tool import daily_init
    except Exception as exc:
        return failure(
            operation,
            "TOOL_NOT_AVAILABLE",
            "The Initialization Tool is not available.",
            f"{type(exc).__name__}: {exc}",
        )

    try:
        result = daily_init(
            date=args.date,
        )
    except Exception as exc:
        return failure(
            operation,
            "TOOL_EXECUTION_FAILED",
            "The Initialization Tool failed unexpectedly.",
            f"{type(exc).__name__}: {exc}",
        )

    return normalize_tool_result(operation, result)


def register_init_cli(modules: Any) -> argparse.ArgumentParser:
    """Register the complete `init` command tree."""
    init_parser = modules.add_parser(
        "init",
        help="Deterministic MuseAI initialization operations.",
    )
    init_commands = init_parser.add_subparsers(
        dest="command",
        metavar="<command>",
    )

    init_daily = init_commands.add_parser(
        "daily",
        help="Prepare one Daily Task date through Task Maintenance.",
    )
    init_daily.add_argument(
        "--date",
        help=(
            "Daily initialization date in YYYY-MM-DD format. "
            "Defaults to the current MuseAI date."
        ),
    )
    init_daily.set_defaults(
        handler=run_init_daily,
        route_operation="init.daily",
        auto_log=True,
    )

    return init_parser
