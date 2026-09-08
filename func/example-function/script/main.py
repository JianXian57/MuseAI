#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Reference MuseAI Custom Function implementation."""

from pathlib import Path


def main() -> int:
    print("MUSE_CUSTOM_FUNCTION_OK")
    print(f"CWD={Path.cwd()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
