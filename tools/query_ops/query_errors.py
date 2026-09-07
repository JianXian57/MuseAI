#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Shared Query errors and public error mapping for MuseAI.

Recommended location:
    MuseAI/tools/query_ops/query_errors.py
"""

from __future__ import annotations

from typing import Any

from common.result import failure
from common.time_service import TimeServiceError
from task_ops.task_read_service import InvalidTaskReadDateError
from task_ops.task_service import InvalidTaskIdError, TaskServiceError


class QueryServiceError(Exception):
    """Base exception for deterministic Query-service failures."""


class InvalidQueryFilterError(QueryServiceError):
    """A Query filter or option is invalid."""


class QueryTaskNotFoundError(QueryServiceError):
    """The exact Task requested by a relationship query was not found."""


class InvalidQueryDataError(QueryServiceError):
    """Validated source data cannot be represented by the Query contract."""


def map_query_exception(
    operation: str,
    exc: Exception,
) -> dict[str, Any]:
    """Map internal Query / Task / Time failures to stable Tool errors."""
    if isinstance(exc, InvalidQueryFilterError):
        return failure(
            operation,
            "QUERY_INVALID_FILTER",
            "The Query filter or option is invalid.",
            {
                "reason": str(exc),
                "exception": type(exc).__name__,
            },
        )

    if isinstance(exc, QueryTaskNotFoundError):
        return failure(
            operation,
            "QUERY_TASK_NOT_FOUND",
            "The requested Task could not be found for this Query.",
            {
                "reason": str(exc),
                "exception": type(exc).__name__,
            },
        )

    if isinstance(exc, InvalidTaskIdError):
        return failure(
            operation,
            "QUERY_INVALID_TASK_ID",
            "The Task ID is invalid for this Query.",
            {
                "reason": str(exc),
                "exception": type(exc).__name__,
            },
        )

    if isinstance(exc, InvalidTaskReadDateError):
        return failure(
            operation,
            "QUERY_INVALID_DATE",
            "The Query date is invalid.",
            {
                "reason": str(exc),
                "exception": type(exc).__name__,
            },
        )

    if isinstance(exc, TimeServiceError):
        return failure(
            operation,
            "QUERY_TIME_ERROR",
            "MuseAI time context could not be resolved for this Query.",
            {
                "reason": str(exc),
                "exception": type(exc).__name__,
            },
        )

    if isinstance(exc, TaskServiceError):
        return failure(
            operation,
            "QUERY_TASK_DATA_ERROR",
            "Task data could not be read for this Query.",
            {
                "reason": str(exc),
                "exception": type(exc).__name__,
            },
        )

    if isinstance(exc, QueryServiceError):
        return failure(
            operation,
            "QUERY_DATA_ERROR",
            "The Query could not be built from the available data.",
            {
                "reason": str(exc),
                "exception": type(exc).__name__,
            },
        )

    return failure(
        operation,
        "QUERY_UNEXPECTED_ERROR",
        "The Query Tool failed unexpectedly.",
        {
            "reason": str(exc),
            "exception": type(exc).__name__,
        },
    )
