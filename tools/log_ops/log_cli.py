#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI Log CLI adapter.

Recommended location:
    MuseAI/tools/log_ops/log_cli.py

Responsibilities
----------------
- Register the public `log` CLI tree.
- Route explicit log.read / log.write commands to the public Log Tool.
- Convert unexpected import/execution failures into the unified Tool protocol.

Important boundary
------------------
This module handles user-invoked Log commands only.

Root lifecycle logging for ordinary MuseAI Tool execution remains owned by
`muse.py`. `log.read` and `log.write` therefore keep auto_log=False to avoid
recursive/self-referential lifecycle logging.

This module does not:
- implement log storage logic;
- print final CLI output;
- choose process exit codes;
- own root lifecycle logging.
"""

from __future__ import annotations

import argparse
from typing import Any

from common.result import failure, normalize_tool_result


def run_log_write(args: argparse.Namespace) -> dict[str, Any]:
    operation = "log.write"

    try:
        from log_ops.log_tool import write_log
    except Exception as exc:
        return failure(
            operation,
            "TOOL_NOT_AVAILABLE",
            "The log Tool is not available.",
            f"{type(exc).__name__}: {exc}",
        )

    try:
        result = write_log(
            purpose=args.purpose,
            operation=args.logged_operation,
            description=args.description,
        )
    except Exception as exc:
        return failure(
            operation,
            "TOOL_EXECUTION_FAILED",
            "The log Tool failed unexpectedly.",
            f"{type(exc).__name__}: {exc}",
        )

    return normalize_tool_result(operation, result)


def run_log_read(args: argparse.Namespace) -> dict[str, Any]:
    operation = "log.read"

    try:
        from log_ops.log_tool import read_log
    except Exception as exc:
        return failure(
            operation,
            "TOOL_NOT_AVAILABLE",
            "The log Tool is not available.",
            f"{type(exc).__name__}: {exc}",
        )

    try:
        result = read_log(
            month=args.month,
            purpose=args.entry_purpose,
            operation=args.logged_operation,
            status=args.status,
            tail=args.tail,
        )
    except Exception as exc:
        return failure(
            operation,
            "TOOL_EXECUTION_FAILED",
            "The log Tool failed unexpectedly.",
            f"{type(exc).__name__}: {exc}",
        )

    return normalize_tool_result(operation, result)


def register_log_cli(modules: Any) -> argparse.ArgumentParser:
    """Register the complete `log` command tree."""
    log_parser = modules.add_parser(
        "log",
        help="Read or write MuseAI log entries.",
    )
    log_commands = log_parser.add_subparsers(
        dest="command",
        metavar="<command>",
    )

    log_write = log_commands.add_parser(
        "write",
        help="Write one explicit MuseAI log entry.",
    )
    log_write.add_argument(
        "--operation",
        dest="logged_operation",
        required=True,
        help="Logical operation identifier to store in the log.",
    )
    log_write.add_argument(
        "--description",
        required=True,
        help=(
            "Log description. Prefer English and begin with "
            "START, SUCCESS, FAILED, INFO, or WARNING."
        ),
    )
    log_write.set_defaults(
        handler=run_log_write,
        route_operation="log.write",
        auto_log=False,
    )

    log_read = log_commands.add_parser(
        "read",
        help="Read and optionally filter one monthly MuseAI log.",
    )
    log_read.add_argument(
        "--month",
        help="Calendar month in YYYYMM format. Defaults to current month.",
    )
    log_read.add_argument(
        "--entry-purpose",
        help="Exact PURPOSE filter for stored log entries.",
    )
    log_read.add_argument(
        "--operation",
        dest="logged_operation",
        help="Exact OPERATION filter for stored log entries.",
    )
    log_read.add_argument(
        "--status",
        choices=["START", "SUCCESS", "FAILED", "INFO", "WARNING"],
        help="Filter by DESCRIPTION status prefix.",
    )
    log_read.add_argument(
        "--tail",
        type=int,
        help="Return only the last N matching entries.",
    )
    log_read.set_defaults(
        handler=run_log_read,
        route_operation="log.read",
        auto_log=False,
    )

    return log_parser
