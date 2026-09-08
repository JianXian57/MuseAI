#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MuseAI internal Custom Function runtime and registry service.

V2 responsibility
-----------------
Runtime:
- Read the Function catalog from:
      <project-root>/config/manifest.yaml
- Read one Function runtime configuration from:
      <project-root>/func/<function-id>/config/function.yaml
- Expose deterministic list/get/run service operations.
- Start the configured process with shell=False.
- Capture exit code, stdout, and stderr.
- Report non-zero process exits and explicit timeouts upward.

Registry management:
- Register an existing user-provided Function Package.
- Update registered semantic information.
- Enable or disable a registered Function.
- Unregister a Function from MuseAI without deleting its package.
- Persist manifest changes atomically.

Ownership boundary
------------------
<project-root>/config/manifest.yaml
    MuseAI-owned registry state:
    id / name / description / enabled

<project-root>/func/<function-id>/
    User-owned Function Package:
    config / data / script

Custom Function discovery is user-driven, not filesystem-driven.
This service never scans func/ to guess or auto-register Functions.

This service does NOT:
- diagnose or repair user scripts;
- create or delete user Function Packages;
- modify Function script/data content;
- install dependencies;
- retry failed scripts;
- infer script types;
- infer Function names or descriptions;
- interpret script-specific business semantics.
"""

from __future__ import annotations

import locale
import math
import os
import re
import signal
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

import yaml

from function_ops.function_errors import (
    FunctionAlreadyRegisteredError,
    FunctionCommandNotFoundError,
    FunctionConfigError,
    FunctionDisabledError,
    FunctionManifestError,
    FunctionNotFoundError,
    FunctionPackageNotFoundError,
    FunctionProcessError,
    FunctionRegistryWriteError,
    FunctionStartError,
    FunctionTimeoutError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "config" / "manifest.yaml"
DEFAULT_FUNC_ROOT = PROJECT_ROOT / "func"

SCHEMA_VERSION = "1.0"
FUNCTION_CONFIG_RELATIVE_PATH = Path("config") / "function.yaml"
FUNCTION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# Process output is drained continuously, while only a bounded prefix is retained.
DEFAULT_OUTPUT_LIMIT_BYTES = 32 * 1024
OUTPUT_DRAIN_GRACE_SECONDS = 0.5
OUTPUT_CANCEL_GRACE_SECONDS = 0.25
OUTPUT_POLL_INTERVAL_SECONDS = 0.05
PROCESS_TERMINATION_GRACE_SECONDS = 1.0


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


def _resolve_path(
    value: str | Path | None,
    *,
    default: Path,
) -> Path:
    if value is None:
        return default

    return Path(value).expanduser().resolve()


def _resolve_manifest_path(
    manifest_path: str | Path | None = None,
) -> Path:
    return _resolve_path(
        manifest_path,
        default=DEFAULT_MANIFEST_PATH,
    )


def _resolve_func_root(
    func_root: str | Path | None = None,
) -> Path:
    return _resolve_path(
        func_root,
        default=DEFAULT_FUNC_ROOT,
    )


def _load_yaml_mapping(
    path: Path,
    *,
    label: str,
    error_type: type[FunctionManifestError] | type[FunctionConfigError],
) -> dict[str, Any]:
    if not path.exists():
        raise error_type(f"{label} not found: {path}")

    if not path.is_file():
        raise error_type(f"{label} path is not a file: {path}")

    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise error_type(f"Could not read {label}: {path}") from exc

    try:
        document = yaml.load(text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise error_type(f"Could not parse {label}: {path}: {exc}") from exc

    if not isinstance(document, dict):
        raise error_type(f"{label} must contain a top-level mapping: {path}")

    return document


def _validate_schema_version(
    document: dict[str, Any],
    *,
    label: str,
    error_type: type[FunctionManifestError] | type[FunctionConfigError],
) -> None:
    version = document.get("schema_version")

    if version != SCHEMA_VERSION:
        raise error_type(
            f"{label} schema_version must be {SCHEMA_VERSION!r}; "
            f"got {version!r}."
        )


def _validate_function_id(
    function_id: Any,
    *,
    error_type: type[FunctionManifestError]
    | type[FunctionConfigError]
    | type[FunctionNotFoundError]
    | type[FunctionPackageNotFoundError],
) -> str:
    if not isinstance(function_id, str) or not FUNCTION_ID_PATTERN.fullmatch(
        function_id
    ):
        raise error_type(
            "Function ID must match "
            "`[a-z0-9][a-z0-9._-]*`: "
            f"{function_id!r}"
        )

    return function_id


def _normalize_semantic_text(
    value: Any,
    *,
    field: str,
    function_id: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FunctionManifestError(
            f"Function `{function_id}` requires a non-empty `{field}`."
        )

    return value.strip()


def _validate_catalog_entry(
    function_id: str,
    entry: Any,
) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise FunctionManifestError(
            f"Manifest entry `{function_id}` must be a mapping."
        )

    allowed = {"name", "description", "enabled"}
    unknown = set(entry) - allowed

    if unknown:
        raise FunctionManifestError(
            f"Manifest entry `{function_id}` contains unsupported fields: "
            f"{sorted(unknown)!r}"
        )

    name = _normalize_semantic_text(
        entry.get("name"),
        field="name",
        function_id=function_id,
    )
    description = _normalize_semantic_text(
        entry.get("description"),
        field="description",
        function_id=function_id,
    )
    enabled = entry.get("enabled")

    if not isinstance(enabled, bool):
        raise FunctionManifestError(
            f"Manifest entry `{function_id}` requires boolean `enabled`."
        )

    return {
        "id": function_id,
        "name": name,
        "description": description,
        "enabled": enabled,
    }


def _validate_manifest_document(
    document: dict[str, Any],
) -> list[dict[str, Any]]:
    _validate_schema_version(
        document,
        label="Function manifest",
        error_type=FunctionManifestError,
    )

    allowed_top_level = {"schema_version", "functions"}
    unknown = set(document) - allowed_top_level

    if unknown:
        raise FunctionManifestError(
            "Function manifest contains unsupported top-level fields: "
            f"{sorted(unknown)!r}"
        )

    functions = document.get("functions")

    if not isinstance(functions, dict):
        raise FunctionManifestError(
            "Function manifest `functions` must be a mapping."
        )

    entries: list[dict[str, Any]] = []

    for raw_id, raw_entry in functions.items():
        function_id = _validate_function_id(
            raw_id,
            error_type=FunctionManifestError,
        )
        entries.append(_validate_catalog_entry(function_id, raw_entry))

    return entries


def _read_manifest_document(
    manifest_path: str | Path | None = None,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    path = _resolve_manifest_path(manifest_path)
    document = _load_yaml_mapping(
        path,
        label="Function manifest",
        error_type=FunctionManifestError,
    )
    entries = _validate_manifest_document(document)
    return path, document, entries


def _read_manifest(
    manifest_path: str | Path | None = None,
) -> tuple[Path, list[dict[str, Any]]]:
    path, _, entries = _read_manifest_document(manifest_path)
    return path, entries


def _catalog_by_id(
    manifest_path: str | Path | None = None,
) -> tuple[Path, dict[str, dict[str, Any]]]:
    path, entries = _read_manifest(manifest_path)

    return (
        path,
        {entry["id"]: entry for entry in entries},
    )


def _get_registered_entry(
    function_id: str,
    *,
    manifest_path: str | Path | None,
) -> tuple[Path, dict[str, Any]]:
    _validate_function_id(
        function_id,
        error_type=FunctionNotFoundError,
    )

    manifest, catalog = _catalog_by_id(manifest_path)
    entry = catalog.get(function_id)

    if entry is None:
        raise FunctionNotFoundError(
            f"Function `{function_id}` is not present in {manifest}."
        )

    return manifest, entry


def _manifest_entry_document(
    *,
    name: str,
    description: str,
    enabled: bool,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "enabled": enabled,
    }


def _write_manifest_atomic(
    path: Path,
    document: dict[str, Any],
) -> None:
    """
    Atomically replace the manifest in the same directory.

    The manifest is MuseAI-owned registry state. YAML comments/formatting are
    not part of the persistence contract; semantic mapping order is preserved.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FunctionRegistryWriteError(
            f"Could not prepare manifest directory: {path.parent}"
        ) from exc

    try:
        serialized = yaml.safe_dump(
            document,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    except yaml.YAMLError as exc:
        raise FunctionRegistryWriteError(
            "Could not serialize the Function manifest."
        ) from exc

    temp_path: Path | None = None

    try:
        fd, raw_temp_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temp_path = Path(raw_temp_path)

        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, path)
        temp_path = None

    except OSError as exc:
        raise FunctionRegistryWriteError(
            f"Could not atomically write Function manifest: {path}"
        ) from exc

    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _normalize_timeout(
    value: Any,
    *,
    function_id: str,
) -> float | None:
    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FunctionConfigError(
            f"Function `{function_id}` process.timeout_seconds must be "
            "a finite positive number or null."
        )

    try:
        timeout = float(value)
    except (OverflowError, ValueError) as exc:
        raise FunctionConfigError(
            f"Function `{function_id}` process.timeout_seconds must be "
            "a finite positive number or null."
        ) from exc

    if not math.isfinite(timeout) or timeout <= 0:
        raise FunctionConfigError(
            f"Function `{function_id}` process.timeout_seconds must be "
            "a finite positive number when configured."
        )

    return timeout


