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



def _run_task_tool(
    operation: str,
    function_name: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Import and execute one public Task Tool operation.

    Import/execution failures are converted to the same stable CLI-level
    errors used by the existing Time and Log routes. Business errors are
    expected to be returned by task_ops.task_tool itself.
    """
    try:
        from task_ops import task_tool
    except Exception as exc:
        return failure(
            operation,
            "TOOL_NOT_AVAILABLE",
            "The Task Tool is not available.",
            f"{type(exc).__name__}: {exc}",
        )

    action = getattr(task_tool, function_name, None)

    if action is None or not callable(action):
        return failure(
            operation,
            "TOOL_NOT_AVAILABLE",
            f"The Task Tool operation `{function_name}` is not available.",
            {"function": function_name},
        )

    try:
        result = action(**kwargs)
    except Exception as exc:
        return failure(
            operation,
            "TOOL_EXECUTION_FAILED",
            "The Task Tool failed unexpectedly.",
            f"{type(exc).__name__}: {exc}",
        )

    return normalize_tool_result(operation, result)


def run_task_daily_ensure(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.daily.ensure",
        "daily_ensure",
        date=args.date,
    )


def run_task_daily_read(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.daily.read",
        "daily_read",
        date=args.date,
    )


def run_task_daily_add(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.daily.add",
        "daily_add",
        title=args.title,
        description=args.description,
        category=args.category,
        source=args.source,
        long_task_id=args.long_task_id,
        date=args.date,
    )


def run_task_daily_update(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.daily.update",
        "daily_update",
        task_id=args.task_id,
        title=args.title,
        description=args.description,
        category=args.category,
        long_task_id=args.long_task_id,
        clear_long_task_id=args.clear_long_task_id,
        date=args.date,
    )


def run_task_daily_status(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.daily.status",
        "daily_status",
        task_id=args.task_id,
        status=args.status,
        date=args.date,
    )


def run_task_daily_remove(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.daily.remove",
        "daily_remove",
        task_id=args.task_id,
        date=args.date,
    )


def run_task_long_ensure(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.long.ensure",
        "long_ensure",
    )


def run_task_long_read(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.long.read",
        "long_read",
        collection=args.collection,
    )


def run_task_long_add(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.long.add",
        "long_add",
        title=args.title,
        description=args.description,
        category=args.category,
        active=not args.inactive,
        stage=args.stage,
        deadline=args.deadline,
    )


def run_task_long_update(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.long.update",
        "long_update",
        task_id=args.task_id,
        title=args.title,
        description=args.description,
        category=args.category,
    )


def run_task_long_status(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.long.status",
        "long_status",
        task_id=args.task_id,
        status=args.status,
    )


def run_task_long_activate(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.long.activate",
        "long_activate",
        task_id=args.task_id,
    )


def run_task_long_deactivate(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.long.deactivate",
        "long_deactivate",
        task_id=args.task_id,
    )


def run_task_long_stage(args: argparse.Namespace) -> dict[str, Any]:
    stage = None if args.clear_stage else args.stage

    return _run_task_tool(
        "task.long.stage",
        "long_stage",
        task_id=args.task_id,
        stage=stage,
    )


def run_task_long_deadline(args: argparse.Namespace) -> dict[str, Any]:
    deadline = None if args.clear_deadline else args.deadline

    return _run_task_tool(
        "task.long.deadline",
        "long_deadline",
        task_id=args.task_id,
        deadline=deadline,
    )


def run_task_long_record(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.long.record",
        "long_record",
        task_id=args.task_id,
        text=args.text,
        entry_type=args.entry_type,
    )


def run_task_long_archive(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.long.archive",
        "long_archive",
        task_id=args.task_id,
    )


def run_task_long_unarchive(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.long.unarchive",
        "long_unarchive",
        task_id=args.task_id,
    )


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


    task_parser = modules.add_parser(
        "task",
        help="Task management operations.",
    )
    task_kinds = task_parser.add_subparsers(
        dest="task_kind",
        metavar="<kind>",
    )

    daily_parser = task_kinds.add_parser(
        "daily",
        help="Daily Task JSON operations.",
    )
    daily_commands = daily_parser.add_subparsers(
        dest="command",
        metavar="<command>",
    )

    daily_ensure = daily_commands.add_parser(
        "ensure",
        help="Ensure the target Daily Task JSON file exists.",
    )
    daily_ensure.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format. Defaults to current MuseAI date.",
    )
    daily_ensure.set_defaults(
        handler=run_task_daily_ensure,
        route_operation="task.daily.ensure",
        auto_log=True,
    )

    daily_read = daily_commands.add_parser(
        "read",
        help="Read and validate one existing Daily Task JSON file.",
    )
    daily_read.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format. Defaults to current MuseAI date.",
    )
    daily_read.set_defaults(
        handler=run_task_daily_read,
        route_operation="task.daily.read",
        auto_log=True,
    )

    daily_add = daily_commands.add_parser(
        "add",
        help="Add one Task to an existing Daily Task JSON file.",
    )
    daily_add.add_argument(
        "--title",
        required=True,
        help="Task title.",
    )
    daily_add.add_argument(
        "--description",
        default="",
        help="Optional detailed Task description. Default: empty.",
    )
    daily_add.add_argument(
        "--category",
        default="未分类",
        help='User-defined category. Default: "未分类".',
    )
    daily_add.add_argument(
        "--source",
        choices=["manual", "carryover", "standing"],
        default="manual",
        help='Daily Task source. Default: "manual".',
    )
    daily_add.add_argument(
        "--long-task-id",
        dest="long_task_id",
        help="Optional related Long Task ID, for example L20260905-001.",
    )
    daily_add.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format. Defaults to current MuseAI date.",
    )
    daily_add.set_defaults(
        handler=run_task_daily_add,
        route_operation="task.daily.add",
        auto_log=True,
    )

    daily_update = daily_commands.add_parser(
        "update",
        help="Update editable fields of one existing Daily Task.",
    )
    daily_update.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Daily Task ID, for example D20260905-001.",
    )
    daily_update.add_argument(
        "--title",
        help="New Task title.",
    )
    daily_update.add_argument(
        "--description",
        help="New Task description.",
    )
    daily_update.add_argument(
        "--category",
        help="New user-defined category.",
    )
    daily_relation_group = daily_update.add_mutually_exclusive_group()
    daily_relation_group.add_argument(
        "--long-task-id",
        dest="long_task_id",
        help="Set the related Long Task ID.",
    )
    daily_relation_group.add_argument(
        "--clear-long-task-id",
        action="store_true",
        help="Remove the current Long Task relation.",
    )
    daily_update.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format. Defaults to current MuseAI date.",
    )
    daily_update.set_defaults(
        handler=run_task_daily_update,
        route_operation="task.daily.update",
        auto_log=True,
    )

    daily_status = daily_commands.add_parser(
        "status",
        help="Set Daily Task status.",
    )
    daily_status.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Daily Task ID.",
    )
    daily_status.add_argument(
        "--status",
        required=True,
        choices=["pending", "done"],
        help="Target Task status.",
    )
    daily_status.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format. Defaults to current MuseAI date.",
    )
    daily_status.set_defaults(
        handler=run_task_daily_status,
        route_operation="task.daily.status",
        auto_log=True,
    )

    daily_remove = daily_commands.add_parser(
        "remove",
        help="Physically remove one existing Daily Task.",
    )
    daily_remove.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Daily Task ID.",
    )
    daily_remove.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format. Defaults to current MuseAI date.",
    )
    daily_remove.set_defaults(
        handler=run_task_daily_remove,
        route_operation="task.daily.remove",
        auto_log=True,
    )


    long_parser = task_kinds.add_parser(
        "long",
        help="Long Task JSON operations.",
    )
    long_commands = long_parser.add_subparsers(
        dest="command",
        metavar="<command>",
    )

    long_ensure = long_commands.add_parser(
        "ensure",
        help="Ensure active and archived Long Task JSON files exist.",
    )
    long_ensure.set_defaults(
        handler=run_task_long_ensure,
        route_operation="task.long.ensure",
        auto_log=True,
    )

    long_read = long_commands.add_parser(
        "read",
        help="Read and validate Long Task collections.",
    )
    long_read.add_argument(
        "--collection",
        choices=["active", "archived", "all"],
        default="active",
        help='Collection to read. Default: "active".',
    )
    long_read.set_defaults(
        handler=run_task_long_read,
        route_operation="task.long.read",
        auto_log=True,
    )

    long_add = long_commands.add_parser(
        "add",
        help="Add one Long Task to the active collection.",
    )
    long_add.add_argument(
        "--title",
        required=True,
        help="Long Task title.",
    )
    long_add.add_argument(
        "--description",
        default="",
        help="Optional detailed Long Task description. Default: empty.",
    )
    long_add.add_argument(
        "--category",
        default="未分类",
        help='User-defined category. Default: "未分类".',
    )
    long_add.add_argument(
        "--inactive",
        action="store_true",
        help="Create the Long Task paused instead of active.",
    )
    long_add.add_argument(
        "--stage",
        help="Optional initial Long Task stage.",
    )
    long_add.add_argument(
        "--deadline",
        help="Optional deadline in YYYY-MM-DD format.",
    )
    long_add.set_defaults(
        handler=run_task_long_add,
        route_operation="task.long.add",
        auto_log=True,
    )

    long_update = long_commands.add_parser(
        "update",
        help="Update ordinary editable fields of one active Long Task.",
    )
    long_update.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Long Task ID, for example L20260905-001.",
    )
    long_update.add_argument(
        "--title",
        help="New Long Task title.",
    )
    long_update.add_argument(
        "--description",
        help="New Long Task description.",
    )
    long_update.add_argument(
        "--category",
        help="New user-defined category.",
    )
    long_update.set_defaults(
        handler=run_task_long_update,
        route_operation="task.long.update",
        auto_log=True,
    )

    long_status = long_commands.add_parser(
        "status",
        help="Set Long Task completion status.",
    )
    long_status.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Long Task ID.",
    )
    long_status.add_argument(
        "--status",
        required=True,
        choices=["pending", "done"],
        help="Target Long Task status.",
    )
    long_status.set_defaults(
        handler=run_task_long_status,
        route_operation="task.long.status",
        auto_log=True,
    )

    long_activate = long_commands.add_parser(
        "activate",
        help="Activate one pending Long Task.",
    )
    long_activate.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Long Task ID.",
    )
    long_activate.set_defaults(
        handler=run_task_long_activate,
        route_operation="task.long.activate",
        auto_log=True,
    )

    long_deactivate = long_commands.add_parser(
        "deactivate",
        help="Pause one active Long Task.",
    )
    long_deactivate.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Long Task ID.",
    )
    long_deactivate.set_defaults(
        handler=run_task_long_deactivate,
        route_operation="task.long.deactivate",
        auto_log=True,
    )

    long_stage = long_commands.add_parser(
        "stage",
        help="Set or clear the current Long Task stage.",
    )
    long_stage.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Long Task ID.",
    )
    long_stage_group = long_stage.add_mutually_exclusive_group(required=True)
    long_stage_group.add_argument(
        "--stage",
        help="New Long Task stage.",
    )
    long_stage_group.add_argument(
        "--clear",
        dest="clear_stage",
        action="store_true",
        help="Clear the current Long Task stage.",
    )
    long_stage.set_defaults(
        handler=run_task_long_stage,
        route_operation="task.long.stage",
        auto_log=True,
    )

    long_deadline = long_commands.add_parser(
        "deadline",
        help="Set or clear the Long Task deadline.",
    )
    long_deadline.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Long Task ID.",
    )
    long_deadline_group = long_deadline.add_mutually_exclusive_group(required=True)
    long_deadline_group.add_argument(
        "--deadline",
        help="New deadline in YYYY-MM-DD format.",
    )
    long_deadline_group.add_argument(
        "--clear",
        dest="clear_deadline",
        action="store_true",
        help="Clear the current Long Task deadline.",
    )
    long_deadline.set_defaults(
        handler=run_task_long_deadline,
        route_operation="task.long.deadline",
        auto_log=True,
    )

    long_record = long_commands.add_parser(
        "record",
        help="Append a user progress or note event to one active Long Task.",
    )
    long_record.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Long Task ID.",
    )
    long_record.add_argument(
        "--text",
        required=True,
        help="Timeline record text.",
    )
    long_record.add_argument(
        "--type",
        dest="entry_type",
        choices=["progress", "note"],
        default="progress",
        help='Timeline record type. Default: "progress".',
    )
    long_record.set_defaults(
        handler=run_task_long_record,
        route_operation="task.long.record",
        auto_log=True,
    )

    long_archive = long_commands.add_parser(
        "archive",
        help="Move one Long Task from active to archived collection.",
    )
    long_archive.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Long Task ID.",
    )
    long_archive.set_defaults(
        handler=run_task_long_archive,
        route_operation="task.long.archive",
        auto_log=True,
    )

    long_unarchive = long_commands.add_parser(
        "unarchive",
        help="Restore one Long Task from archived to active collection.",
    )
    long_unarchive.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Long Task ID.",
    )
    long_unarchive.set_defaults(
        handler=run_task_long_unarchive,
        route_operation="task.long.unarchive",
        auto_log=True,
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
