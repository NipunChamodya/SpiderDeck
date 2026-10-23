#!/usr/bin/env python3
"""
verify.py — checks that every package SpiderDeck needs actually imports.

Run standalone any time you want a quick health check:
    .venv/bin/python verify.py

install.sh calls this automatically as its last step.
"""

from __future__ import annotations

import importlib
import sys

# (import name, friendly/package name) — import name can differ from pip name
REQUIRED_MODULES = [
    ("rich", "rich"),
    ("questionary", "questionary"),
    ("playwright", "playwright"),
    ("httpx", "httpx"),
    ("selectolax", "selectolax"),
    ("bs4", "beautifulsoup4"),
    ("pandas", "pandas"),
    ("openpyxl", "openpyxl"),
    ("pdfplumber", "pdfplumber"),
    ("docx", "python-docx"),
    ("sklearn", "scikit-learn"),
]


def main() -> int:
    print("Verifying SpiderDeck dependencies import correctly...\n")
    missing: list[str] = []

    for import_name, package_name in REQUIRED_MODULES:
        try:
            importlib.import_module(import_name)
            print(f"  ✅ {package_name}")
        except ImportError as e:
            print(f"  ❌ {package_name}  ({e})")
            missing.append(package_name)

    print()
    if missing:
        print("Missing or broken packages:")
        for m in missing:
            print(f"  - {m}")
        print("\nFix: re-run  bash install.sh  — it retries only what's needed.")
        return 1

    print("All required packages import correctly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
