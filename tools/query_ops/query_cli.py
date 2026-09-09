#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI Query CLI adapter.

Recommended location:
    MuseAI/tools/query_ops/query_cli.py

Public tree
-----------
python muse.py query task daily ...
python muse.py query task long ...
python muse.py query task standing ...
python muse.py query task related ...
python muse.py query task overview ...
python muse.py query character current
"""

from __future__ import annotations

import argparse
from typing import Any

from common.result import failure, normalize_tool_result


def _run_query_tool(
    operation: str,
    function_name: str,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        from query_ops import query_tool
    except Exception as exc:
        return failure(
            operation,
            "TOOL_NOT_AVAILABLE",
            "The Query Tool is not available.",
            f"{type(exc).__name__}: {exc}",
        )

    action = getattr(query_tool, function_name, None)

    if action is None or not callable(action):
        return failure(
            operation,
            "TOOL_NOT_AVAILABLE",
            f"The Query Tool operation `{function_name}` is not available.",
            {"function": function_name},
        )

    try:
        result = action(**kwargs)
    except Exception as exc:
        return failure(
            operation,
            "TOOL_EXECUTION_FAILED",
            "The Query Tool failed unexpectedly.",
            f"{type(exc).__name__}: {exc}",
        )

    return normalize_tool_result(operation, result)


def run_query_task_daily(args: argparse.Namespace) -> dict[str, Any]:
    return _run_query_tool(
        "query.task.daily",
        "task_daily",
        date=args.date,
        status=args.status,
        source=args.source,
        category=args.category,
        long_task_id=args.long_task_id,
        standing_task_id=args.standing_task_id,
        task_id=args.task_id,
        text=args.text,
        limit=args.limit,
    )


def run_query_task_long(args: argparse.Namespace) -> dict[str, Any]:
    return _run_query_tool(
        "query.task.long",
        "task_long",
        date=args.date,
        collection=args.collection,
        status=args.status,
        active=args.active_filter,
        category=args.category,
        stage=args.stage,
        deadline_state=args.deadline_state,
        task_id=args.task_id,
        text=args.text,
        limit=args.limit,
    )


def run_query_task_standing(args: argparse.Namespace) -> dict[str, Any]:
    return _run_query_tool(
        "query.task.standing",
        "task_standing",
        date=args.date,
        enabled=args.enabled_filter,
        category=args.category,
        schedule_type=args.schedule_type,
        long_task_id=args.long_task_id,
        scheduled=True if args.scheduled else None,
        due=True if args.due else None,
        task_id=args.task_id,
        text=args.text,
        limit=args.limit,
    )


def run_query_task_related(args: argparse.Namespace) -> dict[str, Any]:
    return _run_query_tool(
        "query.task.related",
        "task_related",
        task_id=args.task_id,
        date=args.date,
        limit=args.limit,
    )


def run_query_task_overview(args: argparse.Namespace) -> dict[str, Any]:
    return _run_query_tool(
        "query.task.overview",
        "task_overview",
        date=args.date,
    )


def run_query_character_current(args: argparse.Namespace) -> dict[str, Any]:
    return _run_query_tool(
        "query.character.current",
        "character_current",
    )


def _add_common_limit(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum returned items. Range: 1-200. Default: 50.",
    )


def _add_common_text_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--id",
        dest="task_id",
        help="Exact Task ID.",
    )
    parser.add_argument(
        "--text",
        help="Case-insensitive substring match over title and description.",
    )
    parser.add_argument(
        "--category",
        help="Exact category match.",
    )


def register_query_cli(modules: Any) -> argparse.ArgumentParser:
    """Register the complete public `query` command tree."""
    query_parser = modules.add_parser(
        "query",
        help="Fast read-only information queries.",
    )
    domains = query_parser.add_subparsers(
        dest="query_domain",
        metavar="<domain>",
    )

    task_parser = domains.add_parser(
        "task",
        help="Read-only Task queries.",
    )
    task_commands = task_parser.add_subparsers(
        dest="task_query",
        metavar="<query>",
    )

    daily = task_commands.add_parser(
        "daily",
        help="Query one Daily Task collection.",
    )
    daily.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD. Defaults to current MuseAI date.",
    )
    daily.add_argument(
        "--status",
        choices=["pending", "done"],
    )
    daily.add_argument(
        "--source",
        help="Exact Daily source match.",
    )
    daily.add_argument(
        "--long-task-id",
        help="Exact related Long Task ID.",
    )
    daily.add_argument(
        "--standing-task-id",
        help="Exact related Standing Task ID.",
    )
    _add_common_text_filters(daily)
    _add_common_limit(daily)
    daily.set_defaults(
        handler=run_query_task_daily,
        route_operation="query.task.daily",
        auto_log=True,
    )

    long_query = task_commands.add_parser(
        "long",
        help="Query Long Tasks.",
    )
    long_query.add_argument(
        "--date",
        help=(
            "Date used to derive deadline state. "
            "Defaults to current MuseAI date."
        ),
    )
    long_query.add_argument(
        "--collection",
        choices=["active", "archived", "all"],
        default="active",
        help="Long collection scope. Default: active.",
    )
    long_query.add_argument(
        "--status",
        choices=["pending", "done"],
    )
    active_group = long_query.add_mutually_exclusive_group()
    active_group.add_argument(
        "--active",
        dest="active_filter",
        action="store_const",
        const=True,
        default=None,
        help="Return only active Long Tasks.",
    )
    active_group.add_argument(
        "--inactive",
        dest="active_filter",
        action="store_const",
        const=False,
        help="Return only inactive Long Tasks.",
    )
    long_query.add_argument(
        "--stage",
        help="Exact Long stage match.",
    )
    long_query.add_argument(
        "--deadline-state",
        choices=[
            "none",
            "future",
            "due_today",
            "overdue",
            "completed",
        ],
        help="Derived deadline-state filter.",
    )
    _add_common_text_filters(long_query)
    _add_common_limit(long_query)
    long_query.set_defaults(
        handler=run_query_task_long,
        route_operation="query.task.long",
        auto_log=True,
    )

    standing = task_commands.add_parser(
        "standing",
        help="Query Standing Task recurrence rules.",
    )
    standing.add_argument(
        "--date",
        help=(
            "Date used to derive schedule/due state. "
            "Defaults to current MuseAI date."
        ),
    )
    enabled_group = standing.add_mutually_exclusive_group()
    enabled_group.add_argument(
        "--enabled",
        dest="enabled_filter",
        action="store_const",
        const=True,
        default=None,
        help="Return only enabled Standing rules.",
    )
    enabled_group.add_argument(
        "--disabled",
        dest="enabled_filter",
        action="store_const",
        const=False,
        help="Return only disabled Standing rules.",
    )
    standing.add_argument(
        "--schedule",
        dest="schedule_type",
        choices=["daily", "weekly", "monthly", "yearly"],
        help="Exact recurrence schedule type.",
    )
    standing.add_argument(
        "--long-task-id",
        help="Exact related Long Task ID.",
    )
    standing.add_argument(
        "--scheduled",
        action="store_true",
        help=(
            "Return only enabled rules whose recurrence pattern matches "
            "the target date, regardless of generation state."
        ),
    )
    standing.add_argument(
        "--due",
        action="store_true",
        help=(
            "Return only scheduled rules that have not yet generated "
            "their target-date Daily occurrence."
        ),
    )
    _add_common_text_filters(standing)
    _add_common_limit(standing)
    standing.set_defaults(
        handler=run_query_task_standing,
        route_operation="query.task.standing",
        auto_log=True,
    )

    related = task_commands.add_parser(
        "related",
        help="Resolve direct relationships for one exact Task ID.",
    )
    related.add_argument(
        "--id",
        dest="task_id",
        required=True,
        help="Exact Daily, Long, or Standing Task ID.",
    )
    related.add_argument(
        "--date",
        help=(
            "Date context for derived Long/Standing state. "
            "Defaults to current MuseAI date."
        ),
    )
    _add_common_limit(related)
    related.set_defaults(
        handler=run_query_task_related,
        route_operation="query.task.related",
        auto_log=True,
    )

    overview = task_commands.add_parser(
        "overview",
        help="Build a compact machine-fact Task overview.",
    )
    overview.add_argument(
        "--date",
        help="Overview date in YYYY-MM-DD. Defaults to current MuseAI date.",
    )
    overview.set_defaults(
        handler=run_query_task_overview,
        route_operation="query.task.overview",
        auto_log=True,
    )

    character_parser = domains.add_parser(
        "character",
        help="Read-only effective Character queries.",
    )
    character_commands = character_parser.add_subparsers(
        dest="character_query",
        metavar="<query>",
    )

    current = character_commands.add_parser(
        "current",
        help="Resolve the effective current Character configuration.",
    )
    current.set_defaults(
        handler=run_query_character_current,
        route_operation="query.character.current",
        # Character context may be resolved for ordinary user-facing replies.
        # Avoid turning that background read into one lifecycle log per turn.
        auto_log=False,
    )

    return query_parser
