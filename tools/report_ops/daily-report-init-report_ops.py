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
    python muse.py init daily
    python muse.py report daily
- Only after both succeed, atomically writes last_auto_report_date.
- Injects the Report Tool Result into the current ZCode turn.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()

# MuseAI/tools/report_ops/daily-report-init.py
# parents[0] = report_ops
# parents[1] = tools
# parents[2] = MuseAI root
PROJECT_ROOT = SCRIPT_PATH.parents[2]

MUSE_PY = PROJECT_ROOT / "muse.py"
STATE_PATH = PROJECT_ROOT / "data" / "state" / "daily-report-init.json"

STATE_SCHEMA_VERSION = "1.0"
PURPOSE = "DailyReportInitHook"
HOOK_EVENT = "UserPromptSubmit"


class HookError(RuntimeError):
    pass


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )
    sys.stdout.flush()


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
    sys.stderr.write(f"[daily-report-init] {message}\n")
    sys.stderr.flush()


def _read_hook_input() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
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

    completed = subprocess.run(
        [
            sys.executable,
            str(MUSE_PY),
            "--purpose",
            PURPOSE,
            *args,
        ],
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=False,
    )

    raw_stdout = completed.stdout.strip()
    raw_stderr = completed.stderr.strip()

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


def _current_muse_date() -> str:
    result = _run_muse("time", "current")
    data = result.get("data")

    if not isinstance(data, dict):
        raise HookError("time.current returned invalid data.")

    current_date = data.get("current_date")
    if not isinstance(current_date, str) or not current_date:
        raise HookError("time.current did not return data.current_date.")

    return current_date


def main() -> int:
    try:
        hook_input = _read_hook_input()

        event_name = hook_input.get("hook_event_name")
        if event_name is not None and event_name != HOOK_EVENT:
            _emit({})
            return 0

        if not _is_inside_project(hook_input.get("cwd")):
            _emit({})
            return 0

        today = _current_muse_date()
        state = _load_state()

        if state.get("last_auto_report_date") == today:
            _emit({})
            return 0

        init_result = _run_muse("init", "daily")
        report_result = _run_muse("report", "daily")

        _atomic_write_state(
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "last_auto_report_date": today,
            }
        )

        context = (
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

        _emit_context(context)
        return 0

    except Exception as exc:
        _debug(f"{type(exc).__name__}: {exc}")

        _emit_context(
            "[MuseAI Automatic Daily Report]\n"
            "The automatic Daily Report hook failed before today could be "
            "marked as completed. Continue handling the user's original "
            "request, briefly surface this hook failure, and do not claim "
            "that the automatic Daily Report succeeded.\n"
            f"Failure: {type(exc).__name__}: {exc}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
