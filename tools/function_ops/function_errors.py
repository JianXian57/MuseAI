#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI Custom Function errors and public Tool-error mapping.

Custom Function wraps user-provided scripts/programs. The runtime reports
registry/config/invocation/process failures but does not diagnose, repair,
retry, or modify the called Function implementation.
"""

from __future__ import annotations

from typing import Any

from common.result import failure


class FunctionServiceError(Exception):
    """Base exception for deterministic Custom Function failures."""


class FunctionManifestError(FunctionServiceError):
    """The central Custom Function manifest is missing or invalid."""


class FunctionRegistryWriteError(FunctionServiceError):
    """MuseAI could not persist a registry change to the manifest."""


class FunctionConfigError(FunctionServiceError):
    """One Function has an invalid runtime package/configuration."""


class FunctionNotFoundError(FunctionServiceError):
    """The requested Function ID is not registered in the manifest."""


class FunctionAlreadyRegisteredError(FunctionServiceError):
    """The requested Function ID is already registered."""


class FunctionPackageNotFoundError(FunctionServiceError):
    """The explicitly requested Function Package does not exist."""


class FunctionDisabledError(FunctionServiceError):
    """The requested Function is registered but disabled."""


class FunctionCommandNotFoundError(FunctionServiceError):
    """The configured process command could not be found."""


class FunctionStartError(FunctionServiceError):
    """The configured process could not be started."""


class FunctionProcessError(FunctionServiceError):
    """The configured process ran and exited with a non-zero exit code."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any],
    ) -> None:
        super().__init__(message)
        self.details = details


class FunctionTimeoutError(FunctionServiceError):
    """The configured process exceeded its explicit timeout."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any],
    ) -> None:
        super().__init__(message)
        self.details = details


def _reason_details(exc: Exception) -> dict[str, Any]:
    return {
        "reason": str(exc),
        "exception": type(exc).__name__,
    }


def map_function_exception(
    operation: str,
    exc: Exception,
) -> dict[str, Any]:
    """Map internal Function failures to stable MuseAI Tool errors."""
    if isinstance(exc, FunctionAlreadyRegisteredError):
        return failure(
            operation,
            "FUNCTION_ALREADY_REGISTERED",
            "The requested Custom Function is already registered.",
            _reason_details(exc),
        )

    if isinstance(exc, FunctionNotFoundError):
        return failure(
            operation,
            "FUNCTION_NOT_FOUND",
            "The requested Custom Function is not registered.",
            _reason_details(exc),
        )

    if isinstance(exc, FunctionPackageNotFoundError):
        return failure(
            operation,
            "FUNCTION_PACKAGE_NOT_FOUND",
            "The requested Custom Function Package does not exist.",
            _reason_details(exc),
        )

    if isinstance(exc, FunctionDisabledError):
        return failure(
            operation,
            "FUNCTION_DISABLED",
            "The requested Custom Function is disabled.",
            _reason_details(exc),
        )

    if isinstance(exc, FunctionRegistryWriteError):
        return failure(
            operation,
            "FUNCTION_REGISTRY_WRITE_FAILED",
            "MuseAI could not persist the Custom Function registry change.",
            _reason_details(exc),
        )

    if isinstance(exc, (FunctionManifestError, FunctionConfigError)):
        return failure(
            operation,
            "FUNCTION_INVALID_CONFIG",
            "The Custom Function configuration is invalid.",
            _reason_details(exc),
        )

    if isinstance(exc, FunctionCommandNotFoundError):
        return failure(
            operation,
            "FUNCTION_COMMAND_NOT_FOUND",
            "The configured Custom Function command could not be found.",
            _reason_details(exc),
        )

    if isinstance(exc, FunctionStartError):
        return failure(
            operation,
            "FUNCTION_START_FAILED",
            "The Custom Function process could not be started.",
            _reason_details(exc),
        )

    if isinstance(exc, FunctionProcessError):
        return failure(
            operation,
            "FUNCTION_PROCESS_FAILED",
            "The Custom Function process exited with a non-zero code.",
            exc.details,
        )

    if isinstance(exc, FunctionTimeoutError):
        return failure(
            operation,
            "FUNCTION_TIMEOUT",
            "The Custom Function process exceeded its configured timeout.",
            exc.details,
        )

    return failure(
        operation,
        "FUNCTION_UNEXPECTED_ERROR",
        "The Custom Function runtime failed unexpectedly.",
        _reason_details(exc),
    )
