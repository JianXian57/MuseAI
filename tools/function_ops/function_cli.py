#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI Custom Function CLI adapter.

Public tree
-----------
python muse.py function list
python muse.py function get <function-id>
python muse.py function run <function-id>

python muse.py function register <function-id> --name "..." --description "..."
python muse.py function update <function-id> [--name "..."] [--description "..."]
python muse.py function unregister <function-id>
python muse.py function enable <function-id>
python muse.py function disable <function-id>

Custom Function discovery is user-driven. Registration always targets the
Function ID and semantic information explicitly supplied by the caller.
"""

from __future__ import annotations

import argparse
from typing import Any

from common.result import failure, normalize_tool_result


def _run_function_tool(
    operation: str,
    function_name: str,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        from function_ops import function_tool
    except Exception as exc:
        return failure(
            operation,
            "TOOL_NOT_AVAILABLE",
            "The Custom Function Tool is not available.",
            f"{type(exc).__name__}: {exc}",
        )

    action = getattr(function_tool, function_name, None)

    if action is None or not callable(action):
        return failure(
            operation,
            "TOOL_NOT_AVAILABLE",
            f"The Custom Function Tool operation `{function_name}` "
            "is not available.",
            {"function": function_name},
        )

    try:
        result = action(**kwargs)
    except Exception as exc:
        return failure(
            operation,
            "TOOL_EXECUTION_FAILED",
            "The Custom Function Tool failed unexpectedly.",
            f"{type(exc).__name__}: {exc}",
        )

    return normalize_tool_result(operation, result)


def run_function_list(args: argparse.Namespace) -> dict[str, Any]:
    return _run_function_tool(
        "function.list",
        "list_functions",
    )


def run_function_get(args: argparse.Namespace) -> dict[str, Any]:
    return _run_function_tool(
        "function.get",
        "get_function",
        function_id=args.function_id,
    )


def run_function_run(args: argparse.Namespace) -> dict[str, Any]:
    return _run_function_tool(
        "function.run",
        "run_function",
        function_id=args.function_id,
    )


def run_function_register(args: argparse.Namespace) -> dict[str, Any]:
    return _run_function_tool(
        "function.register",
        "register_function",
        function_id=args.function_id,
        name=args.name,
        description=args.description,
    )


def run_function_update(args: argparse.Namespace) -> dict[str, Any]:
    return _run_function_tool(
        "function.update",
        "update_function",
        function_id=args.function_id,
        name=args.name,
        description=args.description,
    )


def run_function_unregister(args: argparse.Namespace) -> dict[str, Any]:
    return _run_function_tool(
        "function.unregister",
        "unregister_function",
        function_id=args.function_id,
    )


def run_function_enable(args: argparse.Namespace) -> dict[str, Any]:
    return _run_function_tool(
        "function.enable",
        "enable_function",
        function_id=args.function_id,
    )


def run_function_disable(args: argparse.Namespace) -> dict[str, Any]:
    return _run_function_tool(
        "function.disable",
        "disable_function",
        function_id=args.function_id,
    )


def register_function_cli(modules: Any) -> argparse.ArgumentParser:
    """Register the complete public `function` command tree."""
    function_parser = modules.add_parser(
        "function",
        help="Run, inspect, and manage user-provided Custom Functions.",
    )
    commands = function_parser.add_subparsers(
        dest="function_command",
        metavar="<command>",
    )

    list_parser = commands.add_parser(
        "list",
        help="List registered Custom Functions.",
    )
    list_parser.set_defaults(
        handler=run_function_list,
        route_operation="function.list",
        auto_log=True,
    )

    get_parser = commands.add_parser(
        "get",
        help="Read one registered Custom Function and runtime config.",
    )
    get_parser.add_argument(
        "function_id",
        metavar="<function-id>",
        help="Registered Custom Function ID.",
    )
    get_parser.set_defaults(
        handler=run_function_get,
        route_operation="function.get",
        auto_log=True,
    )

    run_parser = commands.add_parser(
        "run",
        help="Execute one registered and enabled Custom Function.",
    )
    run_parser.add_argument(
        "function_id",
        metavar="<function-id>",
        help="Registered Custom Function ID.",
    )
    run_parser.set_defaults(
        handler=run_function_run,
        route_operation="function.run",
        auto_log=True,
    )

    register_parser = commands.add_parser(
        "register",
        help="Register an existing user-provided Function Package.",
    )
    register_parser.add_argument(
        "function_id",
        metavar="<function-id>",
        help="Function ID explicitly supplied by the user.",
    )
    register_parser.add_argument(
        "--name",
        required=True,
        help="User-provided display name.",
    )
    register_parser.add_argument(
        "--description",
        required=True,
        help="User-provided semantic description.",
    )
    register_parser.set_defaults(
        handler=run_function_register,
        route_operation="function.register",
        auto_log=True,
    )

    update_parser = commands.add_parser(
        "update",
        help="Update registered Function name and/or description.",
    )
    update_parser.add_argument(
        "function_id",
        metavar="<function-id>",
        help="Registered Custom Function ID.",
    )
    update_parser.add_argument(
        "--name",
        default=None,
        help="New user-provided display name.",
    )
    update_parser.add_argument(
        "--description",
        default=None,
        help="New user-provided semantic description.",
    )
    update_parser.set_defaults(
        handler=run_function_update,
        route_operation="function.update",
        auto_log=True,
    )

    unregister_parser = commands.add_parser(
        "unregister",
        help=(
            "Unregister a Function from MuseAI without deleting "
            "its Function Package."
        ),
    )
    unregister_parser.add_argument(
        "function_id",
        metavar="<function-id>",
        help="Registered Custom Function ID.",
    )
    unregister_parser.set_defaults(
        handler=run_function_unregister,
        route_operation="function.unregister",
        auto_log=True,
    )

    enable_parser = commands.add_parser(
        "enable",
        help="Enable a registered Custom Function.",
    )
    enable_parser.add_argument(
        "function_id",
        metavar="<function-id>",
        help="Registered Custom Function ID.",
    )
    enable_parser.set_defaults(
        handler=run_function_enable,
        route_operation="function.enable",
        auto_log=True,
    )

    disable_parser = commands.add_parser(
        "disable",
        help="Disable a registered Custom Function.",
    )
    disable_parser.add_argument(
        "function_id",
        metavar="<function-id>",
        help="Registered Custom Function ID.",
    )
    disable_parser.set_defaults(
        handler=run_function_disable,
        route_operation="function.disable",
        auto_log=True,
    )

    return function_parser