def _is_path_like_command(command: str) -> bool:
    path = Path(command)

    return (
        path.is_absolute()
        or "/" in command
        or "\\" in command
        or command.startswith(".")
    )


def _resolve_command(
    command: str,
    *,
    function_root: Path,
) -> str:
    if not _is_path_like_command(command):
        # Plain executable names are intentionally resolved through PATH.
        return command

    path = Path(command).expanduser()

    if not path.is_absolute():
        path = function_root / path

    return str(path.resolve())


def _read_runtime_config(
    function_id: str,
    *,
    catalog_entry: dict[str, Any],
    func_root: str | Path | None = None,
) -> dict[str, Any]:
    root = _resolve_func_root(func_root)
    function_root = (root / function_id).resolve()

    if not function_root.exists() or not function_root.is_dir():
        raise FunctionPackageNotFoundError(
            f"Function Package `{function_id}` directory not found: "
            f"{function_root}"
        )

    config_path = function_root / FUNCTION_CONFIG_RELATIVE_PATH
    document = _load_yaml_mapping(
        config_path,
        label=f"Function `{function_id}` config",
        error_type=FunctionConfigError,
    )
    _validate_schema_version(
        document,
        label=f"Function `{function_id}` config",
        error_type=FunctionConfigError,
    )

    # enabled is intentionally NOT accepted here in V2.
    # MuseAI management state belongs only to config/manifest.yaml.
    allowed_top_level = {"schema_version", "process"}
    unknown = set(document) - allowed_top_level

    if unknown:
        raise FunctionConfigError(
            f"Function `{function_id}` config contains unsupported fields: "
            f"{sorted(unknown)!r}"
        )

    process = document.get("process")

    if not isinstance(process, dict):
        raise FunctionConfigError(
            f"Function `{function_id}` config `process` must be a mapping."
        )

    allowed_process = {
        "command",
        "args",
        "cwd",
        "timeout_seconds",
    }
    unknown_process = set(process) - allowed_process

    if unknown_process:
        raise FunctionConfigError(
            f"Function `{function_id}` process contains unsupported fields: "
            f"{sorted(unknown_process)!r}"
        )

    command = process.get("command")

    if not isinstance(command, str) or not command.strip():
        raise FunctionConfigError(
            f"Function `{function_id}` process.command must be a "
            "non-empty string."
        )

    args = process.get("args")

    if not isinstance(args, list) or not all(
        isinstance(item, str) for item in args
    ):
        raise FunctionConfigError(
            f"Function `{function_id}` process.args must be a list "
            "of strings."
        )

    raw_cwd = process.get("cwd", ".")

    if raw_cwd is None:
        raw_cwd = "."

    if not isinstance(raw_cwd, str) or not raw_cwd.strip():
        raise FunctionConfigError(
            f"Function `{function_id}` process.cwd must be a string or null."
        )

    cwd_path = Path(raw_cwd).expanduser()

    if not cwd_path.is_absolute():
        cwd_path = function_root / cwd_path

    cwd_path = cwd_path.resolve()

    if not cwd_path.exists() or not cwd_path.is_dir():
        raise FunctionConfigError(
            f"Function `{function_id}` working directory does not exist: "
            f"{cwd_path}"
        )

    timeout = _normalize_timeout(
        process.get("timeout_seconds"),
        function_id=function_id,
    )

    normalized_process = {
        "command": command.strip(),
        "args": list(args),
        "cwd": raw_cwd,
        "timeout_seconds": timeout,
    }

    return {
        "id": function_id,
        "name": catalog_entry["name"],
        "description": catalog_entry["description"],
        "enabled": catalog_entry["enabled"],
        "function_root": str(function_root),
        "config_path": str(config_path),
        "process": normalized_process,
        "_runtime": {
            "command": _resolve_command(
                command.strip(),
                function_root=function_root,
            ),
            "args": list(args),
            "cwd": str(cwd_path),
            "timeout_seconds": timeout,
        },
    }


