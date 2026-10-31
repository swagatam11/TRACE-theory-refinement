"""V6-scoped guarded transport. No v5 files are changed. Provider is injected.

This adapter has NOT been integrated into a Phase 2 coordinator or verified
against a live service. Do not use it until independent review and approval.
"""
import json,re
from pathlib import Path
from transport import build_request,MAX_REQUEST_BYTES,MAX_TOKENS,MAX_CALLS
from schema_v6 import response_format
from arms import C_TECHNICAL_REPAIR_ALLOWANCE,TECHNICAL_REPAIR_MARKER
from stigma_framing.eatd_next_budget import NextGuard
from stigma_framing.ingest import digest
from stigma_framing.pilot import (OUTPUT as PILOT,read_json,write_json,
    input_bytes,reservation_nano,usage_cost)



def _allow_repeated_settled_A(arm,entries):
    """Permit an independent question-only A draw with an identical prompt.

    Identical request bodies are EXPECTED across cases in Arm A: the research
    question is intentionally invariant. This is NOT permission to retry an
    uncertain, failed, incomplete, or same-ID request. The exact request-ID
    replay guard runs separately and first. B/C preserve the old policy.
    """
    return (arm=='A' and bool(entries)
            and all(isinstance(e,dict) and e.get('status')=='ok'
                    and isinstance(e.get('response_id'),str) and e['response_id']
                    for e in entries))

