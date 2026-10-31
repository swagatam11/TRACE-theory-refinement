"""V6 single-case gated live runner. Default `inspect` is OFFLINE.

No API calls unless explicit `live` + authorization token. Holdout forbidden here;
separate protocol freeze/authorization is needed before holdout execution.
"""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
from arms import run_a,run_b,run_c,EATD_ADVERSARIAL_ROUNDS,C_TECHNICAL_REPAIR_ALLOWANCE
from evidence_desk import OneShotEvidenceDesk

ROOT_DIR=Path(__file__).resolve().parent
AUTH='AUTHORIZE_V6_ONE_CASE_PAID_RUN'

def _dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise ValueError('existing output, no replay: '+str(path))
    path.write_text(json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False)+'\n',encoding='utf8')

def check_public(root,case):
    root=Path(root).resolve()
    if 'private' in {p.lower() for p in root.parts}:raise ValueError('private path forbidden')
    if not case.startswith('dev_') or len(case)!=6:raise ValueError('only named development case is permitted')
    pub=root/'public';manifest=json.loads((pub/'manifest.json').read_text(encoding='utf8'))
    if manifest.get('version')!='EATD-V6-ONE-SHOT':raise ValueError('wrong dataset version')
    matching=[x for x in manifest['cases'] if x['case_id']==case and x['partition']=='development']
    if len(matching)!=1:raise ValueError('case missing from frozen manifest')
    study_dir=(pub/'development'/case).resolve()
    if not study_dir.is_relative_to(pub):raise ValueError('unsafe public case path')
    for name,want in matching[0]['files_sha256'].items():
        f=study_dir/name
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=want:raise ValueError('public hash mismatch')
    return study_dir

def execute(case,root,cap,authorization,run_root=None):
    if authorization!=AUTH:raise ValueError('live run not authorized')
    if not math.isfinite(cap) or not 0<cap<=1.0:raise ValueError('additional live cap must be positive and <=1 USD')
    from stigma_framing.local_corpus import ROOT
    from stigma_framing.eatd_next_budget import NextGuard
    from stigma_framing.pilot import OUTPUT as PILOT,load_client,run_lock
    from guarded_provider_v6 import GuardedTextTransport
    from transport import MAX_CALLS,MAX_TOKENS
    if EATD_ADVERSARIAL_ROUNDS!=3 or MAX_CALLS!=8 or C_TECHNICAL_REPAIR_ALLOWANCE!=2 or MAX_TOKENS<60000:
        raise ValueError('three_round_protocol_budget_mismatch')
    public=check_public(root,case)
    run_dir=(ROOT/'results'/'eatd_v6_one_shot'/case).resolve() if run_root is None else Path(run_root).resolve()
    if not run_dir.is_relative_to((ROOT/'results').resolve()):raise ValueError('run must be inside project results')
    if run_dir.exists():raise ValueError('existing run directory, manual reconciliation, no replay')
    config=json.loads((ROOT/'synthetic_benchmark_v1'/'preflight_rebuild'/'phase2_config.json').read_text(encoding='utf8'))
    ledger=ROOT/'results'/'eatd_next_preparation'/'ledger_v2.json'
    with run_lock(PILOT):
        guard=NextGuard(ledger)
        start=guard.spent;ceil=min(20_000_000_000,start+round(cap*1e9))
        if ceil<=start:raise ValueError('no authorized budget available')
        provider=load_client(config)
        run_dir.mkdir(parents=True)
        _dump(run_dir/'manifest.json',{'case':case,'partition':'development','dataset':'EATD-V6-ONE-SHOT',
              'source_manifest_sha256':hashlib.sha256((Path(root)/'public'/'manifest.json').read_bytes()).hexdigest(),
              'authorized_additional_nano':round(cap*1e9),'guarded_start_nano':start,'guarded_ceiling_nano':ceil,
              'no_retries':True,'no_holdout':True,
              'scientific_protocol':'EATD-v6.3-DATA-INVENTORY-ONE-SHOT',
              'technical_repairs_C_max':C_TECHNICAL_REPAIR_ALLOWANCE,
              'scientific_calls_C':8,'technical_repair_only':True,
              'adversarial_rounds_C':EATD_ADVERSARIAL_ROUNDS,
              'max_model_calls_total':{'A':1,'B':2,'C':8+C_TECHNICAL_REPAIR_ALLOWANCE},
              'pre_evidence_and_final_model_calls':{'A':1,'B':2,'C':8},
              'evidence_opportunities_per_arm':{'A':0,'B':1,'C':1},
              'max_tests_in_single_batch':2,
              'arms_sha256':hashlib.sha256((ROOT_DIR/'arms.py').read_bytes()).hexdigest(),
              'schema_sha256':hashlib.sha256((ROOT_DIR/'schema_v6.py').read_bytes()).hexdigest(),
              'evidence_desk_sha256':hashlib.sha256((ROOT_DIR/'evidence_desk.py').read_bytes()).hexdigest()})
        status={}
        for arm,handler in (('A',run_a),('B',run_b),('C',run_c)):
            out=run_dir/'scientific'/arm
            def checkpoint(stage,record):_dump(out/(stage+'.json'),{'stage':stage,'record':record})
            transport=GuardedTextTransport(guard=guard,provider=provider,config=config,
                output=run_dir/'transport'/arm,case=case,arm=arm,authorized_ceiling_nano=ceil)
            try:
                desk=None if arm=='A' else OneShotEvidenceDesk(public)
                answer=handler(transport,checkpoint=checkpoint) if arm=='A' else handler(transport,desk.disclose(),desk,checkpoint=checkpoint)
                _dump(out/'result.json',{'status':'completed','arm':arm,'answer':answer})
                if desk is not None:_dump(out/'evidence_desk_log.json',{'request':desk.locked_request,'receipts':desk.receipts})
                status[arm]='completed'
            except Exception as exc:
                _dump(out/'failure.json',{'status':'failed','arm':arm,'exception_class':type(exc).__name__,
                                          'message':str(exc)[:500]})
                status[arm]='failed'
                break  # Never proceed to another arm after failure.
        scientific={p.relative_to(run_dir).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                    for base in (run_dir/'scientific',run_dir/'transport') if base.exists()
                    for p in base.rglob('*.json')}
        _dump(run_dir/'scientific_output_lock.json',{'sha256':scientific,'status':'immutable_artifacts_locked'})
        _dump(run_dir/'completion_summary.json',{'case':case,'statuses':status,'guarded_end_nano':guard.spent,
                'science_locked':True,'no_unblinding':True})
        print(json.dumps({'statuses':status,'guarded_additional_nano':guard.spent-start},indent=2))
        return status

def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['inspect','live'])
    p.add_argument('--case',required=True)
    p.add_argument('--dataset',required=True)
    p.add_argument('--max-additional-usd',type=float,default=0.)
    p.add_argument('--authorize',default='')
    a=p.parse_args()
    directory=check_public(a.dataset,a.case)
    if a.action=='inspect':
        desk=OneShotEvidenceDesk(directory)
        print(json.dumps({'status':'offline_only','case':a.case,'card':desk.disclose(),
            'evidence_request_used':desk.used,'paid_calls':0},indent=2));return
    execute(a.case,a.dataset,a.max_additional_usd,a.authorize)
if __name__=='__main__':main()
