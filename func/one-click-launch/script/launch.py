#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI One Click Launch.

Usage through Custom Function:
    .\\muse.cmd function run one-click-launch -- <group-id>

A group is read from:
    func/one-click-launch/config/groups/<group-id>.yaml

This program owns only deterministic launch behavior. It does not discover
launch groups, infer user intent, install applications, repair missing paths,
or retry failed launches.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import yaml


SCRIPT_PATH = Path(__file__).resolve()
FUNCTION_ROOT = SCRIPT_PATH.parents[1]
PROJECT_ROOT = SCRIPT_PATH.parents[3]
GROUPS_ROOT = FUNCTION_ROOT / "config" / "groups"
APPLICATIONS_CONFIG = PROJECT_ROOT / "config" / "applications.yaml"
TOOLS_ROOT = PROJECT_ROOT / "tools"

if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from common.applications_config import (  # noqa: E402
    ApplicationsConfigError,
    get_application,
)


SCHEMA_VERSION = "1.0"
GROUP_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SUPPORTED_LAUNCH_TYPES = {
    "browser",
    "terminal",
    "folder",
    "exe",
    "powershell",
    "windows_powershell",
    "cmd",
}
SUPPORTED_SHELLS = {
    "powershell": "pwsh.exe",
    "windows_powershell": "powershell.exe",
    "cmd": "cmd.exe",
}
CHROMIUM_EXECUTABLES = {
    "msedge.exe",
    "chrome.exe",
    "chromium.exe",
}
FIREFOX_EXECUTABLES = {"firefox.exe"}
START_GRACE_SECONDS = 0.20


class LaunchConfigError(RuntimeError):
    """Raised when a launch group is structurally invalid."""


class LaunchPreparationError(RuntimeError):
    """Raised when one launch unit cannot be prepared on this machine."""


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
            raise LaunchConfigError(
                f"{label} contains a non-string key: {key!r}"
            )


def _require_nonempty_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LaunchConfigError(f"{label} must be a non-empty string.")
    return value.strip()


