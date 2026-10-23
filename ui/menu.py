from __future__ import annotations

import questionary
from rich.console import Console

console = Console()

MAIN_MENU_CHOICES = [
    "1) Crawl a website URL",
    "2) Read a local file or folder",
    "3) Open a browser for manual login, then extract what's allowed",
    "4) Clean / structure collected results",
    "5) Rank results against my ideas",
    "6) Run security self-check",
    "7) Settings",
    "8) Quit",
]


def main_menu() -> str:
    choice = questionary.select(
        "SpiderDeck — what would you like to do?",
        choices=MAIN_MENU_CHOICES,
    ).ask()
    return choice or "8) Quit"


def prompt_path(message: str) -> str:
    return questionary.path(message).ask() or ""


def prompt_url(message: str) -> str:
    return questionary.text(message).ask() or ""


def prompt_domains(message: str) -> list[str]:
    raw = questionary.text(
        f"{message} (comma-separated, e.g. example.com, docs.google.com)"
    ).ask()
    if not raw:
        return []
    return [d.strip() for d in raw.split(",") if d.strip()]


def confirm(message: str) -> bool:
    return bool(questionary.confirm(message, default=False).ask())
