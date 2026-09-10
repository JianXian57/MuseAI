#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ZCode UserPromptSubmit hook for MuseAI automatic Daily Report.

Recommended location:
    MuseAI/tools/report_ops/daily-report-init.py

Behavior:
- Only activates when ZCode cwd is inside this MuseAI repository.
- Uses MuseAI public CLI for current date, Daily Init, and Daily Report.
- If today's automatic report was already generated, returns no context.
- Otherwise runs:
    muse.py init daily
    muse.py report daily
- Serializes the complete first-daily-report flow with a cross-process lock.
- Emits the Report Tool Result to the current ZCode turn using UTF-8 JSON.
- Only after successful context emission, atomically records
  last_auto_report_date.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCRIPT_PATH = Path(__file__).resolve()

# MuseAI/tools/report_ops/daily-report-init.py
# parents[0] = report_ops
# parents[1] = tools
# parents[2] = MuseAI root
PROJECT_ROOT = SCRIPT_PATH.parents[2]

MUSE_PY = PROJECT_ROOT / "muse.py"
STATE_PATH = PROJECT_ROOT / "data" / "state" / "daily-report-init.json"
LOCK_PATH = PROJECT_ROOT / "data" / "state" / "daily-report-init.lock"

STATE_SCHEMA_VERSION = "1.0"
PURPOSE = "DailyReportInitHook"
HOOK_EVENT = "UserPromptSubmit"
LOCK_TIMEOUT_SECONDS = 20.0
LOCK_POLL_SECONDS = 0.1


class HookError(RuntimeError):
    pass


def _write_utf8(stream: Any, text: str, *, errors: str = "strict") -> None:
    """Write explicit UTF-8 bytes when a binary buffer is available."""
    data = text.encode("utf-8", errors=errors)
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
        return

    # Test doubles such as io.StringIO do not expose `.buffer`.
    stream.write(data.decode("utf-8", errors=errors))
    stream.flush()


def _emit(payload: dict[str, Any]) -> None:
    """Write the one and only ZCode protocol object as UTF-8 JSON."""
    _write_utf8(
        sys.stdout,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )


def _emit_context(text: str) -> None:
    _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": HOOK_EVENT,
                "additionalContext": text,
            }
        }
    )


def _debug(message: str) -> None:
    # Diagnostics are best-effort and must never corrupt stdout protocol JSON.
    try:
        _write_utf8(
            sys.stderr,
            f"[daily-report-init] {message}\n",
            errors="backslashreplace",
        )
    except Exception:
        pass


def _read_hook_input() -> dict[str, Any]:
    buffer = getattr(sys.stdin, "buffer", None)

    try:
        if buffer is not None:
            raw = buffer.read().decode("utf-8", errors="strict").strip()
        else:
            raw = sys.stdin.read().strip()
    except UnicodeDecodeError as exc:
        raise HookError(f"Invalid UTF-8 in ZCode hook input: {exc}") from exc

    if not raw:
        return {}

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HookError(f"Invalid ZCode hook input JSON: {exc}") from exc

    if not isinstance(value, dict):
        raise HookError("ZCode hook input must be a JSON object.")

    return value


def _is_inside_project(cwd_value: Any) -> bool:
    if not isinstance(cwd_value, str) or not cwd_value.strip():
        return False

    try:
        cwd = Path(cwd_value).expanduser().resolve()
        root = PROJECT_ROOT.resolve()

        common = os.path.commonpath(
            [os.path.normcase(str(cwd)), os.path.normcase(str(root))]
        )
        return os.path.normcase(common) == os.path.normcase(str(root))
    except (OSError, ValueError):
        return False


def _run_muse(*args: str) -> dict[str, Any]:
    if not MUSE_PY.is_file():
        raise HookError(f"MuseAI root CLI was not found: {MUSE_PY}")

    env = os.environ.copy()
    # Child CLI output is a machine protocol. Force UTF-8 independently of the
    # Windows console/code-page inherited by the host process.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    completed = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(MUSE_PY),
            "--purpose",
            PURPOSE,
            *args,
        ],
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=False,
        shell=False,
        check=False,
    )

    try:
        raw_stdout = completed.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise HookError(
            f"MuseAI returned non-UTF-8 stdout for: {' '.join(args)} "
            f"(exit={completed.returncode})"
        ) from exc

    raw_stderr = completed.stderr.decode(
        "utf-8",
        errors="backslashreplace",
    ).strip()

    if raw_stderr:
        _debug(raw_stderr)

    if not raw_stdout:
        raise HookError(
            f"MuseAI returned empty stdout for: {' '.join(args)} "
            f"(exit={completed.returncode})"
        )

    try:
        result = json.loads(raw_stdout)
    except json.JSONDecodeError as exc:
        raise HookError(
            f"MuseAI returned invalid JSON for: {' '.join(args)}"
        ) from exc

    if not isinstance(result, dict):
        raise HookError(
            f"MuseAI returned a non-object result for: {' '.join(args)}"
        )

    if completed.returncode != 0 or result.get("ok") is not True:
        raise HookError(
            f"MuseAI {' '.join(args)} failed "
            f"(exit={completed.returncode}, error={result.get('error')!r})"
        )

    return result


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "last_auto_report_date": None,
        }

    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HookError(f"Could not read state file: {STATE_PATH}: {exc}") from exc

    if not isinstance(state, dict):
        raise HookError("Daily report state must be a JSON object.")

    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise HookError(
            "Unsupported daily report state schema_version: "
            f"{state.get('schema_version')!r}"
        )

    last_date = state.get("last_auto_report_date")
    if last_date is not None and not isinstance(last_date, str):
        raise HookError("last_auto_report_date must be a string or null.")

    return state


