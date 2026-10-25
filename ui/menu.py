from __future__ import annotations

import questionary
from rich.console import Console

console = Console()

MAIN_MENU_CHOICES = [
    "1) Authorized static web collection",
    "2) Import a local document",
    "3) Browse collected records",
    "4) Search intelligence database",
    "5) Research ideas and supervisor ranking",
    "6) Run security self-check",
    "7) Settings",
    "9) Export results",
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


def prompt_text(message: str) -> str:
    return questionary.text(message).ask() or ""


def prompt_choice(message: str, choices: list[str]) -> str | None:
    return questionary.select(message, choices=choices).ask()


def prompt_multiple(message: str, choices: list[str]) -> list[str]:
    return questionary.checkbox(message, choices=choices).ask() or []


def prompt_domains(message: str) -> list[str]:
    raw = questionary.text(
        f"{message} (comma-separated, e.g. example.com, docs.google.com)"
    ).ask()
    if not raw:
        return []
    return [d.strip() for d in raw.split(",") if d.strip()]


def confirm(message: str) -> bool:
    return bool(questionary.confirm(message, default=False).ask())
