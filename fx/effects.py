"""
fx/effects.py
-------------
Purely cosmetic terminal effects. Never blocks or slows the actual
crawl/file logic — call these from a separate thread, or just call
them synchronously at start/end since they're short.

Degrades gracefully: if the terminal doesn't support color/unicode,
rich will fall back to plain text automatically.
"""

from __future__ import annotations

import random
import shutil
import time

from rich.console import Console

console = Console()

_SPIDER_FRAMES = ["🕷️ ", " 🕷️", "🕸️ ", " 🕸️"]
_MATRIX_CHARS = "01アイウエオカキクケコ$#@&*+=-"


def matrix_intro(duration: float = 1.2, enabled: bool = True) -> None:
    if not enabled:
        console.print("[bold cyan]SpiderDeck[/bold cyan] starting...")
        return

    width = shutil.get_terminal_size((80, 20)).columns
    end_time = time.time() + duration
    while time.time() < end_time:
        line = "".join(random.choice(_MATRIX_CHARS) for _ in range(width))
        console.print(f"[green]{line}[/green]", end="\r")
        time.sleep(0.04)
    console.print(" " * width, end="\r")


def glitch_title(text: str, enabled: bool = True) -> None:
    if not enabled:
        console.print(f"[bold]{text}[/bold]")
        return

    glitch_chars = "!@#$%&*▓▒░"
    for _ in range(4):
        scrambled = "".join(
            random.choice(glitch_chars) if random.random() < 0.3 else c
            for c in text
        )
        console.print(f"[bold magenta]{scrambled}[/bold magenta]", end="\r")
        time.sleep(0.05)
    console.print(f"[bold cyan]{text}[/bold cyan]")


def spider_crawl_tick(step: int, label: str, enabled: bool = True) -> str:
    """
    Returns a single status line to print/update during a crawl loop.
    Call this once per item collected; caller controls the loop.
    """
    if not enabled:
        return f"[{step}] {label}"
    frame = _SPIDER_FRAMES[step % len(_SPIDER_FRAMES)]
    return f"{frame} collecting: {label}"


def glitch_flicker(enabled: bool = True) -> None:
    if not enabled:
        return
    console.print("[dim]▓▒░[/dim]", end="\r")
    time.sleep(0.03)
    console.print("   ", end="\r")
