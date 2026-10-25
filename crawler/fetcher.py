"""Direct-IP HTTP transport: no proxy, cookies, auth, automatic redirects or DNS redial."""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
import threading
from dataclasses import dataclass
from typing import Any, BinaryIO
from urllib.parse import urlsplit

from security.network_policy import CollectionError, NetworkPolicy, public_ip


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes


class _LimitedReader:
    def __init__(self, handle: BinaryIO):
        self.handle = handle
        self.line_bytes = 0

    def readline(self, size: int = -1) -> bytes:
        line = self.handle.readline(min(65537, size) if size >= 0 else 65537)
        self.line_bytes += len(line)
        if self.line_bytes > 65536:
            raise CollectionError("response_headers_too_large")
        return line

    def __getattr__(self, name: str) -> Any:
        return getattr(self.handle, name)


class _BoundedResponse(http.client.HTTPResponse):
    def __init__(self, sock: socket.socket, debuglevel: int = 0, method: str | None = None,
                 url: str | None = None):
        super().__init__(sock, debuglevel, method, url)
        self.fp = _LimitedReader(self.fp)


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, address: str, *, timeout: float, tls: bool):
        super().__init__(host, port, timeout=timeout)
        # HTTPConnection's class-level debug switch prints raw headers to stdout.
        # Never inherit it, even if an embedding application enables HTTP debug.
        self.debuglevel = 0
        self.address = address
        self.tls = tls
        self.active_socket = None
        self.response_class = _BoundedResponse
        self.deadline = time.monotonic() + timeout

    def abort(self) -> None:
        if self.active_socket is not None:
            try:
                self.active_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.active_socket.close()

    def connect(self) -> None:
        address = public_ip(self.address)
        sock = socket.socket(socket.AF_INET6 if address.version == 6 else socket.AF_INET, socket.SOCK_STREAM)
        self.active_socket = sock
        try:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise CollectionError("request_timeout")
            sock.settimeout(remaining)
            # Numeric sockaddr on an explicitly chosen family: no hostname resolver call here.
            sock.connect((str(address), self.port))
            if ipaddress.ip_address(sock.getpeername()[0]) != address:
                raise CollectionError("peer_address_mismatch")
            if self.tls:
                # create_default_context honors SSLKEYLOGFILE and may write secrets
                # outside output. Build the verifying client context without that side effect.
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.load_default_certs(ssl.Purpose.SERVER_AUTH)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.verify_flags |= ssl.VERIFY_X509_STRICT | ssl.VERIFY_X509_PARTIAL_CHAIN
                context.set_alpn_protocols(["http/1.1"])
                # Register the wrapped descriptor before any blocking handshake:
                # wrap_socket detaches the raw descriptor, so the watchdog must
                # close the TLS socket rather than the now-empty raw socket.
                sock = context.wrap_socket(sock, server_hostname=self.host,
                                           do_handshake_on_connect=False)
                self.active_socket = sock
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise CollectionError("request_timeout")
                sock.settimeout(remaining)
                sock.do_handshake()
            self.sock = sock
        except BaseException:
            sock.close()
            raise


class PinnedTransport:
    def request(self, url: str, policy: NetworkPolicy, *, user_agent: str,
                timeout: float, max_bytes: int, address_index: int = 0) -> Response:
        started = time.monotonic()
        deadline = started + timeout
        normalized, addresses = policy.resolve(url)
        timeout -= time.monotonic() - started
        if timeout <= 0:
            raise CollectionError("request_timeout")
        parsed = urlsplit(normalized)
        connection = _PinnedConnection(parsed.hostname, 443 if parsed.scheme == "https" else 80,
                                       addresses[address_index % len(addresses)], timeout=timeout, tls=parsed.scheme == "https")
        expired = threading.Event()
        def expire() -> None:
            expired.set()
            connection.abort()
        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
        response = None
        try:
            if expired.is_set():
                raise CollectionError("request_timeout")
            connection.request("GET", parsed.path, headers={"User-Agent": user_agent,
                "Host": parsed.hostname,
                "Accept": "text/html, application/json, text/plain;q=0.8",
                "Accept-Encoding": "identity", "Connection": "close"})
            response = connection.getresponse()
            headers: dict[str, str] = {}
            for key, value in response.getheaders():
                key = key.lower()
                if key in headers and key in {"location", "content-type", "content-length", "content-encoding", "transfer-encoding"}:
                    raise CollectionError("ambiguous_response_headers")
                headers[key] = value
            if response.status != 200:
                return Response(normalized, response.status, headers, b"")
            if ("content-length" in headers and "transfer-encoding" in headers
                    or headers.get("transfer-encoding", "chunked").lower() != "chunked"):
                raise CollectionError("ambiguous_response_headers")
            encoding = headers.get("content-encoding", "identity").lower()
            if encoding != "identity":
                raise CollectionError("compressed_response_unsupported")
            length = headers.get("content-length")
            if length is not None:
                if len(length) > 20 or not length.isascii() or not length.isdigit():
                    raise CollectionError("invalid_content_length")
                if int(length) > max_bytes:
                    raise CollectionError("response_too_large")
            chunks: list[bytes] = []
            size = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CollectionError("request_timeout")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, max_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    raise CollectionError("response_too_large")
            body = b"".join(chunks)
            if length is not None and len(body) != int(length):
                raise CollectionError("incomplete_response")
            if expired.is_set():
                raise CollectionError("request_timeout")
            return Response(normalized, response.status, headers, body)
        except CollectionError:
            raise
        except TimeoutError:
            raise CollectionError("request_timeout") from None
        except ssl.SSLError:
            raise CollectionError("request_timeout" if expired.is_set() else "tls_verification_failed") from None
        except (OSError, http.client.HTTPException, ValueError):
            raise CollectionError("request_timeout" if expired.is_set() else "transport_failed") from None
        finally:
            timer.cancel()
            timer.join()
            if response is not None:
                response.close()
            connection.close()
