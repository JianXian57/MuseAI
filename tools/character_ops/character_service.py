#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI Character deterministic runtime service.

Recommended location:
    MuseAI/tools/character_ops/character_service.py

Responsibilities
----------------
- Read Character user configuration from `config/user.yaml`.
- Resolve the selected Profile under `character/profiles/<profile-id>/`.
- Merge Profile defaults with user overrides.
- Validate optional Reaction manifest metadata and asset paths.
- Build one compact Effective Character snapshot for the read-only Query layer.

This Service is deterministic and read-only. It does not:
- choose how Main should emotionally react to a conversation;
- mutate Character configuration or Profile assets;
- render user-facing prose;
- scan other Profiles for fallback assets;
- enforce conversational cooldown state.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_USER_CONFIG = PROJECT_ROOT / "config" / "user.yaml"
DEFAULT_CHARACTER_ROOT = PROJECT_ROOT / "character"

SCHEMA_VERSION = "1.0"
PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
REACTION_ID_RE = PROFILE_ID_RE

STYLE_KEYS = (
    "warmth",
    "directness",
    "humor",
    "playfulness",
    "initiative",
    "empathy",
    "formality",
    "verbosity",
)

EXPRESSION_KEYS = (
    "emoji",
    "reaction",
    "teasing",
    "excitement",
)


class CharacterServiceError(Exception):
    """Base exception for deterministic Character runtime failures."""


class CharacterConfigError(CharacterServiceError):
    """`config/user.yaml` Character configuration is invalid."""


class CharacterProfileNotFoundError(CharacterServiceError):
    """The selected Character Profile does not exist or is incomplete."""


class CharacterProfileDataError(CharacterServiceError):
    """The selected Profile defaults are invalid."""


class CharacterManifestError(CharacterServiceError):
    """The selected Profile Reaction manifest is invalid."""


def _load_yaml_mapping(
    path: Path,
    *,
    missing_error: type[CharacterServiceError],
    invalid_error: type[CharacterServiceError],
    label: str,
) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise missing_error(f"{label} was not found: {path}")

    try:
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise invalid_error(f"Could not read {label}: {path}: {exc}") from exc

    try:
        value = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise invalid_error(f"Invalid YAML in {label}: {path}: {exc}") from exc

    if not isinstance(value, dict):
        raise invalid_error(f"{label} must contain a YAML mapping: {path}")

    return value


def _validate_profile_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CharacterConfigError("character.profile must be a non-empty string.")

    profile_id = value.strip()
    if PROFILE_ID_RE.fullmatch(profile_id) is None:
        raise CharacterConfigError(
            "character.profile must use only letters, numbers, `_`, or `-`, "
            "and must not contain path separators."
        )

    return profile_id


def _validate_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise CharacterConfigError(f"{label} must be true or false.")
    return value


