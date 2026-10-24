"""
security/validators.py
-----------------------
Every URL and file path SpiderDeck touches passes through here first.
Nothing in handlers/ or core/ should hit the network or filesystem
without going through one of these functions.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

# --- Path safety -----------------------------------------------------------

_TRAVERSAL_PATTERN = re.compile(r"\.\.(/|\\)")


class UnsafePathError(ValueError):
    pass


def safe_output_path(base_dir: Path, requested: str | Path) -> Path:
    """
    Resolve `requested` against `base_dir` and refuse to return anything
    that escapes base_dir. Use this for every file SpiderDeck WRITES.
    """
    base_dir = base_dir.resolve()
    requested = Path(requested)
    if requested.is_absolute() or "\\" in str(requested) or ".." in requested.parts:
        raise UnsafePathError("Output path must be a relative path without traversal.")
    candidate = (base_dir / requested).resolve()

    if not candidate.is_relative_to(base_dir) or candidate == base_dir:
        raise UnsafePathError(
            f"Refusing to write outside output directory: {requested}"
        )
    return candidate


def safe_input_path(requested: str | Path) -> Path:
    """
    Validate a path the user wants SpiderDeck to READ (local file/folder).
    Blocks obvious traversal tricks and requires the path to actually exist.
    """
    text = str(requested)
    if _TRAVERSAL_PATTERN.search(text):
        raise UnsafePathError(f"Path traversal pattern detected: {requested}")

    path = Path(text).expanduser().resolve()
    if not path.is_file():
        raise UnsafePathError(f"Path does not exist: {path}")
    return path


# --- URL / SSRF safety ------------------------------------------------------

_PRIVATE_NETWORKS = [
    ipaddress.ip_network(net)
    for net in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
]


class UnsafeURLError(ValueError):
    pass


def _is_private_ip(host: str) -> bool:
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(item[4][0])
                         for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]
        except (socket.gaierror, ValueError) as exc:
            raise UnsafeURLError("Destination DNS resolution failed.") from exc
    return not addresses or any(not ip.is_global for ip in addresses)



def validate_url(
    url: str,
    allowed_domains: list[str],
    allow_localhost: bool = False,
) -> str:
    """
    Raise UnsafeURLError unless:
      - scheme is http/https
      - host is on the user's allowlist
      - all resolved addresses are globally routable, unless dev mode is enabled
    This is preflight validation only: transports must pin destinations and
    revalidate redirects. It does not prevent DNS rebinding on its own.
    Returns the normalized URL if it passes.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Unsupported scheme: {parsed.scheme!r}")

    if not parsed.hostname:
        raise UnsafeURLError(f"No hostname in URL: {url}")

    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURLError("URL userinfo is not permitted.")
    if not allowed_domains:
        raise UnsafeURLError("An explicit domain allowlist is required.")
    try:
        parsed.port
    except ValueError as exc:
        raise UnsafeURLError("Invalid URL port.") from exc
    host = parsed.hostname.lower()
    if not any(host == d.lower() or host.endswith("." + d.lower()) for d in allowed_domains):
        raise UnsafeURLError("Host is not in the allowlist.")

    if not allow_localhost and _is_private_ip(host):
        raise UnsafeURLError(f"Refusing request to private/internal host: {host}")

    if allowed_domains:
        if not any(
            host == d.lower() or host.endswith("." + d.lower())
            for d in allowed_domains
        ):
            raise UnsafeURLError(
                f"Host {host!r} is not in the allowlist {allowed_domains}"
            )

    return url


# --- Subprocess / shell safety ---------------------------------------------

_SHELL_METACHARACTERS = re.compile(r"[;&|`$<>\\\n]")


class UnsafeArgumentError(ValueError):
    pass


def validate_subprocess_arg(arg: str) -> str:
    """
    Reject arguments containing shell metacharacters. Use this before
    passing ANY user-influenced string into subprocess.run(...). SpiderDeck
    never calls subprocess with shell=True, so this is a defense-in-depth
    check, not the only line of defense.
    """
    if _SHELL_METACHARACTERS.search(arg):
        raise UnsafeArgumentError(f"Unsafe characters in argument: {arg!r}")
    return arg


# --- "No bypass" detectors --------------------------------------------------

RESTRICTION_MARKERS = [
    "security limitations",
    "download is disabled",
    "downloading is unavailable",
    "printing is disabled",
    "making a copy is restricted",
    "you need permission",
    "view only",
    "view-only",
]


def looks_restricted(page_text: str) -> bool:
    """
    Heuristic check: does this page's visible text indicate the owner has
    disabled export/copy/download? If so, handlers must stop and advise
    requesting an authorized export rather than attempting any workaround.
    """
    lowered = page_text.lower()
    return any(marker in lowered for marker in RESTRICTION_MARKERS)
