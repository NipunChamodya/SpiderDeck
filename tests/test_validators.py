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


def test_url_allows_allowlisted_domain():
    url = validate_url("https://example.com/page", ["example.com"])
    assert url == "https://example.com/page"


def test_subprocess_arg_blocks_injection():
    with pytest.raises(UnsafeArgumentError):
        validate_subprocess_arg("file.csv; rm -rf ~")


def test_subprocess_arg_allows_normal_filename():
    assert validate_subprocess_arg("supervisor_list.csv") == "supervisor_list.csv"
