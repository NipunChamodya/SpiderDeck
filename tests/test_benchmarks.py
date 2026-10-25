"""Opt-in profiler tooling must measure correct synthetic work and preserve data."""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from benchmarks.run import main, worker


def test_benchmark_default_workspace_cleanup_and_optional_retention(tmp_path):
    root = tmp_path / 'output'
    root.mkdir(mode=0o700)
    assert worker('import_csv', root, 4, 'time')['outcome']['records'] == 4
    assert list(root.iterdir()) == []
    result = worker('import_csv', root, 4, 'memory', keep_workloads=True)
    assert result['python_peak_bytes'] > 0
    source = next(root.glob('import_csv-*/synthetic.csv'))
    assert source.stat().st_mode & 0o077 == 0


def test_actual_benchmark_cli_all_jobs_generate_valid_private_report(tmp_path):
    root = tmp_path / 'output'
    root.mkdir(mode=0o700)
    existing = root / 'user-data.txt'
    existing.write_text('KEEP USER DATA')
    completed = subprocess.run([sys.executable, '-B', '-m', 'benchmarks.run', '--rows', '8', '--repeats', '1',
                                '--output-dir', str(root)], check=True, capture_output=True, text=True, timeout=45)
    report_path = Path(completed.stdout.strip())
    report = json.loads(report_path.read_text())
    assert report['status'] == 'ok'
    assert report['environment']['python']
    assert len(report['samples']) == 11
    assert all(sample['status'] == 'ok' for sample in report['samples'])
    assert all(sample['wall_seconds'] >= 0 for sample in report['samples'])
    assert report_path.is_relative_to(root)
    assert report_path.stat().st_mode & 0o077 == 0
    assert list(report_path.parent.iterdir()) == [report_path]
    assert existing.read_text() == 'KEEP USER DATA'
    idle = next(sample for sample in report['samples'] if sample['job'] == 'idle')
    assert idle['outcome']['idle_wall_seconds'] >= 0.5
    assert idle['outcome']['idle_cpu_seconds'] >= 0
    pdf = next(sample for sample in report['samples'] if sample['job'] == 'pdf_limit')
    assert pdf['outcome']['page_wrappers_constructed'] == 2


@pytest.mark.parametrize('timeout', [False, True])
def test_failed_or_timed_out_workers_never_report_success(tmp_path, capsys, timeout):
    if timeout:
        behavior = {'side_effect': subprocess.TimeoutExpired(['worker'], 180)}
    else:
        behavior = {'return_value': subprocess.CompletedProcess(['worker'], 1, 'SECRET_STDOUT', 'SECRET_STDERR')}
    with patch('benchmarks.run.subprocess.run', **behavior):
        assert main(['--rows', '8', '--repeats', '1', '--jobs', 'import_csv', '--output-dir', str(tmp_path)]) == 1
    path = Path(capsys.readouterr().out.strip())
    report = json.loads(path.read_text())
    assert report['status'] == 'failed'
    assert report['samples'][0]['status'] == 'failed'
    assert 'SECRET' not in path.read_text()
    assert not report['summary']


def test_invalid_benchmark_size_does_not_create_output(tmp_path):
    root = tmp_path / 'not-created'
    with pytest.raises(SystemExit) as caught:
        main(['--rows', '0', '--output-dir', str(root)])
    assert caught.value.code == 2
    assert not root.exists()


def test_memory_and_profile_modes_are_distinct(tmp_path):
    peak = worker('import_csv', tmp_path, 4, 'memory')
    assert peak['python_peak_bytes'] > 0
    assert 'profile' not in peak
    profile = worker('import_csv', tmp_path, 4, 'profile')
    assert 'function calls' in profile['profile']
    assert 'python_peak_bytes' not in profile


def test_invalid_programmatic_workloads_cannot_escape_or_create_output(tmp_path):
    from benchmarks.run import child_directory, run
    from security.validators import UnsafePathError
    with pytest.raises(UnsafePathError):
        child_directory(tmp_path, '../escape')
    with pytest.raises(ValueError):
        worker('../escape', tmp_path, 4, 'time')
    root = tmp_path / 'not-created'
    with pytest.raises(ValueError):
        run(root, rows=4, repeats=0, jobs=['import_csv'], mode='time')
    with pytest.raises(ValueError):
        run(root, rows=4, repeats=1, jobs=['import_csv', 'import_csv'], mode='time')
    assert not root.exists()
