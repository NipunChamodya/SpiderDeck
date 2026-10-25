#!/usr/bin/env python3
"""
SpiderDeck — authorized-access data collection and ranking tool.

Usage:
    python spiderdeck.py                 # interactive menu
    python spiderdeck.py --security-check # run security self-test only
    python spiderdeck.py --no-fx          # disable cosmetic effects
    python spiderdeck.py --plain --quiet # numbered prompts, reduced output
    python spiderdeck.py --show-settings # configuration JSON, without database access
    python spiderdeck.py --dry-run        # show what would happen, do nothing

Use install.sh to create the virtual environment and install dependencies.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import AppConfig
    from ui.display import DisplayOptions

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"


class ConfigurationError(ValueError):
    pass


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
    return selfcheck.run(verbose=False, plain=True)


def run_menu(args: argparse.Namespace) -> None:
    from core.config import load_config
    from ui.display import use_options

    selected = getattr(args, "config", None)
    try:
        config = load_config(Path(selected).expanduser()) if selected else load_config()
    except (OSError, ValueError, TypeError):
        from ui import menu
        if sys.stdin.isatty() and sys.stdout.isatty() and not args.dry_run:
            print('Configuration is unreadable. The original will remain untouched. Settings can create a private backup and recover it.')
            try:
                allowed = menu.confirm('Continue this session with documented defaults and no approved hostnames? Output defaults to the application output directory.')
            except menu.PromptCancelled:
                allowed = False
            if allowed:
                from core.config import AppConfig, CrawlConfig, OutputConfig
                config = AppConfig(CrawlConfig(), OutputConfig())
            else:
                raise ConfigurationError('Configuration recovery cancelled. The original file was preserved.') from None
        else:
            raise ConfigurationError('Cannot load configuration. Check the TOML path, section types and values; interactive Terminal sessions can open safe recovery.') from None
    with use_options(_display_options(args)):
        _run_menu(args, config)


def _display_options(args: argparse.Namespace) -> DisplayOptions:
    from ui.display import DisplayOptions
    return DisplayOptions(
        quiet=getattr(args, "quiet", False),
        plain=getattr(args, "plain", False) or "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb",
        reduced_motion=(getattr(args, "reduced_motion", False) or getattr(args, "no_fx", False)
                        or os.environ.get("SPIDERDECK_REDUCED_MOTION", "").lower() in {"1", "true", "yes", "on"}),
        animate=getattr(args, "animate", False),
    )


def _run_menu(args: argparse.Namespace, config: AppConfig) -> None:
    from fx import effects
    from ui import menu
    from ui.display import banner, motion_enabled, notice, options
    from ui.progress import operation

    from core.storage import RecordStore, StorageError
    from security.validators import UnsafePathError

    store = None

    def get_store() -> RecordStore:
        nonlocal store
        if store is None:
            store = RecordStore(ROOT / Path(config.output.dir).expanduser())
        return store

    notice("Checking local security controls...")
    security_ok = run_security_check()
    banner()
    if not security_ok:
        print("\nSecurity self-check failed — refusing to start crawler features.")
        print("You can still read local files, but fix security/validators.py first.")
    else:
        notice("Security self-check passed. Web collection still requires explicit target approval.")
    if security_ok and config.fx_enabled and options().animate and motion_enabled():
        effects.matrix_intro(enabled=True)
        effects.glitch_title("S P I D E R D E C K", enabled=True)
    notice("Use arrow keys and Enter, or listed numbers in plain mode. Ctrl+C cancels; 8 exits.")

    while True:
        choice = menu.main_menu()

        if choice.startswith("0"):
            if args.dry_run:
                print('Dry run: projects and database left untouched.')
                continue
            from core.config import CONFIG_PATH
            from ui import research
            selected = getattr(args,'config',None)
            try:
                research.run(config,get_store,Path(selected).expanduser() if selected else CONFIG_PATH,ROOT,security_ok=security_ok)
            except menu.PromptCancelled:
                print('Project workflow cancelled. Existing research remains saved.')
            except (StorageError,OSError,ValueError):
                print('Research database unavailable. Check output permissions, disk space and backups; existing evidence was not replaced.')

        elif choice.startswith("1"):
            if args.dry_run:
                print("Dry run: no web requests or database writes.")
                continue
            if not security_ok:
                print("Web collection is disabled because the startup security self-check failed.")
                continue
            from ui import collection
            try:
                from core.config import CONFIG_PATH
                selected = getattr(args, "config", None)
                collection.run(config.crawl, get_store,
                               config_path=Path(selected).expanduser() if selected else CONFIG_PATH,
                               output_dir=ROOT / Path(config.output.dir).expanduser())
            except menu.PromptCancelled:
                print("Collection prompt cancelled; no target approved.")
            except (StorageError, OSError, ValueError):
                print("Collection/storage failed. Check configuration, output permissions and disk space; audit may be unavailable.")

        elif choice.startswith("2"):
            from ui import importing
            importing.run(config.imports, get_store, dry_run=args.dry_run)

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
            except menu.PromptCancelled:
                print("Export cancelled." if choice.startswith("9") else "Search cancelled.")
            except (StorageError, ValueError) as exc:
                print(f"Operation failed: {records.terminal_text(str(exc), 300)}")
            except OSError:
                print("Operation failed. Check output permissions and disk space; existing data was preserved.")

        elif choice.startswith("5"):
            from ui import ideas
            from ui.records import terminal_text
            if args.dry_run:
                print("Dry run: research ideas and database left untouched.")
                continue
            try:
                ideas.run(get_store(), config.ranking)
            except StorageError as exc:
                print("Ranking unavailable: " + terminal_text(str(exc), 300))

        elif choice.startswith("6"):
            from ui import audit
            audit.run(ROOT / Path(config.output.dir).expanduser())

        elif choice.startswith("7"):
            from core.config import CONFIG_PATH
            from ui.settings import run
            selected = getattr(args, "config", None)
            run(config, Path(selected).expanduser() if selected else CONFIG_PATH, ROOT, dry_run=args.dry_run)

        elif choice.startswith("8"):
            print("Goodbye.")
            break


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SpiderDeck")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--security-check", action="store_true", help="Run offline security self-checks and exit")
    actions.add_argument("--show-settings", action="store_true", help="Print effective configuration as JSON and exit")
    motion = parser.add_mutually_exclusive_group()
    motion.add_argument("--no-fx", "--no-animation", dest="no_fx", action="store_true", help="Disable cosmetic motion")
    motion.add_argument("--animate", action="store_true", help="Opt into startup effects on capable terminals")
    parser.add_argument("--reduced-motion", action="store_true", help="Use static status messages")
    parser.add_argument("--quiet", action="store_true", help="Hide startup notices and progress; retain results, errors and approvals")
    parser.add_argument("--plain", action="store_true", help="Use numbered prompts and static output")
    parser.add_argument("--config", metavar="PATH", help="Read an explicitly selected TOML configuration")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not _in_venv():
        _bootstrap_environment()

    from ui.display import interactive_terminal, use_options
    try:
        with use_options(_display_options(args)):
            if args.security_check:
                from security import selfcheck
                ok = selfcheck.run(verbose=not args.quiet, plain=args.plain or not interactive_terminal())
                if args.quiet:
                    print("Security self-check: " + ("PASS" if ok else "FAIL"))
                return 0 if ok else 1
            if args.show_settings:
                from core.config import load_config
                from ui.settings import as_json
                try:
                    config = load_config(Path(args.config).expanduser()) if args.config else load_config()
                except (OSError, ValueError, TypeError):
                    print("Cannot load configuration. Check the TOML path, section types and values.", file=sys.stderr)
                    return 2
                print(as_json(config))
                return 0
            run_menu(args)
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nCancelled. Previously committed records were preserved.")
        return 130
    except BrokenPipeError:
        return 141
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
