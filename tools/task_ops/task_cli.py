#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI Task CLI registration and routing layer.

Recommended location:
    MuseAI/tools/task_ops/task_cli.py

Responsibilities
----------------
- Register the `task` CLI tree under the root MuseAI parser.
- Define Daily, Long, Standing, and maintenance CLI arguments.
- Convert parsed CLI arguments into public Task Tool calls.
- Preserve stable `route_operation` and `auto_log` metadata for muse.py.

This module does not:
- own lifecycle logging;
- print final CLI output;
- choose process exit codes;
- directly manipulate Task JSON;
- implement Task business logic.

Runtime flow:
    muse.py
      -> task_cli.py
      -> task_tool.py
      -> *_service.py
"""

from __future__ import annotations

import argparse
from typing import Any

from common.result import failure, normalize_tool_result


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
        standing_task_id=args.standing_task_id,
        carryover_from_task_id=args.carryover_from_task_id,
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
        standing_task_id=args.standing_task_id,
        clear_standing_task_id=args.clear_standing_task_id,
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


def run_task_maintenance_check(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.maintenance.check",
        "maintenance_check",
        date=args.date,
    )


def run_task_maintenance_apply(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.maintenance.apply",
        "maintenance_apply",
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



def _standing_schedule_from_args(
    args: argparse.Namespace,
) -> dict[str, Any]:
    schedule_type = args.schedule

    if schedule_type == "daily":
        return {
            "type": "daily",
        }

    if schedule_type == "weekly":
        return {
            "type": "weekly",
            "weekdays": args.weekdays,
        }

    if schedule_type == "monthly":
        return {
            "type": "monthly",
            "day": args.day,
        }

    return {
        "type": "yearly",
        "month": args.month,
        "day": args.day,
    }


def run_task_standing_ensure(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.standing.ensure",
        "standing_ensure",
    )


def run_task_standing_read(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.standing.read",
        "standing_read",
    )


def run_task_standing_add(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.standing.add",
        "standing_add",
        title=args.title,
        description=args.description,
        category=args.category,
        enabled=not args.disabled,
        schedule=_standing_schedule_from_args(args),
        long_task_id=args.long_task_id,
    )


def run_task_standing_update(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.standing.update",
        "standing_update",
        task_id=args.task_id,
        title=args.title,
        description=args.description,
        category=args.category,
        long_task_id=args.long_task_id,
        clear_long_task_id=args.clear_long_task_id,
    )


def run_task_standing_enable(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.standing.enable",
        "standing_enable",
        task_id=args.task_id,
    )


def run_task_standing_disable(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.standing.disable",
        "standing_disable",
        task_id=args.task_id,
    )


def run_task_standing_schedule(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.standing.schedule",
        "standing_schedule",
        task_id=args.task_id,
        schedule=_standing_schedule_from_args(args),
    )


def run_task_standing_due(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.standing.due",
        "standing_due",
        date=args.date,
        include_not_due=args.include_not_due,
    )


def run_task_standing_mark_generated(
    args: argparse.Namespace,
) -> dict[str, Any]:
    return _run_task_tool(
        "task.standing.mark-generated",
        "standing_mark_generated",
        task_id=args.task_id,
        date=args.date,
    )


def run_task_standing_remove(args: argparse.Namespace) -> dict[str, Any]:
    return _run_task_tool(
        "task.standing.remove",
        "standing_remove",
        task_id=args.task_id,
    )


def register_task_cli(modules: Any) -> argparse.ArgumentParser:
    """
    Register the complete `task` command tree.

    `modules` is the root argparse subparser collection created by muse.py.
    External CLI behavior remains unchanged.
    """
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
        "--standing-task-id",
        dest="standing_task_id",
        help="Optional related Standing Task ID, for example S20260905-001.",
    )
    daily_add.add_argument(
        "--carryover-from-task-id",
        dest="carryover_from_task_id",
        help=(
            "Prior Daily Task ID used as carryover provenance. "
            "Valid only with --source carryover."
        ),
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
    daily_standing_relation_group = daily_update.add_mutually_exclusive_group()
    daily_standing_relation_group.add_argument(
        "--standing-task-id",
        dest="standing_task_id",
        help="Set the related Standing Task ID.",
    )
    daily_standing_relation_group.add_argument(
        "--clear-standing-task-id",
        action="store_true",
        help="Remove the current Standing Task relation.",
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


    maintenance_parser = task_kinds.add_parser(
        "maintenance",
        help="Daily Task cross-day maintenance operations.",
    )
    maintenance_commands = maintenance_parser.add_subparsers(
        dest="command",
        metavar="<command>",
    )

    maintenance_check = maintenance_commands.add_parser(
        "check",
        help="Read-only check of carryover and Standing maintenance actions.",
    )
    maintenance_check.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format. Defaults to current MuseAI date.",
    )
    maintenance_check.set_defaults(
        handler=run_task_maintenance_check,
        route_operation="task.maintenance.check",
        auto_log=True,
    )

    maintenance_apply = maintenance_commands.add_parser(
        "apply",
        help="Apply idempotent cross-day Task maintenance for one date.",
    )
    maintenance_apply.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format. Defaults to current MuseAI date.",
    )
    maintenance_apply.set_defaults(
        handler=run_task_maintenance_apply,
        route_operation="task.maintenance.apply",
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


    standing_parser = task_kinds.add_parser(
        "standing",
        help="Standing Task recurrence operations.",
    )
    standing_commands = standing_parser.add_subparsers(
        dest="command",
        metavar="<command>",
    )

    standing_ensure = standing_commands.add_parser(
        "ensure",
        help="Ensure the Standing Task JSON file exists.",
    )
    standing_ensure.set_defaults(
        handler=run_task_standing_ensure,
        route_operation="task.standing.ensure",
        auto_log=True,
    )

    standing_read = standing_commands.add_parser(
        "read",
        help="Read and validate the Standing Task JSON file.",
    )
    standing_read.set_defaults(
        handler=run_task_standing_read,
        route_operation="task.standing.read",
        auto_log=True,
    )

    standing_add = standing_commands.add_parser(
        "add",
        help="Add one Standing Task recurrence rule.",
    )
    standing_add.add_argument(
        "--title",
        required=True,
        help="Standing Task title copied to generated Daily Tasks.",
    )
    standing_add.add_argument(
        "--description",
        default="",
        help="Optional Standing Task description. Default: empty.",
    )
    standing_add.add_argument(
        "--category",
        default="未分类",
        help='User-defined category. Default: "未分类".',
    )
    standing_add.add_argument(
        "--disabled",
        action="store_true",
        help="Create the Standing Task disabled.",
    )
    standing_add.add_argument(
        "--long-task-id",
        dest="long_task_id",
        help="Optional Long Task relation inherited by generated Daily Tasks.",
    )
    standing_add.add_argument(
        "--schedule",
        required=True,
        choices=["daily", "weekly", "monthly", "yearly"],
        help="Recurrence schedule type.",
    )
    standing_add.add_argument(
        "--weekdays",
        nargs="+",
        choices=[
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ],
        help="Weekly recurrence weekdays.",
    )
    standing_add.add_argument(
        "--day",
        type=int,
        help="Monthly day, or yearly day of month.",
    )
    standing_add.add_argument(
        "--month",
        type=int,
        help="Yearly recurrence month.",
    )
    standing_add.set_defaults(
        handler=run_task_standing_add,
        route_operation="task.standing.add",
        auto_log=True,
    )

    standing_update = standing_commands.add_parser(
        "update",
        help="Update ordinary editable fields of one Standing Task.",
    )
    standing_update.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Standing Task ID, for example S20260905-001.",
    )
    standing_update.add_argument(
        "--title",
        help="New Standing Task title.",
    )
    standing_update.add_argument(
        "--description",
        help="New Standing Task description.",
    )
    standing_update.add_argument(
        "--category",
        help="New user-defined category.",
    )
    standing_long_group = standing_update.add_mutually_exclusive_group()
    standing_long_group.add_argument(
        "--long-task-id",
        dest="long_task_id",
        help="Set the optional Long Task relation.",
    )
    standing_long_group.add_argument(
        "--clear-long-task-id",
        action="store_true",
        help="Remove the current Long Task relation.",
    )
    standing_update.set_defaults(
        handler=run_task_standing_update,
        route_operation="task.standing.update",
        auto_log=True,
    )

    standing_enable = standing_commands.add_parser(
        "enable",
        help="Enable one Standing Task recurrence rule.",
    )
    standing_enable.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Standing Task ID.",
    )
    standing_enable.set_defaults(
        handler=run_task_standing_enable,
        route_operation="task.standing.enable",
        auto_log=True,
    )

    standing_disable = standing_commands.add_parser(
        "disable",
        help="Disable one Standing Task recurrence rule.",
    )
    standing_disable.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Standing Task ID.",
    )
    standing_disable.set_defaults(
        handler=run_task_standing_disable,
        route_operation="task.standing.disable",
        auto_log=True,
    )

    standing_schedule = standing_commands.add_parser(
        "schedule",
        help="Replace one Standing Task recurrence schedule.",
    )
    standing_schedule.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Standing Task ID.",
    )
    standing_schedule.add_argument(
        "--schedule",
        required=True,
        choices=["daily", "weekly", "monthly", "yearly"],
        help="New recurrence schedule type.",
    )
    standing_schedule.add_argument(
        "--weekdays",
        nargs="+",
        choices=[
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ],
        help="Weekly recurrence weekdays.",
    )
    standing_schedule.add_argument(
        "--day",
        type=int,
        help="Monthly day, or yearly day of month.",
    )
    standing_schedule.add_argument(
        "--month",
        type=int,
        help="Yearly recurrence month.",
    )
    standing_schedule.set_defaults(
        handler=run_task_standing_schedule,
        route_operation="task.standing.schedule",
        auto_log=True,
    )

    standing_due = standing_commands.add_parser(
        "due",
        help="Check which Standing Tasks are due on one date.",
    )
    standing_due.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format. Defaults to current MuseAI date.",
    )
    standing_due.add_argument(
        "--include-not-due",
        action="store_true",
        help="Include disabled, unmatched, and already-generated rules.",
    )
    standing_due.set_defaults(
        handler=run_task_standing_due,
        route_operation="task.standing.due",
        auto_log=True,
    )

    standing_mark_generated = standing_commands.add_parser(
        "mark-generated",
        help="Record that one Standing Task Daily occurrence exists for a date.",
    )
    standing_mark_generated.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Standing Task ID.",
    )
    standing_mark_generated.add_argument(
        "--date",
        help="Generated Daily date. Defaults to current MuseAI date.",
    )
    standing_mark_generated.set_defaults(
        handler=run_task_standing_mark_generated,
        route_operation="task.standing.mark-generated",
        auto_log=True,
    )

    standing_remove = standing_commands.add_parser(
        "remove",
        help="Physically remove one Standing Task recurrence rule.",
    )
    standing_remove.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Standing Task ID.",
    )
    standing_remove.set_defaults(
        handler=run_task_standing_remove,
        route_operation="task.standing.remove",
        auto_log=True,
    )
    return task_parser
