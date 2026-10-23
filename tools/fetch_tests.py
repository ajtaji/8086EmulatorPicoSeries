"""Fetch the pinned SingleStepTests 8086 v1 corpus (JSON, gzip) and its metadata.

The corpus is ~180 MB and is not committed: it lands in Diagnostics/upstream/8086-v1
(ignored by git). The licence and a manifest of SHA-256 hashes are committed.
"""
from pathlib import Path
from urllib.request import urlopen
import hashlib, json, sys

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / 'Diagnostics' / 'upstream'
DEST = UP / '8086-v1'
COMMIT = 'e71c68d215a6bb8c356bd4cb3842de3bef345ca9'
BASE = f'https://raw.githubusercontent.com/SingleStepTests/8086/{COMMIT}/v1/'
API = f'https://api.github.com/repos/SingleStepTests/8086/contents/v1?ref={COMMIT}'

def get(url):
    for attempt in range(4):
        try:
            with urlopen(url, timeout=120) as r:
                return r.read()
        except Exception as e:
            err = e
    raise SystemExit(f'download failed after 4 tries: {url}: {err}')

DEST.mkdir(parents=True, exist_ok=True)
listing = json.loads(get(API))
names = sorted(e['name'] for e in listing if e['type'] == 'file')
manifest = {}
for n in names:
    p = DEST / n
    if not p.exists():
        p.write_bytes(get(BASE + n))
    data = p.read_bytes()
    manifest[n] = hashlib.sha256(data).hexdigest()
    print(n, len(data), flush=True)
lic = get(f'https://raw.githubusercontent.com/SingleStepTests/8086/{COMMIT}/LICENSE')
(UP / 'singlestep-8086-LICENSE').write_bytes(lic)
(UP / 'manifest-8086-v1.json').write_text(json.dumps({'commit': COMMIT, 'files': manifest}, indent=1) + '\n')
print('files', len(names))
