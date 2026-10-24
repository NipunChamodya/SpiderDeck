from pathlib import Path

import pytest

from security.validators import (
    UnsafeArgumentError,
    UnsafePathError,
    UnsafeURLError,
    safe_output_path,
    validate_subprocess_arg,
    validate_url,
)


def test_output_path_blocks_traversal(tmp_path):
    with pytest.raises(UnsafePathError):
        safe_output_path(tmp_path, "../../etc/passwd")


def test_output_path_allows_normal_file(tmp_path):
    result = safe_output_path(tmp_path, "results.csv")
    assert result.parent == tmp_path.resolve()


def test_url_blocks_localhost():
    with pytest.raises(UnsafeURLError):
        validate_url("http://127.0.0.1/admin", ["example.com"])


def test_url_blocks_private_range():
    with pytest.raises(UnsafeURLError):
        validate_url("http://10.0.0.5/", ["example.com"])


def test_url_blocks_non_allowlisted_domain():
    with pytest.raises(UnsafeURLError):
        validate_url("https://evil.example.org/", ["example.com"])


def test_url_allows_allowlisted_domain(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))])
    url = validate_url("https://example.com/page", ["example.com"])
    assert url == "https://example.com/page"


def test_subprocess_arg_blocks_injection():
    with pytest.raises(UnsafeArgumentError):
        validate_subprocess_arg("file.csv; rm -rf ~")


def test_subprocess_arg_allows_normal_filename():
    assert validate_subprocess_arg("supervisor_list.csv") == "supervisor_list.csv"


@pytest.mark.parametrize("url,domains", [
    ("https://example.com", []),
    ("https://user:secret@example.com", ["example.com"]),
    ("http://[::1]", ["::1"]),
    ("http://[::ffff:127.0.0.1]", ["::ffff:127.0.0.1"]),
    ("http://0.0.0.0", ["0.0.0.0"]),
])
def test_url_preflight_rejections(url, domains):
    with pytest.raises(UnsafeURLError):
        validate_url(url, domains)


def test_dns_mixed_results_and_failure(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0))])
    with pytest.raises(UnsafeURLError):
        validate_url("https://example.com", ["example.com"])
    def fail(*args, **kwargs):
        raise socket.gaierror("unresolved")
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(UnsafeURLError):
        validate_url("https://example.com", ["example.com"])
