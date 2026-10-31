"""One-time dev_02 recovery after a zero-transmission A duplicate guard failure.

No source or ledger mutation, no holdout. The previous failed run is never
deleted, renamed or modified. Execute ONLY with explicit authorization.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from live_v6 import execute, AUTH

def _read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def preflight():
    from stigma_framing.local_corpus import ROOT
    from stigma_framing.eatd_next_budget import NextGuard
    base=ROOT/'results'/'eatd_v6_one_shot'
    old=base/'dev_02'
    new=base/'dev_02_recovery1'
    if not old.is_dir() or new.exists():
        raise ValueError('expected original failed run; recovery output must not exist')
    manifest=_read(old/'manifest.json')
    if manifest.get('case')!='dev_02' or manifest.get('scientific_protocol')!='EATD-v6.1.1-THREE-ROUND-REPAIR2-ONE-SHOT':
        raise ValueError('original run protocol mismatch')
    failed=_read(old/'scientific'/'A'/'failure.json')
    if (failed.get('status')!='failed' or failed.get('arm')!='A'
            or 'duplicate_request_no_replay' not in failed.get('message','')):
        raise ValueError('original run was not the expected pretransmission failure')
    summary=_read(old/'completion_summary.json')
    if summary.get('statuses')!={'A':'failed'}:raise ValueError('unexpected original run completion statuses')
    locked=_read(old/'scientific_output_lock.json')['sha256']
    for rel,digest in locked.items():
        source=old/rel
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
            raise ValueError('original scientific output lock mismatch: '+rel)
    if any((old/'transport').rglob('*.request.json')) or any((old/'transport').rglob('*.response.json')):
        raise ValueError('original run contains transmitted or persisted request/response files')
    ledger=ROOT/'results'/'eatd_next_preparation'/'ledger_v2.json'
    guard=NextGuard(ledger)
    if guard.spent!=7_678_525_000:
        raise ValueError('guarded spending changed since researcher-approved recovery')
    if any(str(k).startswith('v6one_dev_02_') for k in guard.data['entries']):
        raise ValueError('previous dev_02 provider request exists; no automatic recovery')
    return ROOT/'synthetic_benchmark_v1'/'v6_synthetic_cases',new

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--authorize',default='')
    args=parser.parse_args()
    if args.authorize!=AUTH:raise ValueError('explicit authorization required')
    dataset,new=preflight()
    execute('dev_02',dataset,1.00,args.authorize,run_root=new)

if __name__=='__main__':main()
