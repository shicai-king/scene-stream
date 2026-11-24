"""Audit tracked release inputs without reading ignored weights or credentials."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_DIRS = {'.venv', 'node_modules', 'models', 'checkpoints', 'cache', 'runtime', 'vendor', 'logs', 'artifacts', 'releases', '.aws', '.codex', '.agents'}
BLOCKED_SUFFIXES = {'.pt', '.pth', '.safetensors', '.ckpt', '.pem', '.key', '.log', '.pid', '.tar', '.zip', '.mp4', '.webm'}
PATTERNS = {
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'service token': re.compile(rb'\b(?:hf_[A-Za-z0-9]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b'),
    'credential-bearing URL': re.compile(rb'https?://[^\s/:"\x27]+:[^\s/@"\x27]+@'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true', help='Also scan every reachable Git blob for common credential patterns')
    args = parser.parse_args()
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    failures, count, total = [], 0, 0
    for name in filter(None, paths):
        path = Path(name)
        if (set(path.parts) & BLOCKED_DIRS or path.suffix in BLOCKED_SUFFIXES
                or '.local.' in path.name or path.name == '.env' or path.name.startswith('.env.')
                or path.as_posix() in {'configs/workers.yaml'} or path.parts[:2] == ('results', 'raw')):
            failures.append(f'Private/generated path tracked: {name}')
        source = ROOT / path
        if not source.is_file():
            failures.append(f'Tracked file missing: {name}')
            continue
        data = source.read_bytes()
        count += 1
        total += len(data)
        if len(data) > 1024 * 1024:
            failures.append(f'Tracked file exceeds 1 MiB: {name}')
        for label, pattern in PATTERNS.items():
            if pattern.search(data):
                failures.append(f'{label} pattern: {name}')
    if args.history:
        objects = subprocess.check_output(['git', 'rev-list', '--objects', '--all'], cwd=ROOT).splitlines()
        for entry in objects:
            oid = entry.split(b' ', 1)[0].decode()
            kind = subprocess.check_output(['git', 'cat-file', '-t', oid], cwd=ROOT).strip()
            if kind != b'blob':
                continue
            data = subprocess.check_output(['git', 'cat-file', 'blob', oid], cwd=ROOT)
            for label, pattern in PATTERNS.items():
                if pattern.search(data):
                    failures.append(f'{label} pattern in historical blob {oid}')
    print(json.dumps({'passed': not failures, 'tracked_files': count, 'tracked_bytes': total,
                      'history_scanned': args.history, 'findings': failures}, indent=2))
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
