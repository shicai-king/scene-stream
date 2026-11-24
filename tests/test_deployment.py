"""Deployment safety checks run without Docker or a GPU."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/render_scope_deployment.py'


def prepare(path):
    (path / 'configs').mkdir()
    shutil.copy(ROOT / 'configs/workers.example.yaml', path / 'configs/workers.example.yaml')


def render(path, *args):
    return subprocess.run([sys.executable, str(SCRIPT), '--gpu-ids', '1,2', *args], cwd=path, capture_output=True, text=True)


def test_deployment_isolation_and_overwrite_guard(tmp_path):
    prepare(tmp_path)
    result = render(tmp_path)
    assert result.returncode == 0, result.stderr
    config_path = tmp_path / 'compose.scope.local.yaml'
    first = config_path.read_bytes()
    compose = yaml.safe_load(first)
    mock = yaml.safe_load((ROOT / 'compose.yaml').read_text())
    assert mock['name'] != compose['name']
    assert compose['services']['hub']['ports'] == ['127.0.0.1:8080:8080']
    for i, gpu in enumerate(['1', '2'], 1):
        worker = compose['services'][f'worker-{i}']
        assert worker['deploy']['resources']['reservations']['devices'][0]['device_ids'] == [gpu]
        assert 'ports' not in worker
        assert not any('docker.sock' in v for v in worker['volumes'])
        assert worker['environment']['HF_HUB_OFFLINE'] == '1'
    assert render(tmp_path, '--port', '18080').returncode != 0
    assert config_path.read_bytes() == first
    assert render(tmp_path, '--port', '18080', '--force').returncode == 0


def test_shared_runtime_mounts_and_startup_budget(tmp_path):
    prepare(tmp_path)
    runtime = tmp_path / 'runtime'
    for name in ['python/cpython-3.12.8-linux-x86_64-gnu/bin/python3.12', 'hub-env/bin/python', 'scope-env/bin/python']:
        p = runtime / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
    result = render(tmp_path, '--runtime-root', str(runtime), '--worker-startup-timeout', '300')
    assert result.returncode == 0, result.stderr
    compose = yaml.safe_load((tmp_path / 'compose.scope.local.yaml').read_text())
    workers = yaml.safe_load((tmp_path / 'configs/workers.local.yaml').read_text())
    assert workers['worker_startup_timeout_s'] == 300
    for service in compose['services'].values():
        assert service['environment']['NO_PROXY'] == '*'
        assert service['environment']['USER'] == 'longlive'
        assert service['build']['dockerfile'] == 'deploy/Dockerfile.runtime'
        assert all(v.endswith(':ro') for v in service['volumes'] if str(runtime) in v)
    assert compose['services']['worker-1']['environment']['WORKER_STARTUP_TIMEOUT_S'] == '300'
    assert compose['services']['worker-1']['healthcheck']['start_period'] == '300s'


@pytest.mark.parametrize('args', [('--width', '385'), ('--port', '65536'), ('--first-frame-timeout', '0')])
def test_invalid_deployment_does_not_write_config(tmp_path, args):
    prepare(tmp_path)
    assert render(tmp_path, *args).returncode != 0
    assert not (tmp_path / 'compose.scope.local.yaml').exists()
    assert not (tmp_path / 'configs/workers.local.yaml').exists()