def _optional_nonempty_string(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    return _require_nonempty_string(value, label=label)


def _validate_unknown_fields(
    mapping: dict[str, Any],
    *,
    allowed: set[str],
    label: str,
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise LaunchConfigError(
            f"{label} contains unsupported fields: {sorted(unknown)!r}"
        )


def _validate_http_url(value: Any, *, label: str) -> str:
    url = _require_nonempty_string(value, label=label)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LaunchConfigError(
            f"{label} must be an absolute http/https URL: {url!r}"
        )
    return url


def _validate_string_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list):
        raise LaunchConfigError(f"{label} must be a list.")

    result: list[str] = []
    for index, item in enumerate(value):
        result.append(
            _require_nonempty_string(
                item,
                label=f"{label}[{index}]",
            )
        )
    return result


def _validate_terminal_tab(
    raw: Any,
    *,
    launch_name: str,
    index: int,
) -> dict[str, Any]:
    label = f"Terminal launch `{launch_name}` tab[{index}]"

    if not isinstance(raw, dict):
        raise LaunchConfigError(f"{label} must be a mapping.")
    _require_string_keys(raw, label=label)
    _validate_unknown_fields(
        raw,
        allowed={"name", "shell", "cwd"},
        label=label,
    )

    shell = _require_nonempty_string(raw.get("shell"), label=f"{label}.shell")
    if shell not in SUPPORTED_SHELLS:
        raise LaunchConfigError(
            f"{label}.shell must be one of {sorted(SUPPORTED_SHELLS)!r}; "
            f"got {shell!r}."
        )

    return {
        "name": _optional_nonempty_string(
            raw.get("name"),
            label=f"{label}.name",
        ),
        "shell": shell,
        "cwd": _optional_nonempty_string(
            raw.get("cwd"),
            label=f"{label}.cwd",
        ),
    }


def _validate_launch(raw: Any, *, index: int) -> dict[str, Any]:
    label = f"launches[{index}]"

    if not isinstance(raw, dict):
        raise LaunchConfigError(f"{label} must be a mapping.")
    _require_string_keys(raw, label=label)

    name = _require_nonempty_string(raw.get("name"), label=f"{label}.name")
    launch_type = _require_nonempty_string(
        raw.get("type"),
        label=f"{label}.type",
    )

    if launch_type not in SUPPORTED_LAUNCH_TYPES:
        raise LaunchConfigError(
            f"{label}.type must be one of {sorted(SUPPORTED_LAUNCH_TYPES)!r}; "
            f"got {launch_type!r}."
        )

    if launch_type == "browser":
        _validate_unknown_fields(
            raw,
            allowed={"name", "type", "application", "tabs"},
            label=label,
        )
        application = _require_nonempty_string(
            raw.get("application"),
            label=f"{label}.application",
        )
        tabs_raw = raw.get("tabs")
        if not isinstance(tabs_raw, list) or not tabs_raw:
            raise LaunchConfigError(f"{label}.tabs must be a non-empty list.")
        tabs = [
            _validate_http_url(url, label=f"{label}.tabs[{tab_index}]")
            for tab_index, url in enumerate(tabs_raw)
        ]
        return {
            "name": name,
            "type": launch_type,
            "application": application,
            "tabs": tabs,
        }

    if launch_type == "terminal":
        _validate_unknown_fields(
            raw,
            allowed={"name", "type", "tabs"},
            label=label,
        )
        tabs_raw = raw.get("tabs")
        if not isinstance(tabs_raw, list) or not tabs_raw:
            raise LaunchConfigError(f"{label}.tabs must be a non-empty list.")
        tabs = [
            _validate_terminal_tab(tab, launch_name=name, index=tab_index)
            for tab_index, tab in enumerate(tabs_raw)
        ]
        return {
            "name": name,
            "type": launch_type,
            "tabs": tabs,
        }

    if launch_type == "folder":
        _validate_unknown_fields(
            raw,
            allowed={"name", "type", "target"},
            label=label,
        )
        return {
            "name": name,
            "type": launch_type,
            "target": _require_nonempty_string(
                raw.get("target"),
                label=f"{label}.target",
            ),
        }

    if launch_type == "exe":
        _validate_unknown_fields(
            raw,
            allowed={"name", "type", "target", "args", "cwd"},
            label=label,
        )
        return {
            "name": name,
            "type": launch_type,
            "target": _require_nonempty_string(
                raw.get("target"),
                label=f"{label}.target",
            ),
            "args": _validate_string_list(
                raw.get("args", []),
                label=f"{label}.args",
            ),
            "cwd": _optional_nonempty_string(
                raw.get("cwd"),
                label=f"{label}.cwd",
            ),
        }

    _validate_unknown_fields(
        raw,
        allowed={"name", "type", "cwd"},
        label=label,
    )
    return {
        "name": name,
        "type": launch_type,
        "cwd": _optional_nonempty_string(
            raw.get("cwd"),
            label=f"{label}.cwd",
        ),
    }


def validate_group_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise LaunchConfigError(
            "Launch group must contain a top-level mapping."
        )

    _require_string_keys(document, label="Launch group")
    _validate_unknown_fields(
        document,
        allowed={"schema_version", "name", "launches"},
        label="Launch group",
    )

    if document.get("schema_version") != SCHEMA_VERSION:
        raise LaunchConfigError(
            "Launch group `schema_version` must be "
            f"{SCHEMA_VERSION!r}; got {document.get('schema_version')!r}."
        )

    name = _require_nonempty_string(
        document.get("name"),
        label="Launch group.name",
    )

    launches_raw = document.get("launches")
    if not isinstance(launches_raw, list) or not launches_raw:
        raise LaunchConfigError(
            "Launch group `launches` must be a non-empty list."
        )

    launches = [
        _validate_launch(raw, index=index)
        for index, raw in enumerate(launches_raw)
    ]

    names = [item["name"] for item in launches]
    if len(set(names)) != len(names):
        raise LaunchConfigError(
            "Launch unit names must be unique within one group."
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "launches": launches,
    }


def resolve_group_path(
    group_id: str,
    *,
    groups_root: Path = GROUPS_ROOT,
) -> Path:
    if not isinstance(group_id, str) or not GROUP_ID_PATTERN.fullmatch(group_id):
        raise LaunchConfigError(
            "Group ID must match `[a-z0-9][a-z0-9._-]*`: "
            f"{group_id!r}"
        )
    return groups_root / f"{group_id}.yaml"


def load_group(
    group_id: str,
    *,
    groups_root: Path = GROUPS_ROOT,
) -> dict[str, Any]:
    path = resolve_group_path(group_id, groups_root=groups_root)

    if not path.exists():
        raise LaunchConfigError(f"Launch group not found: {path}")
    if not path.is_file():
        raise LaunchConfigError(f"Launch group path is not a file: {path}")

    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise LaunchConfigError(f"Could not read launch group: {path}") from exc

    try:
        document = yaml.load(text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise LaunchConfigError(
            f"Could not parse launch group: {path}: {exc}"
        ) from exc

    return validate_group_document(document)


def _resolve_user_path(value: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(value))
    path = Path(expanded)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _require_existing_directory(value: str, *, label: str) -> Path:
    path = _resolve_user_path(value)
    if not path.exists() or not path.is_dir():
        raise LaunchPreparationError(
            f"{label} directory does not exist: {path}"
        )
    return path


def _require_existing_file(value: str, *, label: str) -> Path:
    path = _resolve_user_path(value)
    if not path.exists() or not path.is_file():
        raise LaunchPreparationError(
            f"{label} file does not exist: {path}"
        )
    return path


def _find_command(command: str) -> str:
    resolved = shutil.which(command)
    if not resolved:
        raise LaunchPreparationError(
            f"Required command was not found: {command}"
        )
    return resolved


def _browser_argv(
    launch: dict[str, Any],
    *,
    applications_path: Path = APPLICATIONS_CONFIG,
) -> list[str]:
    try:
        app = get_application(
            launch["application"],
            expected_type="browser",
            config_path=applications_path,
        )
    except ApplicationsConfigError as exc:
        raise LaunchPreparationError(str(exc)) from exc

    executable = _require_existing_file(
        app["executable"],
        label=f"Browser `{launch['application']}` executable",
    )
    basename = executable.name.lower()
    tabs = launch["tabs"]

    if basename in CHROMIUM_EXECUTABLES:
        return [str(executable), "--new-window", *tabs]

    if basename in FIREFOX_EXECUTABLES:
        argv = [str(executable), "-new-window", tabs[0]]
        for url in tabs[1:]:
            argv.extend(["-new-tab", url])
        return argv

    raise LaunchPreparationError(
        "Grouped browser windows currently support Edge, Chrome, Chromium, "
        f"and Firefox executables; got {executable.name!r}."
    )


def _terminal_argv(launch: dict[str, Any]) -> list[str]:
    wt = _find_command("wt.exe")
    argv = [wt, "-w", "new"]

    for index, tab in enumerate(launch["tabs"]):
        if index:
            argv.append(";")

        argv.append("new-tab")

        if tab["name"]:
            argv.extend(["--title", tab["name"]])

        if tab["cwd"]:
            cwd = _require_existing_directory(
                tab["cwd"],
                label=f"Terminal tab `{tab['name'] or index}` cwd",
            )
            argv.extend(["-d", str(cwd)])

        shell_executable = _find_command(SUPPORTED_SHELLS[tab["shell"]])
        argv.append(shell_executable)

    return argv


def prepare_launch(
    launch: dict[str, Any],
    *,
    applications_path: Path = APPLICATIONS_CONFIG,
) -> tuple[list[str], str | None, bool, str]:
    """
    Prepare one launch unit.

    Returns:
        argv, cwd, new_console, detail
    """
    launch_type = launch["type"]

    if launch_type == "browser":
        argv = _browser_argv(launch, applications_path=applications_path)
        return argv, None, False, f"browser: {len(launch['tabs'])} tabs"

    if launch_type == "terminal":
        argv = _terminal_argv(launch)
        return argv, None, False, f"terminal: {len(launch['tabs'])} tabs"

    if launch_type == "folder":
        target = _require_existing_directory(
            launch["target"],
            label=f"Folder launch `{launch['name']}` target",
        )
        explorer = _find_command("explorer.exe")
        return [explorer, str(target)], None, False, "folder"

    if launch_type == "exe":
        executable = _require_existing_file(
            launch["target"],
            label=f"EXE launch `{launch['name']}` target",
        )
        cwd: str | None = None
        if launch["cwd"]:
            cwd = str(
                _require_existing_directory(
                    launch["cwd"],
                    label=f"EXE launch `{launch['name']}` cwd",
                )
            )
        return [str(executable), *launch["args"]], cwd, False, "application"

    cwd_path: Path | None = None
    if launch["cwd"]:
        cwd_path = _require_existing_directory(
            launch["cwd"],
            label=f"Shell launch `{launch['name']}` cwd",
        )

    if launch_type == "powershell":
        shell = _find_command("pwsh.exe")
        argv = [shell, "-NoExit"]
        if cwd_path is not None:
            argv.extend(["-WorkingDirectory", str(cwd_path)])
        return argv, None, True, "PowerShell 7"

    if launch_type == "windows_powershell":
        shell = _find_command("powershell.exe")
        argv = [shell, "-NoExit"]
        if cwd_path is not None:
            escaped = str(cwd_path).replace("'", "''")
            argv.extend(["-Command", f"Set-Location -LiteralPath '{escaped}'"])
        return argv, None, True, "Windows PowerShell"

    if launch_type == "cmd":
        shell = _find_command("cmd.exe")
        argv = [shell]
        if cwd_path is not None:
            argv.extend(["/K", f'cd /d "{cwd_path}"'])
        return argv, None, True, "Command Prompt"

    raise LaunchPreparationError(
        f"Unsupported launch type reached preparation: {launch_type!r}"
    )


def spawn_launch(
    argv: list[str],
    *,
    cwd: str | None,
    new_console: bool,
) -> tuple[bool, str]:
    creationflags = 0
    if new_console and os.name == "nt":
        creationflags |= subprocess.CREATE_NEW_CONSOLE

    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    except (OSError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {exc}"

    time.sleep(START_GRACE_SECONDS)
    exit_code = process.poll()

    if exit_code is None:
        return True, f"started pid={process.pid}"
    if exit_code == 0:
        return True, "dispatch accepted (process exited 0)"
    return False, f"process exited immediately with code {exit_code}"


def execute_group(
    group: dict[str, Any],
    *,
    applications_path: Path = APPLICATIONS_CONFIG,
    spawn: Callable[..., tuple[bool, str]] = spawn_launch,
) -> tuple[int, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []

    for launch in group["launches"]:
        try:
            argv, cwd, new_console, detail = prepare_launch(
                launch,
                applications_path=applications_path,
            )
        except LaunchPreparationError as exc:
            results.append(
                {
                    "name": launch["name"],
                    "type": launch["type"],
                    "ok": False,
                    "detail": str(exc),
                }
            )
            continue

        ok, process_detail = spawn(
            argv,
            cwd=cwd,
            new_console=new_console,
        )
        results.append(
            {
                "name": launch["name"],
                "type": launch["type"],
                "ok": ok,
                "detail": f"{detail}; {process_detail}" if process_detail else detail,
            }
        )

    failures = sum(1 for item in results if not item["ok"])
    return (0 if failures == 0 else 1), results


def print_summary(
    group_id: str,
    group: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    title = f"One Click Launch: {group['name']} ({group_id})"
    print(title)
    print("=" * len(title))

    for result in results:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"{status:<4}  {result['name']}")
        print(f"      {result['detail']}")

    succeeded = sum(1 for item in results if item["ok"])
    failed = len(results) - succeeded
    print("")
    print(f"{succeeded} succeeded, {failed} failed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch one named MuseAI One Click Launch group."
    )
    parser.add_argument(
        "group_id",
        metavar="<group-id>",
        help="Group ID matching config/groups/<group-id>.yaml.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if os.name != "nt":
        print("One Click Launch currently supports Windows only.", file=sys.stderr)
        return 2

    try:
        group = load_group(args.group_id)
    except LaunchConfigError as exc:
        print(f"Launch group config error: {exc}", file=sys.stderr)
        return 2

    exit_code, results = execute_group(group)
    print_summary(args.group_id, group, results)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
