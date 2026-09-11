#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI public Custom Function Tool.

Read / execute:
    function.list
    function.get
    function.run

Registry management:
    function.register
    function.update
    function.unregister
    function.enable
    function.disable

The Tool remains intentionally thin. User Function Packages remain outside
MuseAI ownership.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from common.result import success
from function_ops.custom_function_service import (
    disable_function as service_disable_function,
    enable_function as service_enable_function,
    get_function as service_get_function,
    list_functions as service_list_functions,
    register_function as service_register_function,
    run_function as service_run_function,
    unregister_function as service_unregister_function,
    update_function as service_update_function,
)
from function_ops.function_errors import map_function_exception


def _run(
    operation: str,
    action: Callable[..., tuple[dict[str, Any], list[str]]],
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        data, warnings = action(**kwargs)
    except Exception as exc:
        return map_function_exception(operation, exc)

    return success(
        operation,
        data,
        warnings,
    )


def list_functions(
    *,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "function.list",
        service_list_functions,
        manifest_path=manifest_path,
    )


def get_function(
    function_id: str,
    *,
    manifest_path: str | Path | None = None,
    func_root: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "function.get",
        service_get_function,
        function_id=function_id,
        manifest_path=manifest_path,
        func_root=func_root,
    )


def register_function(
    function_id: str,
    *,
    name: str,
    description: str,
    manifest_path: str | Path | None = None,
    func_root: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "function.register",
        service_register_function,
        function_id=function_id,
        name=name,
        description=description,
        manifest_path=manifest_path,
        func_root=func_root,
    )


def update_function(
    function_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "function.update",
        service_update_function,
        function_id=function_id,
        name=name,
        description=description,
        manifest_path=manifest_path,
    )


def unregister_function(
    function_id: str,
    *,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "function.unregister",
        service_unregister_function,
        function_id=function_id,
        manifest_path=manifest_path,
    )


def enable_function(
    function_id: str,
    *,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "function.enable",
        service_enable_function,
        function_id=function_id,
        manifest_path=manifest_path,
    )


def disable_function(
    function_id: str,
    *,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    return _run(
        "function.disable",
        service_disable_function,
        function_id=function_id,
        manifest_path=manifest_path,
    )


def run_function(
    function_id: str,
    *,
    runtime_args: list[str] | None = None,
    manifest_path: str | Path | None = None,
    func_root: str | Path | None = None,
    output_limit_bytes: int = 32 * 1024,
) -> dict[str, Any]:
    return _run(
        "function.run",
        service_run_function,
        function_id=function_id,
        runtime_args=runtime_args,
        manifest_path=manifest_path,
        func_root=func_root,
        output_limit_bytes=output_limit_bytes,
    )
