#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI Report CLI adapter.

Recommended location:
    MuseAI/tools/report_ops/report_cli.py

Responsibilities
----------------
- Register the public `report` CLI tree.
- Route `report daily` to the public Report Tool.
- Convert unexpected import/execution failures into the MuseAI Tool protocol.

This module does not:
- implement report snapshot logic;
- generate natural-language reports;
- print final CLI output;
- choose process exit codes;
- write lifecycle logs.
"""

from __future__ import annotations

import argparse
from typing import Any

from common.result import failure, normalize_tool_result


def run_report_daily(args: argparse.Namespace) -> dict[str, Any]:
    operation = "report.daily"

    try:
        from report_ops.report_tool import daily_report
    except Exception as exc:
        return failure(
            operation,
            "TOOL_NOT_AVAILABLE",
            "The Report Tool is not available.",
            f"{type(exc).__name__}: {exc}",
        )

    try:
        result = daily_report(
            date=args.date,
        )
    except Exception as exc:
        return failure(
            operation,
            "TOOL_EXECUTION_FAILED",
            "The Report Tool failed unexpectedly.",
            f"{type(exc).__name__}: {exc}",
        )

    return normalize_tool_result(operation, result)


def register_report_cli(modules: Any) -> argparse.ArgumentParser:
    """Register the complete `report` command tree."""
    report_parser = modules.add_parser(
        "report",
        help="Read-only report snapshot operations.",
    )
    report_commands = report_parser.add_subparsers(
        dest="command",
        metavar="<command>",
    )

    report_daily = report_commands.add_parser(
        "daily",
        help="Build a deterministic Daily Report snapshot.",
    )
    report_daily.add_argument(
        "--date",
        help=(
            "Report date in YYYY-MM-DD format. "
            "Defaults to the current MuseAI date."
        ),
    )
    report_daily.set_defaults(
        handler=run_report_daily,
        route_operation="report.daily",
        auto_log=True,
    )

    return report_parser
