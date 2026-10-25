"""Lazy native file selection and explicit default-browser opening.

No GUI framework is required. NSOpenPanel is preferred if PyObjC is already
installed; Tk is tried next. macOS's fixed choose-file AppleScript is the
fallback when Homebrew Python has no _tkinter. Paths never enter a command.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from security.network_policy import normalize_url


class DialogUnavailable(RuntimeError):
    pass


_FILE_SCRIPT = '''set selectedFile to choose file with prompt "Select a local document for SpiderDeck" of type {"pdf", "docx", "xlsx", "csv", "json", "txt", "md", "markdown", "html", "htm"}
return POSIX path of selectedFile'''


def desktop_available() -> bool:
    return (sys.platform == 'darwin' and sys.stdin.isatty() and sys.stdout.isatty()
            and not os.environ.get('SSH_CONNECTION') and not os.environ.get('SSH_TTY'))


def _appkit_file() -> str | None:
    try:
        from AppKit import NSApplication, NSOpenPanel, NSModalResponseOK
    except ImportError:
        raise DialogUnavailable from None
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    panel = NSOpenPanel.openPanel()
    panel.setTitle_('Import a document into SpiderDeck')
    panel.setCanChooseFiles_(True)
    panel.setCanChooseDirectories_(False)
    panel.setAllowsMultipleSelection_(False)
    panel.setAllowedFileTypes_(['pdf', 'docx', 'xlsx', 'csv', 'json', 'txt', 'md', 'markdown', 'html', 'htm'])
    if panel.runModal() != NSModalResponseOK:
        return None
    return str(panel.URL().path())


def _tk_file() -> str | None:
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError:
        raise DialogUnavailable from None
    root = None
    try:
        root = tkinter.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        selected = filedialog.askopenfilename(parent=root, title='Import a document into SpiderDeck',
            filetypes=[('Supported documents', '*.pdf *.docx *.xlsx *.csv *.json *.txt *.md *.markdown *.html *.htm'),
                       ('All files', '*')])
        return str(selected) if selected else None
    except tkinter.TclError:
        raise DialogUnavailable from None
    finally:
        if root is not None:
            try:
                root.destroy()
            except tkinter.TclError:
                pass


def _osascript_file() -> str | None:
    try:
        result = subprocess.run(['/usr/bin/osascript', '-e', _FILE_SCRIPT],
            capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise DialogUnavailable from None
    if result.returncode:
        if '(-128)' in result.stderr:
            return None
        raise DialogUnavailable
    path = result.stdout.removesuffix('\n')
    if not path or len(path) > 8192 or not Path(path).is_absolute():
        raise DialogUnavailable
    return path


def select_document() -> str | None:
    if not desktop_available():
        raise DialogUnavailable
    for chooser in (_appkit_file, _tk_file, _osascript_file):
        try:
            return chooser()
        except (DialogUnavailable, OSError, RuntimeError):
            continue
    raise DialogUnavailable


def open_browser(url: str) -> bool:
    """Only explicitly approved callers invoke this; never reuse browser sessions."""
    checked = normalize_url(url)
    try:
        if sys.platform == 'darwin':
            result = subprocess.run(['/usr/bin/open', '--', checked], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
            return result.returncode == 0
        import webbrowser
        try:
            return bool(webbrowser.open(checked, new=2))
        except webbrowser.Error:
            return False
    except (OSError, subprocess.TimeoutExpired):
        return False
