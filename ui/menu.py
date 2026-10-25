from __future__ import annotations

import questionary
from rich.console import Console
from ui.display import interactive_terminal, terminal_text

console = Console()


class PromptCancelled(Exception):
    """A cancelled text prompt must not be mistaken for an intentional blank."""


def _answer(value: str | None) -> str:
    if value is None:
        raise PromptCancelled
    return value

MAIN_MENU_CHOICES = [
    "0) Research projects and focused collection",
    "1) Authorized static web collection",
    "2) Import a local document",
    "3) Browse collected records",
    "4) Search intelligence database",
    "5) Research ideas and supervisor ranking",
    "6) Security audit and collection logs",
    "7) Settings",
    "9) Export results",
    "8) Quit",
]


def main_menu() -> str:
    if not interactive_terminal():
        for label in MAIN_MENU_CHOICES:
            print(label)
        choices = {label.split(")", 1)[0]: label for label in MAIN_MENU_CHOICES}
        while True:
            raw = _input("Choice (8 or q exits): ")
            if raw is None or raw.strip().lower() in {"", "q", "quit", "exit"}:
                return "8) Quit"
            if raw.strip() in choices:
                return choices[raw.strip()]
            print("Choose one of the listed numbers.")
    choice = questionary.select(
        "SpiderDeck — what would you like to do?",
        choices=MAIN_MENU_CHOICES,
    ).ask()
    return choice or "8) Quit"


def prompt_path(message: str) -> str:
    if not interactive_terminal():
        return _answer(_input(message + " "))
    return _answer(questionary.path(message).ask())


def prompt_url(message: str) -> str:
    if not interactive_terminal():
        return _answer(_input(message + " "))
    return _answer(questionary.text(message).ask())


def prompt_text(message: str) -> str:
    if not interactive_terminal():
        return _answer(_input(message + " "))
    return _answer(questionary.text(message).ask())


def prompt_choice(message: str, choices: list[str]) -> str | None:
    if not choices:
        return None
    if not interactive_terminal():
        print(terminal_text(message, 500))
        for index, label in enumerate(choices, 1):
            print(f"{index}) {terminal_text(label, 500)}")
        while True:
            raw = _input("Choice (blank cancels): ")
            if raw is None or not raw.strip():
                return None
            if raw.strip().isascii() and raw.strip().isdigit() and len(raw.strip()) < 8:
                index = int(raw.strip())
                if 1 <= index <= len(choices):
                    return choices[index - 1]
            print("Choose one of the listed numbers, or leave blank to cancel.")
    return questionary.select(message, choices=choices).ask()


def prompt_multiple(message: str, choices: list[str]) -> list[str]:
    if not choices:
        return []
    if not interactive_terminal():
        print(terminal_text(message, 500))
        for index, label in enumerate(choices, 1):
            print(f"{index}) {terminal_text(label, 500)}")
        while True:
            raw = _input("Numbers separated by commas (blank cancels): ")
            if raw is None or not raw.strip():
                return []
            pieces = [piece.strip() for piece in raw.split(",")]
            if all(piece.isascii() and piece.isdigit() and len(piece) < 8 for piece in pieces):
                indices = {int(piece) for piece in pieces}
                if all(1 <= index <= len(choices) for index in indices):
                    return [choices[index - 1] for index in sorted(indices)]
            print("Use listed numbers separated by commas, or leave blank to cancel.")
    return questionary.checkbox(message, choices=choices).ask() or []


def prompt_domains(message: str) -> list[str]:
    raw = prompt_text(f"{message} (comma-separated, e.g. example.com, docs.google.com)")
    if not raw:
        return []
    return [d.strip() for d in raw.split(",") if d.strip()]


def confirm(message: str) -> bool:
    if not interactive_terminal():
        while True:
            raw = _input(terminal_text(message, 1000) + " [y/N] ")
            if raw is None or raw.strip().lower() in {"", "n", "no"}:
                return False
            if raw.strip().lower() in {"y", "yes"}:
                return True
            print("Enter yes or no; blank means no.")
    return bool(questionary.confirm(message, default=False).ask())


def _input(message: str) -> str | None:
    try:
        return input(message)
    except EOFError:
        return None
    except KeyboardInterrupt:
        print("\nCancelled.")
        return None