def _validate_existing_package_for_registration(
    function_id: str,
    *,
    name: str,
    description: str,
    func_root: str | Path | None,
) -> dict[str, Any]:
    """
    Validate the explicitly named user Function Package before registration.

    This is target-specific validation only. It never scans func/.
    """
    proposed_entry = {
        "id": function_id,
        "name": name,
        "description": description,
        "enabled": True,
    }

    return _read_runtime_config(
        function_id,
        catalog_entry=proposed_entry,
        func_root=func_root,
    )


def _decode_output(data: bytes) -> str:
    if not data:
        return ""

    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeError:
            pass

    # Redirected Windows PowerShell output can sometimes be UTF-16LE.
    if len(data) >= 4 and data.count(b"\x00") > len(data) // 8:
        try:
            return data.decode("utf-16-le")
        except UnicodeError:
            pass

    try:
        return data.decode("utf-8")
    except UnicodeError:
        pass

    preferred = locale.getpreferredencoding(False) or "utf-8"

    try:
        return data.decode(preferred)
    except (LookupError, UnicodeError):
        return data.decode("utf-8", errors="replace")


def _bounded_output(
    data: bytes | None,
    *,
    limit_bytes: int,
) -> tuple[str, bool]:
    raw = data or b""
    truncated = len(raw) > limit_bytes

    if truncated:
        raw = raw[:limit_bytes]

    return _decode_output(raw), truncated


