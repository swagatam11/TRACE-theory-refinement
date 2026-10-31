"""OPTIONAL zero-provider replay against the already locked dev_02 recovery.

This verifies code acceptance and request-size feasibility of historical responses,
NOT what a fresh model would reply to changed prompts. Never touches any ledger.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from arms import run_c
from evidence_desk import OneShotEvidenceDesk
from transport import build_request


class ReplayClient:
    def __init__(self,replies):self.replies=list(replies);self.calls=[]
    def call(self,**kwargs):
        build_request(kwargs['system'],kwargs['user'],kwargs['tools'],kwargs['schema'],kwargs['arm'],kwargs['stage'])
        self.calls.append(kwargs)
        if not self.replies:raise AssertionError('replay exhausted responses')
        return {'text':self.replies.pop(0),'tool_calls':[]}


def raw_response_text(source):
    j=json.loads(source.read_text(encoding='utf8'))
    return ''.join(c.get('text','') for v in j['output'] if v.get('type')=='message'
                   for c in v.get('content',[]))


def replay(results,public):
    run=Path(results).resolve();pub=Path(public).resolve()
    lock=json.loads((run/'scientific_output_lock.json').read_text(encoding='utf8'))
    for relative,expected in lock['sha256'].items():
        path=(run/relative).resolve()
        if not path.is_relative_to(run) or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('historical scientific-lock integrity mismatch')
    requests=json.loads((run/'scientific/B/B_requested_evidence.json').read_text(encoding='utf8'))['record']['verbatim_request']
    desk=OneShotEvidenceDesk(pub); b_receipts=desk.request(requests)
    if [x['status'] for x in b_receipts]!=['ok','infeasible']:
        raise AssertionError('B historical evidence incorrectly interpreted')
    original=run/'transport/C'
    seq=(1,2,3,5,6,8,9) # 04/07 were prior repair calls, not new scientific stages
    replies=[raw_response_text(original/f'v6one_dev_02_C_{n:02d}.response.json') for n in seq]
    replies.append('Evidence-dependent conclusions remain constrained by unavailable interventions.')
    client=ReplayClient(replies);marks={};cd=OneShotEvidenceDesk(pub)
    result=run_c(client,cd.disclose(),cd,lambda k,v:marks.__setitem__(k,v))
    if len(client.calls)!=8 or result['repair_calls']!=0 or not cd.used:
        raise AssertionError('C replay failed bounded workflow')
    if len(result['final_pre_evidence_graphs']['mechanisms'])!=2:
        raise AssertionError('C did not narrow live rivals to two')
    if len(marks['C_round_3_proposer']['mechanisms'])!=5:
        raise AssertionError('Historical extra theories were not preserved')
    if len(result['receipts'])!=2 or any(r['status']!='infeasible' for r in result['receipts']):
        raise AssertionError('C requests were incorrectly substituted')
    return {'locked_archive_integrity':'pass','B_receipts':[r['status'] for r in b_receipts],
            'C_stage_calls':len(client.calls),'C_repairs':result['repair_calls'],
            'C_live_rivals':len(result['final_pre_evidence_graphs']['mechanisms']),
            'C_original_final_rivals':len(marks['C_round_3_proposer']['mechanisms']),
            'C_receipts':[r['status'] for r in result['receipts']],
            'provider_calls':0,'note':'Historical raw responses tested offline, not new scientific evidence.'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--results',required=True)
    parser.add_argument('--public-case',required=True)
    a=parser.parse_args();print(json.dumps(replay(a.results,a.public_case),indent=2))
if __name__=='__main__':main()
