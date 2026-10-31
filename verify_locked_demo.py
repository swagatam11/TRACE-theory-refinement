"""Verify public scientific outputs against hashes from the original full lock."""
from pathlib import Path
import hashlib,json
base=Path(__file__).resolve().parent/'demo_locked'/'dev_03'
lock=json.loads((base/'PUBLIC_SCIENCE_LOCK.json').read_text())
for name,want in lock['sha256'].items():
    path=base/name
    if not path.is_file():raise SystemExit('MISSING '+name)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=want:raise SystemExit('MISMATCH '+name)
print('PASS:',len(lock['sha256']),'scientific artifact hashes verified')