def _atomic_write_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{STATE_PATH.name}.",
        suffix=".tmp",
        dir=str(STATE_PATH.parent),
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_name, STATE_PATH)

    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _try_lock(handle: Any) -> bool:
    """Try to acquire an exclusive cross-process lock without blocking."""
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    # POSIX fallback keeps the regression test executable outside Windows.
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return False
    return True


def _unlock(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _daily_report_lock(
    *,
    timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Serialize the full check -> init -> report -> emit -> commit flow."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    with LOCK_PATH.open("a+b") as handle:
        # msvcrt.locking locks a byte range; ensure byte 0 exists.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)

        deadline = time.monotonic() + max(0.0, timeout_seconds)
        acquired = False

        while True:
            if _try_lock(handle):
                acquired = True
                break

            if time.monotonic() >= deadline:
                raise HookError(
                    "Timed out waiting for the Daily Report cross-process lock."
                )

            time.sleep(LOCK_POLL_SECONDS)

        try:
            yield
        finally:
            if acquired:
                try:
                    _unlock(handle)
                except OSError as exc:
                    _debug(f"Could not release Daily Report lock cleanly: {exc}")


def _current_muse_date() -> str:
    result = _run_muse("time", "current")
    data = result.get("data")

    if not isinstance(data, dict):
        raise HookError("time.current returned invalid data.")

    current_date = data.get("current_date")
    if not isinstance(current_date, str) or not current_date:
        raise HookError("time.current did not return data.current_date.")

    return current_date


def _build_context(
    *,
    today: str,
    init_result: dict[str, Any],
    report_result: dict[str, Any],
) -> str:
    return (
        "[MuseAI Automatic Daily Report]\n"
        f"This is the first MuseAI user interaction for {today} that "
        "successfully generated today's automatic Daily Report.\n"
        "The hook has already completed `init.daily` and `report.daily`; "
        "do not rerun them merely for this automatic report.\n"
        "Before answering the user's original prompt, render the Daily "
        "Report according to `.zcode/skills/daily-report/SKILL.md` using "
        "the authoritative Report Tool Result below. After the report, "
        "continue handling the user's original request normally.\n"
        "init.daily warnings: "
        f"{json.dumps(init_result.get('warnings', []), ensure_ascii=False)}\n"
        "Report Tool Result:\n"
        f"{json.dumps(report_result, ensure_ascii=False, separators=(',', ':'))}"
    )


def main() -> int:
    output_emitted = False

    try:
        hook_input = _read_hook_input()

        event_name = hook_input.get("hook_event_name")
        if event_name is not None and event_name != HOOK_EVENT:
            _emit({})
            return 0

        if not _is_inside_project(hook_input.get("cwd")):
            _emit({})
            return 0

        with _daily_report_lock():
            # Resolve the authoritative date inside the same serialized flow.
            # This also avoids a midnight rollover while waiting for the lock.
            today = _current_muse_date()

            # The state must be read after lock acquisition. A second process
            # may have completed today's report while this process was waiting.
            state = _load_state()
            if state.get("last_auto_report_date") == today:
                _emit({})
                return 0

            init_result = _run_muse("init", "daily")
            report_result = _run_muse("report", "daily")
            context = _build_context(
                today=today,
                init_result=init_result,
                report_result=report_result,
            )

            # At-least-once delivery semantics: only mark success after the
            # protocol payload has been written and flushed successfully.
            _emit_context(context)
            output_emitted = True

            _atomic_write_state(
                {
                    "schema_version": STATE_SCHEMA_VERSION,
                    "last_auto_report_date": today,
                }
            )

        return 0

    except Exception as exc:
        _debug(f"{type(exc).__name__}: {exc}")

        # Never write a second JSON object after a successful protocol emit.
        # If state commit failed after emission, leaving the date unmarked is
        # intentional so a later prompt may retry.
        if output_emitted:
            return 0

        try:
            _emit_context(
                "[MuseAI Automatic Daily Report]\n"
                "The automatic Daily Report hook failed before today could be "
                "marked as completed. Continue handling the user's original "
                "request, briefly surface this hook failure, and do not claim "
                "that the automatic Daily Report succeeded.\n"
                f"Failure: {type(exc).__name__}: {exc}"
            )
        except Exception as emit_exc:
            _debug(
                "Could not emit Daily Report failure context: "
                f"{type(emit_exc).__name__}: {emit_exc}"
            )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
