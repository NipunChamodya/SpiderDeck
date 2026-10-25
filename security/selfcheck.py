"""
security/selfcheck.py
----------------------
Run with: python spiderdeck.py --security-check

This tests SpiderDeck's OWN defenses against a battery of malicious-looking
inputs. It does not contact, scan, or attack any external target — every
input below is handled entirely in-process.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table
from security.filesystem import output_filename
from security.network_policy import NetworkPolicy, approve_target, normalize_url, public_ip

from security.validators import (
    UnsafeArgumentError,
    UnsafePathError,
    UnsafeURLError,
    safe_output_path,
    validate_subprocess_arg,
    validate_url,
)

console = Console()


def _case(label: str, fn, *, expect_pass: bool) -> tuple[str, bool, str]:
    try:
        fn()
        passed = expect_pass
        detail = "allowed (expected)" if expect_pass else "allowed (SHOULD HAVE BLOCKED)"
    except (UnsafePathError, UnsafeURLError, UnsafeArgumentError, ValueError) as e:
        passed = not expect_pass
        detail = f"blocked: {e}" if not expect_pass else f"blocked (SHOULD HAVE PASSED): {e}"
    return label, passed, detail


def run(*, verbose: bool = True, plain: bool = False) -> bool:
    base = Path(__file__).resolve().parent.parent / "output"
    # URL checking here does not resolve DNS or open a socket.
    policy = NetworkPolicy(approve_target('https://research.test/', ['research.test'],
                                         authorized=True), ['research.test'])
    cases = [
        # --- Path traversal: must be BLOCKED ---
        _case(
            "Path traversal (../../etc/passwd)",
            lambda: safe_output_path(base, "../../etc/passwd"),
            expect_pass=False,
        ),
        _case(
            "Path traversal (encoded)",
            lambda: safe_output_path(base, "..\\..\\Windows\\System32"),
            expect_pass=False,
        ),
        # --- Legit relative path: must PASS ---
        _case(
            "Normal output file (results.csv)",
            lambda: safe_output_path(base, "results.csv"),
            expect_pass=True,
        ),
        # --- SSRF targets: must be BLOCKED ---
        _case(
            "SSRF to localhost",
            lambda: validate_url("http://127.0.0.1:8080/admin", ["example.com"]),
            expect_pass=False,
        ),
        _case(
            "SSRF to private 10.x range",
            lambda: validate_url("http://10.0.0.5/internal", ["example.com"]),
            expect_pass=False,
        ),
        _case(
            "SSRF to AWS metadata endpoint",
            lambda: validate_url("http://169.254.169.254/latest/meta-data/", ["example.com"]),
            expect_pass=False,
        ),
        _case(
            "Domain not on allowlist",
            lambda: validate_url("https://evil.example.org/", ["example.com"]),
            expect_pass=False,
        ),
        # --- Legit URL: must PASS ---
        _case(
            "Allowlisted HTTPS domain",
            lambda: validate_url("https://8.8.8.8/page", ["8.8.8.8"]),
            expect_pass=True,
        ),
        # --- Shell injection: must be BLOCKED ---
        _case(
            "Shell metacharacters (; rm -rf)",
            lambda: validate_subprocess_arg("file.csv; rm -rf ~"),
            expect_pass=False,
        ),
        _case(
            "Command substitution ($(...))",
            lambda: validate_subprocess_arg("$(curl evil.com)"),
            expect_pass=False,
        ),
        # --- Legit arg: must PASS ---
        _case(
            "Normal filename argument",
            lambda: validate_subprocess_arg("supervisor_list.csv"),
            expect_pass=True,
        ),
        _case('Live policy: IPv4 loopback', lambda: public_ip('127.0.0.1'), expect_pass=False),
        _case('Live policy: cloud metadata', lambda: public_ip('169.254.169.254'), expect_pass=False),
        _case('Live policy: IPv6 loopback', lambda: public_ip('::1'), expect_pass=False),
        _case('Live policy: IPv6 private', lambda: public_ip('fd00::1'), expect_pass=False),
        _case('Live policy: IPv4-mapped IPv6', lambda: public_ip('::ffff:8.8.8.8'), expect_pass=False),
        _case('Live policy: URL userinfo', lambda: normalize_url('https://user:example@research.test/'), expect_pass=False),
        _case('Live policy: query URL', lambda: normalize_url('https://research.test/?token=example'), expect_pass=False),
        _case('Live policy: invalid scheme', lambda: normalize_url('file:///etc/passwd'), expect_pass=False),
        _case('Live policy: target approval required',
              lambda: approve_target('https://research.test/', ['research.test'], authorized=False), expect_pass=False),
        _case('Live policy: new origin needs approval',
              lambda: policy.check_url('https://other.test/'), expect_pass=False),
        _case('Output publication: traversal filename', lambda: output_filename('../escape.csv'), expect_pass=False),
        _case('Live policy: approved origin path', lambda: policy.check_url('https://research.test/page'), expect_pass=True),
    ]

    table = Table(title="SpiderDeck Security Self-Check")
    table.add_column("Check")
    table.add_column("Result")
    table.add_column("Detail")

    all_passed = True
    for label, passed, detail in cases:
        all_passed &= passed
        mark = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        table.add_row(label, mark, detail)

    if verbose and plain:
        for label, passed, detail in cases:
            print(f"{'PASS' if passed else 'FAIL'} | {label} | {detail}")
    elif verbose:
        console.print(table)
    elif not all_passed:
        for label, passed, detail in cases:
            if not passed:
                print(f"FAIL: {label}: {detail}")
    if all_passed and verbose:
        if plain:
            print("All security checks passed.")
        else:
            console.print("\n[green]All security checks passed.[/green]")
    elif not all_passed:
        print("One or more security checks failed. Do not use SpiderDeck for live crawling until this is fixed.")
    return all_passed


if __name__ == "__main__":
    run()
