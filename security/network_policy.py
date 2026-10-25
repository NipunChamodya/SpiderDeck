"""Exact-origin authorization and fail-closed destination validation."""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit, urlunsplit


def canonical_path(value: str) -> str:
    encoded = quote(value, safe="/!$&'()*+,;=:@-._~%")
    def replace(match: re.Match[str]) -> str:
        char = chr(int(match[0][1:], 16))
        return char if char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~" else match[0].upper()
    return re.sub(r"%[0-9a-fA-F]{2}", replace, encoded)


class CollectionError(ValueError):
    """Only fixed, non-sensitive codes/messages may reach audit logs."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def hostname(value: str) -> str:
    try:
        if not value or any(char in value for char in "%\\/@:*[]") or value.endswith("."):
            raise ValueError
        encoded = value.encode("idna").decode("ascii").lower()
        if encoded == "localhost" or encoded.endswith(".localhost"):
            raise ValueError
        if len(encoded) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
                                     for part in encoded.split(".")):
            raise ValueError
        try:
            socket.inet_aton(encoded)  # Local numeric parsing, not DNS.
        except OSError:
            pass
        else:
            raise ValueError  # Hostname allowlists do not accept numeric IP representations.
        return encoded
    except (ValueError, UnicodeError) as exc:
        raise CollectionError("invalid_hostname") from exc


def normalize_url(url: str) -> str:
    if (not isinstance(url, str) or len(url) > 4096 or "\\" in url
            or any(ord(char) <= 32 or ord(char) == 127 for char in url)):
        raise CollectionError("invalid_url")
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise CollectionError("invalid_scheme_or_host")
        if parsed.username is not None or parsed.password is not None:
            raise CollectionError("userinfo_forbidden")
        # Initial static collector intentionally excludes secret-bearing/signed queries.
        if parsed.query:
            raise CollectionError("query_urls_unsupported")
        host = hostname(parsed.hostname)
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        if port != (443 if parsed.scheme == "https" else 80):
            raise CollectionError("nonstandard_port")
        path = parsed.path or "/"
        if re.search(r"%(?![a-fA-F0-9]{2})", path):
            raise CollectionError("invalid_url")
        decoded = unquote(path, errors="strict")
        if (any(ord(char) < 32 or ord(char) == 127 for char in decoded)
                or "\\" in decoded or re.search(r"%(?:2f|5c|25)", path, re.I)
                or any(part in {".", ".."} for part in decoded.split("/"))):
            raise CollectionError("ambiguous_path")
        path = canonical_path(path)
        normalized = urlunsplit((parsed.scheme, host, path, "", ""))
        if len(normalized) > 4096:
            raise CollectionError("invalid_url")
        return normalized
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, CollectionError):
            raise
        raise CollectionError("invalid_url") from exc


def origin(url: str) -> str:
    parsed = urlsplit(normalize_url(url))
    return f"{parsed.scheme}://{parsed.netloc}"


@dataclass(frozen=True)
class TargetApproval:
    seed_url: str
    origin: str


def approve_target(url: str, allowed_domains: list[str], *, authorized: bool) -> TargetApproval:
    if authorized is not True:
        raise CollectionError("target_approval_required")
    normalized = normalize_url(url)
    if urlsplit(normalized).hostname not in {hostname(domain) for domain in allowed_domains}:
        raise CollectionError("domain_not_allowlisted")
    return TargetApproval(normalized, origin(normalized))


def public_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise CollectionError("invalid_dns_address") from exc
    if (not address.is_global or address.is_multicast or address.is_reserved
            or (isinstance(address, ipaddress.IPv6Address)
                and (address.ipv4_mapped is not None or address.sixtofour is not None
                     or address.teredo is not None or address.scope_id is not None
                     or address not in ipaddress.ip_network("2000::/3")))):
        raise CollectionError("prohibited_destination")
    return address


class NetworkPolicy:
    def __init__(self, approval: TargetApproval, allowed_domains: list[str]):
        checked = approve_target(approval.seed_url, allowed_domains, authorized=True)
        if approval != checked:
            raise CollectionError("invalid_approval")
        self.approval = checked
        self.allowed_domains = tuple(allowed_domains)

    def check_url(self, url: str) -> str:
        normalized = normalize_url(url)
        if origin(normalized) != self.approval.origin:
            raise CollectionError("new_origin_requires_approval")
        if urlsplit(normalized).hostname not in {hostname(domain) for domain in self.allowed_domains}:
            raise CollectionError("domain_not_allowlisted")
        return normalized

    def resolve(self, url: str) -> tuple[str, tuple[str, ...]]:
        normalized = self.check_url(url)
        parsed = urlsplit(normalized)
        host = parsed.hostname
        port = 443 if parsed.scheme == "https" else 80
        try:
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise CollectionError("dns_resolution_failed") from exc
        if not answers:
            raise CollectionError("dns_resolution_failed")
        addresses: set[str] = set()
        for family, _, _, _, endpoint in answers:
            if family not in {socket.AF_INET, socket.AF_INET6}:
                raise CollectionError("invalid_dns_address")
            addresses.add(str(public_ip(endpoint[0])))
        return normalized, tuple(sorted(addresses))
