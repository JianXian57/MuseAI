#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI unified CLI entry point.

Recommended location:
    MuseAI/muse.py

Responsibilities
----------------
- Parse root-level command-line arguments.
- Register command modules and dispatch parsed handlers.
- Register Time, Log, Task, Report, and Init CLI modules under `tools/`.
- Provide one unified JSON output.
- Attach execution purpose context.
- Record START / SUCCESS / FAILED lifecycle logs for normal Tool operations.
- Set a meaningful process exit code.

Business logic must remain inside Tool/Service modules. Feature-specific CLI definitions belong in their corresponding `*_cli.py` adapters.

Logging policy
--------------
Only this entry point decides when lifecycle logs are written.

Normal Tool:
    muse.py
      -> log START
      -> execute Tool
      -> log SUCCESS / FAILED
      -> emit Tool JSON

Log Tool:
    `log.write` and `log.read` are not automatically logged themselves,
    preventing recursive/self-referential logging.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parent
TOOLS_ROOT = PROJECT_ROOT / "tools"

if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from common.result import append_warning, failure, normalize_tool_result


def emit(result: dict[str, Any]) -> int:
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") is True else 1


def _write_lifecycle_log(
    *,
    purpose: str,
    operation: str,
    description: str,
) -> str | None:
    """
    Write one lifecycle log entry.

    Logging failure is returned as a warning and must not replace the
    actual Tool result.
    """
    try:
        from log_ops.log_tool import write_log
    except Exception as exc:
        return f"LOG_UNAVAILABLE: {type(exc).__name__}: {exc}"

    try:
        log_result = write_log(
            purpose=purpose,
            operation=operation,
            description=description,
        )
    except Exception as exc:
        return f"LOG_WRITE_EXCEPTION: {type(exc).__name__}: {exc}"

    if not isinstance(log_result, dict):
        return "LOG_INVALID_RESULT: log.write returned a non-dict result."

    if log_result.get("ok") is not True:
        error = log_result.get("error") or {}
        code = error.get("code") or "LOG_WRITE_FAILED"
        message = error.get("message") or "Unknown log write failure."
        return f"{code}: {message}"

    log_warnings = log_result.get("warnings") or []

    if log_warnings:
        return "LOG_WARNING: " + " | ".join(str(item) for item in log_warnings)

    return None


def _failure_description(result: dict[str, Any]) -> str:
    error = result.get("error") or {}
    code = str(error.get("code") or "TOOL_ERROR")
    message = str(error.get("message") or "Tool execution failed.")
    return f"FAILED {code}: {message}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="muse",
        description="MuseAI unified Tool command-line interface.",
    )

    parser.add_argument(
        "--purpose",
        default="Direct",
        help=(
            "Execution purpose used by lifecycle logging. "
            'Example: --purpose "每日汇报". '
            'Default: "Direct".'
        ),
    )

    modules = parser.add_subparsers(
        dest="module",
        metavar="<module>",
    )

    from time_ops.time_cli import register_time_cli
    from log_ops.log_cli import register_log_cli
    from task_ops.task_cli import register_task_cli
    from report_ops.report_cli import register_report_cli
    from init_ops.init_cli import register_init_cli

    register_time_cli(modules)
    register_log_cli(modules)
    register_task_cli(modules)
    register_report_cli(modules)
    register_init_cli(modules)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handler: Callable[[argparse.Namespace], dict[str, Any]] | None = getattr(
        args,
        "handler",
        None,
    )

    if handler is None:
        parser.print_help(sys.stderr)
        return 2

    purpose = str(getattr(args, "purpose", "Direct")).strip() or "Direct"
    operation = str(getattr(args, "route_operation", "system.unknown"))
    auto_log = bool(getattr(args, "auto_log", False))

    start_log_warning: str | None = None

    if auto_log:
        start_log_warning = _write_lifecycle_log(
            purpose=purpose,
            operation=operation,
            description=f"START Execute {operation}.",
        )

    try:
        result = handler(args)

    except KeyboardInterrupt:
        result = failure(
            operation,
            "INTERRUPTED",
            "Operation interrupted by the user.",
        )

    except Exception as exc:
        result = failure(
            operation,
            "UNHANDLED_ERROR",
            "Unhandled MuseAI CLI error.",
            f"{type(exc).__name__}: {exc}",
        )

    result = normalize_tool_result(operation, result)

    if start_log_warning:
        append_warning(result, start_log_warning)

    if auto_log:
        if result.get("ok") is True:
            description = f"SUCCESS Execute {operation}."
        else:
            description = _failure_description(result)

        finish_log_warning = _write_lifecycle_log(
            purpose=purpose,
            operation=operation,
            description=description,
        )

        if finish_log_warning:
            append_warning(result, finish_log_warning)

    return emit(result)


if __name__ == "__main__":
    raise SystemExit(main())
