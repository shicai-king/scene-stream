"""Export a clean committed source tree; never package the workspace recursively."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', type=Path, default=root / 'releases')
args = parser.parse_args()
if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=root).strip():
    parser.error('Commit the intended changes first; ignored runtime files are not included')
subprocess.run(['python3', str(root / 'scripts/check_repository.py'), '--history'], check=True)
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
out = args.output_dir.resolve()
out.mkdir(parents=True, exist_ok=True)
name = 'longlive-rooms-' + commit[:8]
archives = []
for fmt, suffix in [('zip', '.zip'), ('tar.gz', '.tar.gz')]:
    dest = out / (name + suffix)
    subprocess.run(['git', 'archive', '--format=' + fmt, '--prefix=longlive-rooms/', '--output=' + str(dest), 'HEAD'], cwd=root, check=True)
    archives.append(dest)
with zipfile.ZipFile(archives[0]) as archive:
    members = [n for n in archive.namelist() if not n.endswith('/')]
with tarfile.open(archives[1]) as archive:
    assert sorted(members) == sorted(m.name for m in archive if m.isfile())
checksums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in archives}
(out / (name + '.sha256')).write_text(''.join(f'{digest}  {file}\n' for file, digest in checksums.items()))
report = {'commit': commit, 'files': len(members), 'archives': [{'file': p.name, 'bytes': p.stat().st_size, 'sha256': checksums[p.name]} for p in archives]}
(out / (name + '.json')).write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