class GuardedTextTransport:
    def __init__(self,*,guard,provider,config,output,case,arm,authorized_ceiling_nano=None):
        if not isinstance(guard,NextGuard): raise ValueError('existing project NextGuard required')
        if arm not in ('A','B','C') or not re.fullmatch(r'[A-Za-z0-9_-]+',case): raise ValueError('invalid identity')
        self.guard,self.provider,self.config,self.output,self.case,self.arm=guard,provider,dict(config),Path(output),case,arm
        self.authorized_ceiling_nano=authorized_ceiling_nano
        if type(authorized_ceiling_nano) is not int or not 0<authorized_ceiling_nano<=20_000_000_000:
            raise ValueError('explicit project spending ceiling required')
        self.output.mkdir(parents=True,exist_ok=True)
        self.arm_ledger=self.output/'arm_token_reservations.json'
        if not self.arm_ledger.exists(): write_json(self.arm_ledger,{'case':case,'arm':arm,'entries':{}})
        self.sequence=0

    def call(self,*,system,user,tools,schema,arm,stage):
        if arm!=self.arm: raise ValueError('arm mismatch')
        # The public scientific payload is logged exactly; no EATD report schema
        # is imposed on A or B. C uses its prompt-defined JSON contract only.
        build_request(system,user,tools,schema,arm,stage)
        is_repair=system.startswith(TECHNICAL_REPAIR_MARKER+':')
        if is_repair and arm!='C':raise ValueError('baseline_repair_protocol_leak')
        output_format=response_format(arm,stage,schema)
        if arm=='A' and (stage!='answer' or tools): raise ValueError('question_only_arm_contaminated')
        if arm=='B' and (stage!='chat' or schema is not None): raise ValueError('baseline_B_contaminated')
        if arm=='C' and stage not in ('empirical','accounts','challenge','revision','evidence_decision','adjudicate'):
            raise ValueError('unknown_EATD_stage')
        if len({t['name'] for t in tools})!=len(tools): raise ValueError('duplicate_tool_definition')
        functions=[{'type':'function','name':v['name'],'description':v['description'],
                    'parameters':{'type':'object','properties':{},'additionalProperties':False},'strict':True} for v in tools]
        body={'model':self.config['model'],'store':False,'service_tier':'default',
              'reasoning':{'effort':self.config['reasoning_effort']},'truncation':'disabled',
              'max_output_tokens':3500 if arm=='C' else 2400,'input':[{'role':'system','content':system},{'role':'user','content':user}],
              'text':{'format':output_format}}
        if functions: body['tools']=functions
        # The only model-visible tool interface is the common public test menu.
        # A and B never receive the EATD JSON schema or a mandated scientific sequence.
        if input_bytes(body)>MAX_REQUEST_BYTES: raise ValueError('request_too_large')
        self.sequence+=1; request_id=f'v6one_{self.case}_{arm}_{self.sequence:02d}'
        request_hash=digest(body); reservation=reservation_nano(body,self.config)
        token_bound=input_bytes(body)+self.config['input_bound_overhead_tokens']+body['max_output_tokens']
        req=self.output/(request_id+'.request.json'); raw=self.output/(request_id+'.response.json')
        # The top-level live_v6.execute owns the exclusive project run lock
        # across all arms. Re-acquiring it here raises FileExistsError because
        # pilot.run_lock uses exclusive file creation and is NOT reentrant.
        if not (PILOT / 'run.lock').is_file():
            raise ValueError('parent_project_run_lock_required')
        self.guard.data=read_json(self.guard.path); self.guard.validate()
        if self.guard.spent+reservation>self.authorized_ceiling_nano: raise ValueError('authorized_budget_limit')
        ledger=read_json(self.arm_ledger)
        if ledger.get('case')!=self.case or ledger.get('arm')!=arm: raise ValueError('arm ledger mismatch')
        old=self.guard.data['entries'].get(request_id)
        if old:
            # Safe conservative behavior: no retransmission of any attempted call.
            raise ValueError('attempted_request_no_replay')
        prior_matching_hashes=[e for e in self.guard.data['entries'].values()
                               if e.get('request_hash')==request_hash]
        if prior_matching_hashes and not _allow_repeated_settled_A(arm,prior_matching_hashes):
            raise ValueError('duplicate_request_no_replay')
        entries=ledger['entries']
        # A=one scientific call; B=two scientific calls; C=eight scientific
        # calls plus up to two TECHNICAL corrections. Never count an extra
        # proposer or critic turn as a correction.
        science_count=sum(not e.get('technical_repair',False) for e in entries.values())
        repair_count=sum(e.get('technical_repair',False) for e in entries.values())
        science_ceiling=1 if arm=='A' else 2 if arm=='B' else MAX_CALLS
        if is_repair:
            if repair_count>=C_TECHNICAL_REPAIR_ALLOWANCE:raise ValueError('arm_repair_call_limit')
        elif science_count>=science_ceiling:
            raise ValueError('arm_scientific_call_limit')
        if len(entries)>=science_ceiling+(C_TECHNICAL_REPAIR_ALLOWANCE if arm=='C' else 0):
            raise ValueError('arm_total_call_limit')
        if any(v['status']!='settled' for v in entries.values()): raise ValueError('unknown_token_outcome')
        if sum(v['charged'] for v in entries.values())+token_bound>MAX_TOKENS: raise ValueError('arm_token_limit')
        if req.exists(): raise ValueError('unreconciled_request')
        write_json(req,body)
        entries[request_id]={'charged':token_bound,'status':'reserved','request_hash':request_hash,
                             'stage':stage,'technical_repair':is_repair};write_json(self.arm_ledger,ledger)
        self.guard.reserve(request_id,reservation,request_hash,role=arm)
        try:
            response=self.provider.responses.create(**body).model_dump(mode='json')
        except Exception:
            self.guard.settle(request_id,reservation,'error_unknown_cost',error={'type':'transport_error'})
            raise RuntimeError('unknown_cost_reservation_retained') from None
        write_json(raw,response)
        try:
            usage=response['usage']; standard,charge=usage_cost(usage,self.config)
            total=usage['total_tokens']
            if type(total) is not int or total!=usage['input_tokens']+usage['output_tokens'] or total>token_bound:
                raise ValueError('usage invalid')
            if charge>reservation: raise ValueError('charge exceeds reservation')
            if response.get('status')!='completed' or not response.get('id'): raise ValueError('response incomplete')
            if response.get('model')!=body['model'] and not response.get('model','').startswith(body['model']+'-'): raise ValueError('unknown model pricing')
            if response.get('service_tier') not in (None,'default'): raise ValueError('unknown service tier')
        except Exception:
            self.guard.settle(request_id,reservation,'error_unknown_cost',response_id=response.get('id'))
            raise ValueError('provider_usage_unknown_reservation_retained') from None
        # A malformed provider response is a scientific-stage failure, not a retry.
        # Settle known usage once and retain the unmodified raw response.
        try:
            chunks=[]; selected=[]
            for unit in response.get('output',[]):
                if unit.get('type')=='function_call':
                    if arm!='B' or unit.get('name') not in {v['name'] for v in tools}:
                        raise ValueError('unknown tool requested')
                    if json.loads(unit.get('arguments','{}'))!={}:
                        raise ValueError('unexpected tool arguments')
                    selected.append(unit['name'])
                for item in unit.get('content',[]):
                    if item.get('type')=='output_text': chunks.append(item['text'])
                    if item.get('type')=='refusal': raise ValueError('provider refusal')
            if not chunks and not selected: raise ValueError('empty provider response')
            if arm=='C' and output_format['type']=='json_schema' and selected:
                raise ValueError('EATD structured stage unexpectedly returned tool calls')
        except (ValueError,TypeError,KeyError) as exc:
            self.guard.settle(request_id,charge,'error',usage=usage,response_id=response['id'],
                              standard_nano=standard,error={'type':type(exc).__name__, 'message':str(exc)[:240]})
            ledger['entries'][request_id].update(status='settled',charged=total)
            write_json(self.arm_ledger,ledger)
            raise
        self.guard.settle(request_id,charge,'ok',usage=usage,response_id=response['id'],standard_nano=standard)
        ledger['entries'][request_id].update(status='settled',charged=total)
        write_json(self.arm_ledger,ledger)
        return {'text':''.join(chunks),'tool_calls':selected}