def _validate_int_range(
    value: Any,
    *,
    label: str,
    minimum: int = 0,
    maximum: int = 100,
    error_type: type[CharacterServiceError] = CharacterConfigError,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise error_type(f"{label} must be an integer.")

    if value < minimum or value > maximum:
        raise error_type(
            f"{label} must be between {minimum} and {maximum}; got {value}."
        )

    return value


def _validate_numeric_group(
    value: Any,
    *,
    label: str,
    allowed_keys: tuple[str, ...],
    require_all: bool,
    error_type: type[CharacterServiceError],
) -> dict[str, int]:
    if value is None and not require_all:
        return {}

    if not isinstance(value, dict):
        raise error_type(f"{label} must be a YAML mapping.")

    unknown = sorted(set(value) - set(allowed_keys))
    if unknown:
        raise error_type(
            f"{label} contains unsupported fields: {', '.join(unknown)}."
        )

    if require_all:
        missing = [key for key in allowed_keys if key not in value]
        if missing:
            raise error_type(
                f"{label} is missing required fields: {', '.join(missing)}."
            )

    result: dict[str, int] = {}
    for key, item in value.items():
        result[key] = _validate_int_range(
            item,
            label=f"{label}.{key}",
            error_type=error_type,
        )

    return result


def _project_display_path(path: Path, *, project_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _safe_reaction_asset_path(
    reactions_dir: Path,
    raw_file: Any,
    *,
    reaction_id: str,
) -> tuple[str, Path]:
    if not isinstance(raw_file, str) or not raw_file.strip():
        raise CharacterManifestError(
            f"Reaction `{reaction_id}` field `file` must be a non-empty string."
        )

    file_value = raw_file.strip().replace("\\", "/")
    relative = Path(file_value)

    if relative.is_absolute():
        raise CharacterManifestError(
            f"Reaction `{reaction_id}` file must be relative to the reactions directory."
        )

    base = reactions_dir.resolve()
    candidate = (reactions_dir / relative).resolve()

    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise CharacterManifestError(
            f"Reaction `{reaction_id}` file escapes the reactions directory: {file_value}"
        ) from exc

    return relative.as_posix(), candidate


def _load_user_character_config(path: Path) -> dict[str, Any]:
    user = _load_yaml_mapping(
        path,
        missing_error=CharacterConfigError,
        invalid_error=CharacterConfigError,
        label="MuseAI user configuration",
    )

    raw_character = user.get("character")

    # Backward-compatible safe state for a legacy user.yaml that predates
    # Character. Missing Character config means Character is disabled.
    if raw_character is None:
        return {
            "enabled": False,
            "profile": "default",
            "overrides": {"style": {}, "expression": {}},
            "reaction": {"enabled": False, "cooldown_turns": 4},
        }

    if not isinstance(raw_character, dict):
        raise CharacterConfigError("character must be a YAML mapping.")

    enabled = _validate_bool(
        raw_character.get("enabled", False),
        label="character.enabled",
    )
    profile_id = _validate_profile_id(raw_character.get("profile", "default"))

    raw_overrides = raw_character.get("overrides", {})
    if raw_overrides is None:
        raw_overrides = {}
    if not isinstance(raw_overrides, dict):
        raise CharacterConfigError("character.overrides must be a YAML mapping.")

    unknown_override_groups = sorted(
        set(raw_overrides) - {"style", "expression"}
    )
    if unknown_override_groups:
        raise CharacterConfigError(
            "character.overrides contains unsupported groups: "
            + ", ".join(unknown_override_groups)
        )

    style_overrides = _validate_numeric_group(
        raw_overrides.get("style", {}),
        label="character.overrides.style",
        allowed_keys=STYLE_KEYS,
        require_all=False,
        error_type=CharacterConfigError,
    )
    expression_overrides = _validate_numeric_group(
        raw_overrides.get("expression", {}),
        label="character.overrides.expression",
        allowed_keys=EXPRESSION_KEYS,
        require_all=False,
        error_type=CharacterConfigError,
    )

    raw_reaction = raw_character.get("reaction", {})
    if raw_reaction is None:
        raw_reaction = {}
    if not isinstance(raw_reaction, dict):
        raise CharacterConfigError("character.reaction must be a YAML mapping.")

    unknown_reaction_fields = sorted(
        set(raw_reaction) - {"enabled", "cooldown_turns"}
    )
    if unknown_reaction_fields:
        raise CharacterConfigError(
            "character.reaction contains unsupported fields: "
            + ", ".join(unknown_reaction_fields)
        )

    reaction_enabled = _validate_bool(
        raw_reaction.get("enabled", False),
        label="character.reaction.enabled",
    )
    cooldown_turns = _validate_int_range(
        raw_reaction.get("cooldown_turns", 4),
        label="character.reaction.cooldown_turns",
        minimum=0,
        maximum=1000,
    )

    return {
        "enabled": enabled,
        "profile": profile_id,
        "overrides": {
            "style": style_overrides,
            "expression": expression_overrides,
        },
        "reaction": {
            "enabled": reaction_enabled,
            "cooldown_turns": cooldown_turns,
        },
    }


def _load_profile_defaults(
    path: Path,
    *,
    profile_id: str,
) -> tuple[dict[str, int], dict[str, int]]:
    defaults = _load_yaml_mapping(
        path,
        missing_error=CharacterProfileNotFoundError,
        invalid_error=CharacterProfileDataError,
        label=f"Character Profile `{profile_id}` defaults",
    )

    if defaults.get("schema_version") != SCHEMA_VERSION:
        raise CharacterProfileDataError(
            f"Profile `{profile_id}` defaults must use schema_version "
            f"{SCHEMA_VERSION!r}."
        )

    if defaults.get("profile") != profile_id:
        raise CharacterProfileDataError(
            f"Profile defaults identity mismatch: expected `{profile_id}`, "
            f"got {defaults.get('profile')!r}."
        )

    style = _validate_numeric_group(
        defaults.get("style"),
        label=f"profile `{profile_id}` style",
        allowed_keys=STYLE_KEYS,
        require_all=True,
        error_type=CharacterProfileDataError,
    )
    expression = _validate_numeric_group(
        defaults.get("expression"),
        label=f"profile `{profile_id}` expression",
        allowed_keys=EXPRESSION_KEYS,
        require_all=True,
        error_type=CharacterProfileDataError,
    )

    return style, expression


def _load_reaction_manifest(
    manifest_path: Path,
    *,
    profile_id: str,
    project_root: Path,
) -> tuple[dict[str, Any], list[str]]:
    if not manifest_path.exists():
        return {
            "supported": False,
            "manifest_path": None,
            "available_count": 0,
            "missing_count": 0,
            "reactions": {},
        }, []

    manifest = _load_yaml_mapping(
        manifest_path,
        missing_error=CharacterManifestError,
        invalid_error=CharacterManifestError,
        label=f"Character Profile `{profile_id}` Reaction manifest",
    )

    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise CharacterManifestError(
            f"Reaction manifest for `{profile_id}` must use schema_version "
            f"{SCHEMA_VERSION!r}."
        )

    if manifest.get("profile") != profile_id:
        raise CharacterManifestError(
            f"Reaction manifest identity mismatch: expected `{profile_id}`, "
            f"got {manifest.get('profile')!r}."
        )

    raw_reactions = manifest.get("reactions")
    if not isinstance(raw_reactions, dict):
        raise CharacterManifestError("Reaction manifest `reactions` must be a mapping.")

    reactions_dir = manifest_path.parent
    output: dict[str, Any] = {}
    warnings: list[str] = []
    available_count = 0
    missing_count = 0

    for reaction_id, raw in raw_reactions.items():
        if not isinstance(reaction_id, str) or REACTION_ID_RE.fullmatch(reaction_id) is None:
            raise CharacterManifestError(
                f"Invalid Reaction ID {reaction_id!r}; use letters, numbers, `_`, or `-`."
            )

        if not isinstance(raw, dict):
            raise CharacterManifestError(
                f"Reaction `{reaction_id}` must be a YAML mapping."
            )

        required_fields = {"name", "file", "description", "intensity"}
        missing_fields = sorted(required_fields - set(raw))
        if missing_fields:
            raise CharacterManifestError(
                f"Reaction `{reaction_id}` is missing fields: "
                + ", ".join(missing_fields)
            )

        name = raw.get("name")
        description = raw.get("description")
        if not isinstance(name, str) or not name.strip():
            raise CharacterManifestError(
                f"Reaction `{reaction_id}` field `name` must be a non-empty string."
            )
        if not isinstance(description, str) or not description.strip():
            raise CharacterManifestError(
                f"Reaction `{reaction_id}` field `description` must be a non-empty string."
            )

        intensity = _validate_int_range(
            raw.get("intensity"),
            label=f"reaction `{reaction_id}` intensity",
            error_type=CharacterManifestError,
        )
        file_value, asset_path = _safe_reaction_asset_path(
            reactions_dir,
            raw.get("file"),
            reaction_id=reaction_id,
        )

        available = asset_path.exists() and asset_path.is_file()
        if available:
            available_count += 1
            uri: str | None = asset_path.as_uri()
        else:
            missing_count += 1
            uri = None
            warnings.append(
                "CHARACTER_REACTION_ASSET_MISSING: "
                f"{reaction_id} -> {file_value}"
            )

        output[reaction_id] = {
            "name": name.strip(),
            "file": file_value,
            "description": description.strip(),
            "intensity": intensity,
            "available": available,
            "asset_path": _project_display_path(
                asset_path,
                project_root=project_root,
            ),
            "uri": uri,
        }

    return {
        "supported": True,
        "manifest_path": _project_display_path(
            manifest_path,
            project_root=project_root,
        ),
        "available_count": available_count,
        "missing_count": missing_count,
        "reactions": output,
    }, warnings


def resolve_current_character(
    *,
    user_config_path: str | Path | None = None,
    character_root: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Resolve MuseAI's effective current Character snapshot.

    Returns
    -------
    (data, warnings)
        Compact deterministic Character data for the Query layer.
    """
    user_path = (
        Path(user_config_path).expanduser()
        if user_config_path is not None
        else DEFAULT_USER_CONFIG
    )
    char_root = (
        Path(character_root).expanduser()
        if character_root is not None
        else DEFAULT_CHARACTER_ROOT
    )

    project_root = char_root.resolve().parent
    user_config = _load_user_character_config(user_path)

    enabled = user_config["enabled"]
    profile_id = user_config["profile"]
    configured_reaction_enabled = user_config["reaction"]["enabled"]
    cooldown_turns = user_config["reaction"]["cooldown_turns"]

    if not enabled:
        return {
            "enabled": False,
            "profile": profile_id,
            "profile_path": None,
            "defaults_path": None,
            "style": {},
            "expression": {},
            "reaction": {
                "supported": False,
                "configured_enabled": configured_reaction_enabled,
                "enabled": False,
                "cooldown_turns": cooldown_turns,
                "manifest_path": None,
                "available_count": 0,
                "missing_count": 0,
                "reactions": {},
            },
        }, []

    profile_root = char_root / "profiles" / profile_id
    profile_path = profile_root / "profile.md"
    defaults_path = profile_root / "defaults.yaml"

    if not profile_path.exists() or not profile_path.is_file():
        raise CharacterProfileNotFoundError(
            f"Character Profile `{profile_id}` profile.md was not found: {profile_path}"
        )

    default_style, default_expression = _load_profile_defaults(
        defaults_path,
        profile_id=profile_id,
    )

    style = dict(default_style)
    style.update(user_config["overrides"]["style"])

    expression = dict(default_expression)
    expression.update(user_config["overrides"]["expression"])

    manifest_data, warnings = _load_reaction_manifest(
        profile_root / "reactions" / "manifest.yaml",
        profile_id=profile_id,
        project_root=project_root,
    )

    supported = bool(manifest_data["supported"])
    available_count = int(manifest_data["available_count"])
    reaction_enabled = bool(
        configured_reaction_enabled
        and supported
        and expression["reaction"] > 0
        and available_count > 0
    )

    reaction = {
        "supported": supported,
        "configured_enabled": configured_reaction_enabled,
        "enabled": reaction_enabled,
        "cooldown_turns": cooldown_turns,
        "manifest_path": manifest_data["manifest_path"],
        "available_count": available_count,
        "missing_count": manifest_data["missing_count"],
        "reactions": manifest_data["reactions"],
    }

    return {
        "enabled": True,
        "profile": profile_id,
        "profile_path": _project_display_path(
            profile_path,
            project_root=project_root,
        ),
        "defaults_path": _project_display_path(
            defaults_path,
            project_root=project_root,
        ),
        "style": style,
        "expression": expression,
        "reaction": reaction,
    }, warnings
