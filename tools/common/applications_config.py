#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI machine-local application configuration reader.

Ownership:
- config/applications.yaml
    Machine-local application bindings. Read-only here.
- config/applications.example.yaml
    Repository-tracked example.

This module does not scan the OS, guess paths, install applications, or
modify configuration.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_APPLICATIONS_CONFIG = PROJECT_ROOT / "config" / "applications.yaml"

SCHEMA_VERSION = "1.0"
APPLICATION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SUPPORTED_TYPES = {"browser", "application"}


class ApplicationsConfigError(RuntimeError):
    """Base error for application configuration problems."""


class ApplicationsConfigNotFoundError(ApplicationsConfigError):
    """Raised when the machine-local configuration is missing."""


class ApplicationsConfigInvalidError(ApplicationsConfigError):
    """Raised when the configuration is malformed or unsupported."""


class ApplicationNotFoundError(ApplicationsConfigError):
    """Raised when a requested application ID is not configured."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: yaml.SafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}

    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)

        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc

        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key: {key!r}",
                key_node.start_mark,
            )

        mapping[key] = loader.construct_object(value_node, deep=deep)

    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _require_string_keys(mapping: dict[Any, Any], *, label: str) -> None:
    for key in mapping:
        if not isinstance(key, str):
            raise ApplicationsConfigInvalidError(
                f"{label} contains a non-string key: {key!r}"
            )


def _resolve_config_path(config_path: str | Path | None) -> Path:
    if config_path is None:
        return DEFAULT_APPLICATIONS_CONFIG
    return Path(config_path).expanduser().resolve()


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ApplicationsConfigNotFoundError(
            f"Applications config not found: {path}"
        )

    if not path.is_file():
        raise ApplicationsConfigInvalidError(
            f"Applications config path is not a file: {path}"
        )

    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ApplicationsConfigInvalidError(
            f"Could not read applications config: {path}"
        ) from exc

    try:
        document = yaml.load(text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ApplicationsConfigInvalidError(
            f"Could not parse applications config: {path}: {exc}"
        ) from exc

    if not isinstance(document, dict):
        raise ApplicationsConfigInvalidError(
            "Applications config must contain a top-level mapping."
        )

    _require_string_keys(document, label="Applications config")
    return document


def _validate_application(
    application_id: Any,
    raw_entry: Any,
) -> dict[str, str]:
    if (
        not isinstance(application_id, str)
        or not APPLICATION_ID_PATTERN.fullmatch(application_id)
    ):
        raise ApplicationsConfigInvalidError(
            "Application ID must match `[a-z0-9][a-z0-9._-]*`: "
            f"{application_id!r}"
        )

    if not isinstance(raw_entry, dict):
        raise ApplicationsConfigInvalidError(
            f"Application `{application_id}` must be a mapping."
        )

    _require_string_keys(raw_entry, label=f"Application `{application_id}`")

    allowed = {"type", "executable"}
    unknown = set(raw_entry) - allowed
    if unknown:
        raise ApplicationsConfigInvalidError(
            f"Application `{application_id}` contains unsupported fields: "
            f"{sorted(unknown)!r}"
        )

    app_type = raw_entry.get("type")
    if not isinstance(app_type, str) or app_type not in SUPPORTED_TYPES:
        raise ApplicationsConfigInvalidError(
            f"Application `{application_id}` type must be one of "
            f"{sorted(SUPPORTED_TYPES)!r}; got {app_type!r}."
        )

    executable = raw_entry.get("executable")
    if not isinstance(executable, str) or not executable.strip():
        raise ApplicationsConfigInvalidError(
            f"Application `{application_id}` requires a non-empty "
            "`executable` string."
        )

    return {
        "id": application_id,
        "type": app_type,
        "executable": executable.strip(),
    }


def load_applications_config(
    config_path: str | Path | None = None,
) -> dict[str, dict[str, str]]:
    """
    Load and validate the machine-local application registry.

    Returns a new mapping keyed by application ID.
    """
    path = _resolve_config_path(config_path)
    document = _load_yaml_mapping(path)

    if document.get("schema_version") != SCHEMA_VERSION:
        raise ApplicationsConfigInvalidError(
            "Applications config `schema_version` must be "
            f"{SCHEMA_VERSION!r}; got {document.get('schema_version')!r}."
        )

    allowed_top_level = {"schema_version", "applications"}
    unknown = set(document) - allowed_top_level
    if unknown:
        raise ApplicationsConfigInvalidError(
            "Applications config contains unsupported top-level fields: "
            f"{sorted(unknown)!r}"
        )

    raw_applications = document.get("applications")
    if not isinstance(raw_applications, dict):
        raise ApplicationsConfigInvalidError(
            "Applications config `applications` must be a mapping."
        )

    _require_string_keys(
        raw_applications,
        label="Applications config `applications`",
    )

    applications: dict[str, dict[str, str]] = {}
    for application_id, raw_entry in raw_applications.items():
        entry = _validate_application(application_id, raw_entry)
        applications[application_id] = entry

    return applications


def get_application(
    application_id: str,
    *,
    expected_type: str | None = None,
    config_path: str | Path | None = None,
) -> dict[str, str]:
    """
    Resolve one configured application by ID.

    `expected_type` optionally enforces the caller's required application type.
    """
    if (
        not isinstance(application_id, str)
        or not APPLICATION_ID_PATTERN.fullmatch(application_id)
    ):
        raise ApplicationsConfigInvalidError(
            "Application ID must match `[a-z0-9][a-z0-9._-]*`: "
            f"{application_id!r}"
        )

    if expected_type is not None and expected_type not in SUPPORTED_TYPES:
        raise ApplicationsConfigInvalidError(
            f"Unsupported expected application type: {expected_type!r}"
        )

    applications = load_applications_config(config_path)

    try:
        entry = applications[application_id]
    except KeyError as exc:
        raise ApplicationNotFoundError(
            f"Application `{application_id}` is not configured."
        ) from exc

    if expected_type is not None and entry["type"] != expected_type:
        raise ApplicationsConfigInvalidError(
            f"Application `{application_id}` has type {entry['type']!r}; "
            f"expected {expected_type!r}."
        )

    return dict(entry)
