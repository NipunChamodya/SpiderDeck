#!/usr/bin/env python3
"""
SpiderDeck — authorized-access data collection and ranking tool.

Usage:
    python spiderdeck.py                 # interactive menu
    python spiderdeck.py --security-check # run security self-test only
    python spiderdeck.py --no-fx          # disable cosmetic effects
    python spiderdeck.py --dry-run        # show what would happen, do nothing

Use install.sh to create the virtual environment and install dependencies.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"


def _in_venv() -> bool:
    return sys.prefix != sys.base_prefix


def _bootstrap_environment() -> None:
    """
    Not running inside the venv yet — point to install.sh, which does the
    actual setup (venv creation + per-package retries). spiderdeck.py
    itself no longer installs packages, since a single pip call that fails
    halfway through a slow package used to abort the whole setup.
    """
    print("SpiderDeck isn't running inside its virtual environment yet.\n")

    install_script = ROOT / "install.sh"
    if not VENV_DIR.exists() and install_script.exists():
        print("Run the bootstrap script first — it's more reliable on slow")
        print("or flaky connections (retries each package individually):\n")
        print(f"  bash {install_script}\n")
        print("Then:")
        print(f"  source {VENV_DIR}/bin/activate")
        print(f"  python {ROOT / 'spiderdeck.py'}\n")
    else:
        print("Activate the virtual environment, then re-run:\n")
        print(f"  source {VENV_DIR}/bin/activate")
        print(f"  python {ROOT / 'spiderdeck.py'}\n")
    sys.exit(0)


def _maybe_install_playwright_browsers() -> None:
    answer = input(
        "Ensure Playwright browsers (Chromium, Firefox) are installed? [y/N]: "
    ).strip().lower()
    if answer == "y":
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium", "firefox"],
            check=True,
        )


def run_security_check() -> bool:
    from security import selfcheck
    return selfcheck.run()


def run_menu(args: argparse.Namespace) -> None:
    from core.config import load_config
    from fx import effects
    from ui import menu

    config = load_config()
    fx_enabled = config.fx_enabled and not args.no_fx
    from core.storage import RecordStore, StorageError
    from security.validators import UnsafePathError

    store = None

    def get_store() -> RecordStore:
        nonlocal store
        if store is None:
            store = RecordStore(ROOT / Path(config.output.dir).expanduser())
        return store

    effects.matrix_intro(enabled=fx_enabled)
    effects.glitch_title("S P I D E R D E C K", enabled=fx_enabled)

    if not run_security_check():
        print("\nSecurity self-check failed — refusing to start crawler features.")
        print("You can still read local files, but fix security/validators.py first.")

    while True:
        choice = menu.main_menu()

        if choice.startswith("1"):
            print("\nWeb collection is not implemented. Import an authorized local export with option 2.\n")

        elif choice.startswith("2"):
            from handlers.local import DocumentImportError, import_document
            requested = menu.prompt_path("Local document to import:")
            if not requested:
                continue
            if args.dry_run:
                print("Dry run: no document read.")
                continue
            try:
                result = import_document(requested, config.imports)
                summary = get_store().save_import(result)
            except DocumentImportError as exc:
                print(f"Import failed: {exc}")
                continue
            except StorageError as exc:
                print(f"Storage failed: {exc}")
                continue
            except (OSError, UnsafePathError):
                print("Storage failed. Check output permissions and disk space; no import was committed.")
                continue
            print(f"Imported {len(result.records)} records; saved {summary.inserted} new records; "
                  f"skipped {summary.duplicates} duplicate identifiers.")
            if summary.content_duplicates:
                print(f"{summary.content_duplicates} records have content already stored; source provenance retained.")
            if summary.reimported:
                print("This document's record set was imported previously.")
            for warning in result.warnings:
                print(f"Notice: {warning}")
            del result  # SQLite owns the persisted copy; do not accumulate sessions in RAM.

        elif choice.startswith(("3", "4", "9")):
            from ui import records
            try:
                if args.dry_run:
                    print("Dry run: database and exports left untouched.")
                    continue
                if choice.startswith("9"):
                    records.export(get_store())
                else:
                    records.browse(get_store(), search=choice.startswith("4"))
            except FileExistsError:
                print("Export already exists. Choose a new filename; existing data was preserved.")
            except (StorageError, ValueError) as exc:
                print(f"Operation failed: {records.terminal_text(str(exc), 300)}")
            except OSError:
                print("Operation failed. Check output permissions and disk space; existing data was preserved.")

        elif choice.startswith("5"):
            print("\n[Ranking against your ideas] — coming in Phase 5 of the build.\n")

        elif choice.startswith("6"):
            run_security_check()

        elif choice.startswith("7"):
            print(f"\nCurrent config: {config}\n")

        elif choice.startswith("8"):
            print("Goodbye.")
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="SpiderDeck")
    parser.add_argument("--security-check", action="store_true")
    parser.add_argument("--no-fx", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not _in_venv():
        _bootstrap_environment()

    if args.security_check:
        ok = run_security_check()
        sys.exit(0 if ok else 1)

    run_menu(args)


if __name__ == "__main__":
    main()