def _process_result(
    *,
    function: dict[str, Any],
    exit_code: int,
    stdout: bytes | None,
    stderr: bytes | None,
    output_limit_bytes: int,
    stdout_pretruncated: bool = False,
    stderr_pretruncated: bool = False,
) -> dict[str, Any]:
    stdout_text, stdout_limited = _bounded_output(
        stdout,
        limit_bytes=output_limit_bytes,
    )
    stderr_text, stderr_limited = _bounded_output(
        stderr,
        limit_bytes=output_limit_bytes,
    )

    return {
        "id": function["id"],
        "name": function["name"],
        "description": function["description"],
        "exit_code": exit_code,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "stdout_truncated": stdout_pretruncated or stdout_limited,
        "stderr_truncated": stderr_pretruncated or stderr_limited,
    }


class _BoundedStreamCapture:
    """
    Continuously drain one pipe while retaining only a bounded prefix.

    The reader is deliberately cancellable. It never relies on a blocking
    `stream.read()` that must later be interrupted by closing the stream from
    another thread. This keeps Function completion bounded even when a
    background descendant inherits stdout/stderr after the direct process exits.
    """

    def __init__(
        self,
        stream: Any,
        *,
        limit_bytes: int,
    ) -> None:
        self._stream = stream
        self._limit_bytes = limit_bytes
        self._buffer = bytearray()
        self._truncated = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._started = False
        self._thread = threading.Thread(
            target=self._drain,
            name="MuseAI-FunctionOutputDrain",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()
        self._started = True

    def _append(self, chunk: bytes) -> None:
        if not chunk:
            return

        with self._lock:
            remaining = self._limit_bytes - len(self._buffer)

            if remaining > 0:
                self._buffer.extend(chunk[:remaining])

            if len(chunk) > remaining:
                self._truncated = True

    def _mark_truncated(self) -> None:
        with self._lock:
            self._truncated = True

    def _drain_windows(self) -> None:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        fd = self._stream.fileno()
        raw_handle = msvcrt.get_osfhandle(fd)
        handle = wintypes.HANDLE(raw_handle)

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        peek_named_pipe = kernel32.PeekNamedPipe
        peek_named_pipe.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        peek_named_pipe.restype = wintypes.BOOL

        error_broken_pipe = 109
        error_no_data = 232
        error_invalid_handle = 6

        while not self._stop_event.is_set():
            available = wintypes.DWORD(0)
            ok = peek_named_pipe(
                handle,
                None,
                0,
                None,
                ctypes.byref(available),
                None,
            )

            if not ok:
                error = ctypes.get_last_error()

                if error in {
                    error_broken_pipe,
                    error_no_data,
                    error_invalid_handle,
                }:
                    return

                self._mark_truncated()
                return

            if available.value <= 0:
                self._stop_event.wait(OUTPUT_POLL_INTERVAL_SECONDS)
                continue

            try:
                chunk = os.read(
                    fd,
                    min(64 * 1024, int(available.value)),
                )
            except (OSError, ValueError):
                return

            if not chunk:
                return

            self._append(chunk)

    def _drain_posix(self) -> None:
        import select

        fd = self._stream.fileno()

        while not self._stop_event.is_set():
            try:
                ready, _, _ = select.select(
                    [fd],
                    [],
                    [],
                    OUTPUT_POLL_INTERVAL_SECONDS,
                )
            except (OSError, ValueError):
                return

            if not ready:
                continue

            try:
                chunk = os.read(fd, 64 * 1024)
            except (BlockingIOError, InterruptedError):
                continue
            except (OSError, ValueError):
                return

            if not chunk:
                return

            self._append(chunk)

    def _drain(self) -> None:
        try:
            if os.name == "nt":
                self._drain_windows()
            else:
                self._drain_posix()
        except Exception:
            # Output capture failures must not crash the Function runtime.
            # The retained prefix remains reportable but is marked incomplete.
            self._mark_truncated()

    def finish(
        self,
        *,
        grace_seconds: float = OUTPUT_DRAIN_GRACE_SECONDS,
    ) -> tuple[bytes, bool]:
        if not self._started:
            try:
                self._stream.close()
            except (OSError, ValueError):
                pass
            return b"", False

        # First allow ordinary EOF to drain naturally.
        self._thread.join(grace_seconds)

        if self._thread.is_alive():
            # A descendant may still own an inherited write handle. Cancel the
            # polling reader cooperatively rather than closing a stream while
            # another thread is inside a blocking read.
            self._mark_truncated()
            self._stop_event.set()
            self._thread.join(OUTPUT_CANCEL_GRACE_SECONDS)

        thread_alive = self._thread.is_alive()

        if not thread_alive:
            try:
                self._stream.close()
            except (OSError, ValueError):
                pass
        else:
            # The polling loops are designed to stop within one poll interval.
            # If an unexpected platform/runtime condition prevents that, never
            # block the main thread on stream.close().
            self._mark_truncated()

        with self._lock:
            return bytes(self._buffer), self._truncated


WINDOWS_CREATE_SUSPENDED = 0x00000004


def _create_windows_job(process: subprocess.Popen[bytes]) -> int | None:
    """
    Assign a suspended process to a private Windows Job Object.

    `run_function()` creates the process with CREATE_SUSPENDED and resumes it
    only after this function succeeds. Windows Job ownership is therefore a
    required precondition for user code execution, not an optional optimization.

    The Job intentionally does not use KILL_ON_JOB_CLOSE so a normally
    completed launcher may leave an intentional background child alive.
    """
    if os.name != "nt":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        create_job = kernel32.CreateJobObjectW
        create_job.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        create_job.restype = wintypes.HANDLE

        assign = kernel32.AssignProcessToJobObject
        assign.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        assign.restype = wintypes.BOOL

        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        job = create_job(None, None)
        if not job:
            return None

        process_handle = wintypes.HANDLE(
            int(process._handle)  # type: ignore[attr-defined]
        )

        if not assign(job, process_handle):
            close_handle(job)
            return None

        return int(job)
    except Exception:
        # The caller treats missing Job ownership as a start failure and never
        # resumes the suspended user process.
        return None


def _resume_windows_process(process: subprocess.Popen[bytes]) -> bool:
    """
    Resume a process created with CREATE_SUSPENDED.

    subprocess.Popen does not retain the primary thread handle, therefore the
    process handle is resumed with NtResumeProcess after Job assignment.
    """
    if os.name != "nt":
        return True

    try:
        import ctypes
        from ctypes import wintypes

        ntdll = ctypes.WinDLL("ntdll")
        nt_resume_process = ntdll.NtResumeProcess
        nt_resume_process.argtypes = [wintypes.HANDLE]
        nt_resume_process.restype = ctypes.c_long

        process_handle = wintypes.HANDLE(
            int(process._handle)  # type: ignore[attr-defined]
        )
        status = int(nt_resume_process(process_handle))

        # NT_SUCCESS(status) is true when the signed NTSTATUS is non-negative.
        return status >= 0
    except Exception:
        return False


def _close_windows_job(job_handle: int | None) -> None:
    if os.name != "nt" or job_handle is None:
        return

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        close_handle(wintypes.HANDLE(job_handle))
    except Exception:
        pass


def _terminate_windows_job(job_handle: int | None) -> bool:
    if os.name != "nt" or job_handle is None:
        return False

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        terminate_job = kernel32.TerminateJobObject
        terminate_job.argtypes = [wintypes.HANDLE, wintypes.UINT]
        terminate_job.restype = wintypes.BOOL

        return bool(
            terminate_job(
                wintypes.HANDLE(job_handle),
                wintypes.UINT(1),
            )
        )
    except Exception:
        return False


def _close_process_output_streams(
    process: subprocess.Popen[bytes],
) -> None:
    """Best-effort close of direct process stdout/stderr pipe handles."""
    for stream in (process.stdout, process.stderr):
        if stream is None:
            continue

        try:
            stream.close()
        except (OSError, ValueError):
            pass


def _terminate_process_tree(
    process: subprocess.Popen[bytes],
    *,
    windows_job: int | None,
) -> None:
    """
    Best-effort termination of the owned process tree.

    Job/process-group termination is attempted even if the direct process has
    already exited because descendants may still be alive.
    """
    if os.name == "nt":
        if _terminate_windows_job(windows_job):
            return

        if process.poll() is None:
            # Best-effort cleanup fallback. Normal Windows execution never
            # reaches user code without Job ownership, but this still protects
            # pre-resume/start-failure and defensive cleanup paths.
            try:
                subprocess.run(
                    [
                        "taskkill",
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                    ],
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=PROCESS_TERMINATION_GRACE_SECONDS,
                    check=False,
                )
                if process.poll() is not None:
                    return
            except (OSError, subprocess.SubprocessError):
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass

    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def _reap_direct_process(
    process: subprocess.Popen[bytes],
) -> None:
    if process.poll() is not None:
        return

    try:
        process.wait(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        process.kill()
    except OSError:
        pass

    try:
        process.wait(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def _terminate_and_reap_process_tree(
    process: subprocess.Popen[bytes],
    *,
    windows_job: int | None,
) -> None:
    _terminate_process_tree(
        process,
        windows_job=windows_job,
    )
    _reap_direct_process(process)


def _finish_capture_pair(
    stdout_capture: _BoundedStreamCapture,
    stderr_capture: _BoundedStreamCapture,
) -> tuple[bytes, bool, bytes, bool]:
    stdout, stdout_truncated = stdout_capture.finish()
    stderr, stderr_truncated = stderr_capture.finish()
    return stdout, stdout_truncated, stderr, stderr_truncated


def list_functions(
    *,
    manifest_path: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Return the registered Function catalog in manifest order."""
    path, entries = _read_manifest(manifest_path)

    return (
        {
            "manifest_path": str(path),
            "count": len(entries),
            "functions": entries,
        },
        [],
    )


def get_function(
    function_id: str,
    *,
    manifest_path: str | Path | None = None,
    func_root: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Return one registered Function and its normalized runtime config."""
    manifest, entry = _get_registered_entry(
        function_id,
        manifest_path=manifest_path,
    )
    function = _read_runtime_config(
        function_id,
        catalog_entry=entry,
        func_root=func_root,
    )

    public = {
        key: value
        for key, value in function.items()
        if key != "_runtime"
    }
    public["manifest_path"] = str(manifest)

    return public, []


def register_function(
    function_id: str,
    *,
    name: str,
    description: str,
    manifest_path: str | Path | None = None,
    func_root: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Register one explicitly named existing Function Package.

    The caller supplies id/name/description. The service does not infer them.
    Registration does not create, copy, or modify the Function Package.
    """
    function_id = _validate_function_id(
        function_id,
        error_type=FunctionPackageNotFoundError,
    )
    normalized_name = _normalize_semantic_text(
        name,
        field="name",
        function_id=function_id,
    )
    normalized_description = _normalize_semantic_text(
        description,
        field="description",
        function_id=function_id,
    )

    manifest, document, entries = _read_manifest_document(manifest_path)
    catalog = {entry["id"]: entry for entry in entries}

    if function_id in catalog:
        raise FunctionAlreadyRegisteredError(
            f"Function `{function_id}` is already registered."
        )

    # Validate only the user-specified package. Do not scan func/.
    _validate_existing_package_for_registration(
        function_id,
        name=normalized_name,
        description=normalized_description,
        func_root=func_root,
    )

    functions = document["functions"]
    functions[function_id] = _manifest_entry_document(
        name=normalized_name,
        description=normalized_description,
        enabled=True,
    )
    _write_manifest_atomic(manifest, document)

    return (
        {
            "id": function_id,
            "name": normalized_name,
            "description": normalized_description,
            "enabled": True,
            "changed": True,
            "manifest_path": str(manifest),
        },
        [],
    )


def update_function(
    function_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    manifest_path: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Update only MuseAI semantic catalog information for one Function."""
    _validate_function_id(
        function_id,
        error_type=FunctionNotFoundError,
    )

    if name is None and description is None:
        raise FunctionManifestError(
            "function.update requires --name and/or --description."
        )

    manifest, document, entries = _read_manifest_document(manifest_path)
    catalog = {entry["id"]: entry for entry in entries}
    current = catalog.get(function_id)

    if current is None:
        raise FunctionNotFoundError(
            f"Function `{function_id}` is not present in {manifest}."
        )

    new_name = (
        current["name"]
        if name is None
        else _normalize_semantic_text(
            name,
            field="name",
            function_id=function_id,
        )
    )
    new_description = (
        current["description"]
        if description is None
        else _normalize_semantic_text(
            description,
            field="description",
            function_id=function_id,
        )
    )

    changed = (
        new_name != current["name"]
        or new_description != current["description"]
    )

    if changed:
        document["functions"][function_id] = _manifest_entry_document(
            name=new_name,
            description=new_description,
            enabled=current["enabled"],
        )
        _write_manifest_atomic(manifest, document)

    return (
        {
            "id": function_id,
            "name": new_name,
            "description": new_description,
            "enabled": current["enabled"],
            "changed": changed,
            "manifest_path": str(manifest),
        },
        [],
    )


def unregister_function(
    function_id: str,
    *,
    manifest_path: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Remove one Function from MuseAI registry only.

    This operation never deletes or modifies func/<function-id>/.
    """
    _validate_function_id(
        function_id,
        error_type=FunctionNotFoundError,
    )

    manifest, document, entries = _read_manifest_document(manifest_path)
    catalog = {entry["id"]: entry for entry in entries}
    current = catalog.get(function_id)

    if current is None:
        raise FunctionNotFoundError(
            f"Function `{function_id}` is not present in {manifest}."
        )

    del document["functions"][function_id]
    _write_manifest_atomic(manifest, document)

    return (
        {
            "id": function_id,
            "name": current["name"],
            "description": current["description"],
            "enabled": current["enabled"],
            "changed": True,
            "package_deleted": False,
            "manifest_path": str(manifest),
        },
        [],
    )


def _set_function_enabled(
    function_id: str,
    *,
    enabled: bool,
    manifest_path: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    _validate_function_id(
        function_id,
        error_type=FunctionNotFoundError,
    )

    manifest, document, entries = _read_manifest_document(manifest_path)
    catalog = {entry["id"]: entry for entry in entries}
    current = catalog.get(function_id)

    if current is None:
        raise FunctionNotFoundError(
            f"Function `{function_id}` is not present in {manifest}."
        )

    changed = current["enabled"] is not enabled

    if changed:
        document["functions"][function_id] = _manifest_entry_document(
            name=current["name"],
            description=current["description"],
            enabled=enabled,
        )
        _write_manifest_atomic(manifest, document)

    return (
        {
            "id": function_id,
            "name": current["name"],
            "description": current["description"],
            "enabled": enabled,
            "changed": changed,
            "manifest_path": str(manifest),
        },
        [],
    )


def enable_function(
    function_id: str,
    *,
    manifest_path: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Set one registered Function enabled=true. Idempotent."""
    return _set_function_enabled(
        function_id,
        enabled=True,
        manifest_path=manifest_path,
    )


def disable_function(
    function_id: str,
    *,
    manifest_path: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Set one registered Function enabled=false. Idempotent."""
    return _set_function_enabled(
        function_id,
        enabled=False,
        manifest_path=manifest_path,
    )


def run_function(
    function_id: str,
    *,
    manifest_path: str | Path | None = None,
    func_root: str | Path | None = None,
    output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
) -> tuple[dict[str, Any], list[str]]:
    """
    Execute one registered Function and return its raw process result.

    Success means the configured process was started and exited with code 0.
    A non-zero exit is surfaced as FunctionProcessError.

    Process lifecycle ownership:
    - stdout/stderr are drained with bounded in-memory retention;
    - Windows processes are created suspended and are resumed only after
      required Job ownership has been established;
    - POSIX processes run in a dedicated session/process group;
    - timeout, KeyboardInterrupt, and unexpected abnormal exits terminate and
      reap the owned process tree before propagating the outcome upward;
    - normal completion does not kill intentional background descendants.
    """
    if (
        isinstance(output_limit_bytes, bool)
        or not isinstance(output_limit_bytes, int)
        or output_limit_bytes <= 0
    ):
        raise FunctionConfigError(
            "output_limit_bytes must be a positive integer."
        )

    _, entry = _get_registered_entry(
        function_id,
        manifest_path=manifest_path,
    )

    if not entry["enabled"]:
        raise FunctionDisabledError(
            f"Function `{function_id}` is disabled."
        )

    function = _read_runtime_config(
        function_id,
        catalog_entry=entry,
        func_root=func_root,
    )

    runtime = function["_runtime"]
    command = runtime["command"]
    argv = [command, *runtime["args"]]
    timeout_seconds = runtime["timeout_seconds"]

    if _is_path_like_command(command):
        command_path = Path(command)

        if not command_path.exists() or not command_path.is_file():
            raise FunctionCommandNotFoundError(
                f"Configured command not found: {command_path}"
            )

    popen_kwargs: dict[str, Any] = {
        "cwd": runtime["cwd"],
        "shell": False,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "bufsize": 0,
    }

    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | WINDOWS_CREATE_SUSPENDED
        )
    else:
        # A dedicated process group is useful not only for configured timeouts
        # but also for KeyboardInterrupt/unexpected-exit cleanup.
        popen_kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(
            argv,
            **popen_kwargs,
        )
    except FileNotFoundError as exc:
        raise FunctionCommandNotFoundError(
            f"Configured command could not be found: {command}"
        ) from exc
    except OSError as exc:
        raise FunctionStartError(
            f"Could not start Function `{function_id}`: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    windows_job: int | None = None
    stdout_capture: _BoundedStreamCapture | None = None
    stderr_capture: _BoundedStreamCapture | None = None
    timed_out = False

    try:
        if process.stdout is None or process.stderr is None:
            _terminate_and_reap_process_tree(
                process,
                windows_job=windows_job,
            )
            raise FunctionStartError(
                f"Could not capture Function `{function_id}` output."
            )

        if os.name == "nt":
            # The process is still suspended here. Windows process-tree
            # ownership is mandatory: never run user code unless the Job has
            # been created and the process has been assigned successfully.
            windows_job = _create_windows_job(process)

            if windows_job is None:
                _terminate_and_reap_process_tree(
                    process,
                    windows_job=None,
                )
                _close_process_output_streams(process)
                raise FunctionStartError(
                    f"Could not establish Windows process ownership for "
                    f"Function `{function_id}`."
                )

        stdout_capture = _BoundedStreamCapture(
            process.stdout,
            limit_bytes=output_limit_bytes,
        )
        stderr_capture = _BoundedStreamCapture(
            process.stderr,
            limit_bytes=output_limit_bytes,
        )
        stdout_capture.start()
        stderr_capture.start()

        if os.name == "nt" and not _resume_windows_process(process):
            _terminate_and_reap_process_tree(
                process,
                windows_job=windows_job,
            )
            _finish_capture_pair(
                stdout_capture,
                stderr_capture,
            )
            raise FunctionStartError(
                f"Could not resume Function `{function_id}` after "
                "Windows process ownership setup."
            )

        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_and_reap_process_tree(
                process,
                windows_job=windows_job,
            )

        (
            stdout,
            stdout_truncated,
            stderr,
            stderr_truncated,
        ) = _finish_capture_pair(
            stdout_capture,
            stderr_capture,
        )

    except BaseException:
        # Cancellation and unexpected abnormal exits must never leave user
        # Function processes running after MuseAI has stopped waiting for them.
        _terminate_and_reap_process_tree(
            process,
            windows_job=windows_job,
        )

        if stdout_capture is not None and stderr_capture is not None:
            try:
                _finish_capture_pair(
                    stdout_capture,
                    stderr_capture,
                )
            except Exception:
                pass

        raise
    finally:
        _close_windows_job(windows_job)

    if timed_out:
        details = _process_result(
            function=function,
            exit_code=-1,
            stdout=stdout,
            stderr=stderr,
            output_limit_bytes=output_limit_bytes,
            stdout_pretruncated=stdout_truncated,
            stderr_pretruncated=stderr_truncated,
        )
        details["timeout_seconds"] = timeout_seconds

        raise FunctionTimeoutError(
            f"Function `{function_id}` exceeded "
            f"{timeout_seconds} seconds.",
            details=details,
        )

    result = _process_result(
        function=function,
        exit_code=process.returncode,
        stdout=stdout,
        stderr=stderr,
        output_limit_bytes=output_limit_bytes,
        stdout_pretruncated=stdout_truncated,
        stderr_pretruncated=stderr_truncated,
    )

    if process.returncode != 0:
        raise FunctionProcessError(
            f"Function `{function_id}` exited with code "
            f"{process.returncode}.",
            details=result,
        )

    return result, []

