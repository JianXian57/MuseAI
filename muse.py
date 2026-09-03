#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI unified CLI entry point.

Recommended location:
    MuseAI/muse.py

Responsibilities
----------------
- Parse command-line arguments.
- Route requests to public Tool modules under `tools/`.
- Provide one unified JSON output.
- Attach execution purpose context.
- Record START / SUCCESS / FAILED lifecycle logs for normal Tool operations.
- Set a meaningful process exit code.

Business logic must remain inside Tool modules.

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


def success(
    operation: str,
    data: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": operation,
        "data": data or {},
        "warnings": warnings or [],
        "error": None,
    }


def failure(
    operation: str,
    message: str,
    *,
    code: str = "TOOL_ERROR",
    details: Any = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": operation,
        "data": {},
        "warnings": warnings or [],
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
    }


def emit(result: dict[str, Any]) -> int:
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") is True else 1


def normalize_tool_result(
    operation: str,
    result: Any,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        return failure(
            operation,
            "Tool returned an unsupported result type.",
            code="INVALID_TOOL_RESULT",
            details={"type": type(result).__name__},
        )

    if "ok" not in result:
        return success(operation=operation, data=result)

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
    if not warning:
        return result

    warnings = result.setdefault("warnings", [])

    if warning not in warnings:
        warnings.append(warning)

    return result


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


def run_time_current(_: argparse.Namespace) -> dict[str, Any]:
    operation = "time.current"

    try:
        from time_ops.time_tool import current_time
    except Exception as exc:
        return failure(
            operation,
            "The time Tool is not available.",
            code="TOOL_NOT_AVAILABLE",
            details=f"{type(exc).__name__}: {exc}",
        )

    try:
        result = current_time()
    except Exception as exc:
        return failure(
            operation,
            "The time Tool failed unexpectedly.",
            code="TOOL_EXECUTION_FAILED",
            details=f"{type(exc).__name__}: {exc}",
        )

    return normalize_tool_result(operation, result)


def run_log_write(args: argparse.Namespace) -> dict[str, Any]:
    operation = "log.write"

    try:
        from log_ops.log_tool import write_log
    except Exception as exc:
        return failure(
            operation,
            "The log Tool is not available.",
            code="TOOL_NOT_AVAILABLE",
            details=f"{type(exc).__name__}: {exc}",
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
            "The log Tool failed unexpectedly.",
            code="TOOL_EXECUTION_FAILED",
            details=f"{type(exc).__name__}: {exc}",
        )

    return normalize_tool_result(operation, result)


def run_log_read(args: argparse.Namespace) -> dict[str, Any]:
    operation = "log.read"

    try:
        from log_ops.log_tool import read_log
    except Exception as exc:
        return failure(
            operation,
            "The log Tool is not available.",
            code="TOOL_NOT_AVAILABLE",
            details=f"{type(exc).__name__}: {exc}",
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
            "The log Tool failed unexpectedly.",
            code="TOOL_EXECUTION_FAILED",
            details=f"{type(exc).__name__}: {exc}",
        )

    return normalize_tool_result(operation, result)


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
            "Operation interrupted by the user.",
            code="INTERRUPTED",
        )

    except Exception as exc:
        result = failure(
            operation,
            "Unhandled MuseAI CLI error.",
            code="UNHANDLED_ERROR",
            details=f"{type(exc).__name__}: {exc}",
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
