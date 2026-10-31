"""Provider-neutral EATD v6: ordinary A, independent ordinary B, one-shot C.

Inject client.call(system=...,user=...,tools=[],schema=...,arm=...,stage=...). 
The existing guarded transport may be used in a separately authorized run; this
module creates NO provider and has NO paid-run CLI. A and B have no EATD imports.
"""
from __future__ import annotations
import json,re,hashlib

QUESTION=('How and under what conditions might relational rather than disability-attribute-bound '
          'descriptions of assistive-technology innovations influence organizational interest '
          'in adopting them? Develop a theoretical explanation and describe how a researcher might investigate it.')
BACKGROUND="""Organizations evaluate innovations using technical fit, quality, perceived usefulness and social interpretations. Descriptions may change which users, situations and meanings become salient. Stigma can shape audiences' evaluations; categories influence expectations and legitimacy. Organizational interests, expertise and risk preferences can also affect selection into descriptions and adoption. Legitimacy, usefulness, attention, and technical fit are plausible but distinct pathways. An observed association does not by itself identify a causal effect or mediator. A credible theory should state what evidence could distinguish its explanation from alternatives."""
COMMON=('You have ONE opportunity to request evidence, containing no more than TWO specific analyses or investigations. '
        'You receive a neutral inventory of EXISTING study datasets and their design/variables, '
        'not results and not a test menu. Ask only for analyses of available datasets. '
        'You may recommend new studies as future research, but the evidence desk cannot perform them. '
        'Describe the evidence you want in ordinary language. Your request will be fulfilled once '
        'when feasible, and you cannot request more evidence afterward.')

def _text(response):
    if not isinstance(response,dict) or not isinstance(response.get('text'),str) or not response['text'].strip():
        raise ValueError('empty_or_invalid_model_response')
    if response.get('tool_calls'): raise ValueError('unexpected_function_calls_for_one_shot_protocol')
    return response['text']

def _parse_baseline_request(text):
    """Last-line JSON list. Natural descriptions, not a list of tool names."""
    matches=list(re.finditer(r'(?im)^\s*EVIDENCE_REQUEST\s*:\s*(\[[^\n]*\])\s*$',text))
    if matches:
        try:return json.loads(matches[-1].group(1))
        except (TypeError,ValueError):return ['invalid request syntax, no evidence']
    # Generous interpretation of an ordinary chatbot's spontaneous test proposals.
    # Only the FIRST two distinct, explicitly proposed analyses count; later ideas
    # cannot be selected after observing results. Do not mine general theoretical
    # assertions or the research question for implied tests.
    candidate=[];seen=set()
    for sentence in re.split(r'(?<=[.!?])\s+|\n+',text):
        sentence=sentence.strip()
        if not re.search(r'\b(i would|we should|i propose|i request|please|could we|can we|test whether|run a|estimate|compare|randomiz\w*|investigate|examine experimentally)\b',sentence,re.I):
            continue
        key=re.sub(r'\s+',' ',sentence.casefold())
        if key in seen:continue
        seen.add(key);candidate.append(sentence[:2400])
        if len(candidate)==2:break
    return candidate

def run_a(client, checkpoint=None):
    answer=_text(client.call(system='You are a helpful assistant.',user=QUESTION,
                             tools=[],schema=None,arm='A',stage='answer'))
    if checkpoint: checkpoint('A_answer',answer)
    return {'initial_final_answer':answer,'evidence_requested':False}

def run_b(client,study,desk,checkpoint=None):
    """No DAGs, critic, schemas, or prescribed hypothesis stages."""
    if desk.used:raise ValueError('desk already used')
    initial=_text(client.call(system='You are a helpful research assistant.',
        user=json.dumps({'question':QUESTION,'conceptual_background':BACKGROUND,'public_study':study,
            'instruction':('Produce your best preliminary theory or ask for evidence. '+COMMON+
               ' At the end write EVIDENCE_REQUEST: ["specific natural-language request", ...], '
               'or EVIDENCE_REQUEST: [] if no evidence is needed. No more than two items. '
               'This is a request to an evidence desk, not a suggested method for theoretical reasoning.')},
             ensure_ascii=False),tools=[],schema=None,arm='B',stage='chat'))
    if checkpoint: checkpoint('B_pre_evidence',initial)
    requests=_parse_baseline_request(initial)
    # Every B attempt irrevocably consumes the evidence opportunity, including no request.
    receipts=desk.request(requests) if requests else desk.request(['invalid or absent evidence request'])
    if not requests: receipts=[] # preserve no-evidence semantics, but desk.used=True
    if checkpoint: checkpoint('B_requested_evidence',{'verbatim_request':requests,'receipts':receipts})
    final=_text(client.call(system='You are a helpful research assistant.',
        user=json.dumps({'question':QUESTION,'public_study':study,'background':BACKGROUND,
            'your_pre_evidence_response':initial,'evidence_receipts':receipts,
            'instruction':'Give your final scientifically defensible explanation. You may not request additional evidence.'},
            ensure_ascii=False),tools=[],schema=None,arm='B',stage='chat'))
    if checkpoint: checkpoint('B_final',final)
    return {'pre_evidence_answer':initial,'verbatim_request':requests,'receipts':receipts,
            'final':final,'model_calls':2}

def _canonical_node(raw, variables):
    """Map explicit study aliases only; otherwise mark a concept as *latent*.

    Never turn an unmeasured hypothetical construct into a measured covariate.
    The original raw request/response is independently saved by the provider.
    """
    if isinstance(raw,dict):
        name=raw.get('id')
        declared=raw.get('type')
        if declared not in ('measured','latent') or not isinstance(name,str):
            raise ValueError('invalid typed DAG node')
    elif isinstance(raw,str):
        name=raw;declared=None
    else:
        raise ValueError('DAG nodes must be strings or explicitly typed nodes')
    key=re.sub(r'[^a-z0-9]+','_',name.strip().lower()).strip('_')
    if not key:raise ValueError('empty DAG node')
    alias={'x':'X','framing':'X','frame':'X','relational_framing':'X',
           'frame_relational':'X','description':'X','framing_assignment':'X',
           'y':'Y','adoption_interest':'Y','expressed_interest':'Y',
           'organizational_adoption_interest':'Y','interest_in_adoption':'Y'}
    measured={v.casefold():v for v in variables}
    mapped=alias.get(key,measured.get(key))
    if declared=='measured' and mapped is None:
        raise ValueError('model explicitly declared an unavailable measured node')
    if declared=='latent' and mapped is not None:
        raise ValueError('contradictory node declaration for measured public variable')
    if mapped is None:
        mapped='latent_'+(key[7:] if key.startswith('latent_') else key)
    if len(mapped)>110:raise ValueError('unreasonably long DAG node identifier')
    return mapped


def _validate_graphs(item,vars):
    """Canonicalize node syntax locally, preserve all original causal *edges*.

    The two primary rivals are selected separately; alternatives are never
    silently deleted from the raw scientific record.
    """
    if not isinstance(item,dict) or not isinstance(item.get('mechanisms'),list) or len(item['mechanisms'])<2:
        raise ValueError('two competing mechanisms required')
    seen=set();signatures=[];variables=set(vars)
    for g in item['mechanisms']:
        if not isinstance(g,dict) or not {'id','description','nodes','edges'}<=set(g):
            raise ValueError('incomplete mechanism')
        nodes=g['nodes'];edges=g['edges'];ident=g['id']
        if not isinstance(ident,str) or not ident.strip() or ident in seen:
            raise ValueError('duplicate mechanisms')
        seen.add(ident)
        if not isinstance(nodes,list) or len(nodes)<2 or not isinstance(edges,list) or not edges:
            raise ValueError('bad DAG nodes or edges')
        conversion={}
        for n in nodes:
            original=n if isinstance(n,str) else n.get('id') if isinstance(n,dict) else None
            if not isinstance(original,str) or not original.strip() or original in conversion:
                raise ValueError('duplicate/invalid source DAG node')
            conversion[original]=_canonical_node(n,variables)
        canon=list(conversion.values())
        if len(canon)!=len(set(canon)):
            raise ValueError('two source DAG nodes collapse to the same measured or latent identifier')
        if not {'X','Y'}<=set(canon):
            raise ValueError('DAG must contain framing X and adoption interest Y')
        pairs=[]
        for edge in edges:
            if (not isinstance(edge,list) or len(edge)!=2 or
                any(not isinstance(n,str) or n not in conversion for n in edge) or edge[0]==edge[1]):
                raise ValueError('bad DAG edges')
            pairs.append([conversion[edge[0]],conversion[edge[1]]])
        if len(set(map(tuple,pairs)))!=len(pairs):raise ValueError('duplicate DAG edge')
        remain=set(canon)
        while remain:
            roots={n for n in remain if not any(u in remain and v==n for u,v in pairs)}
            if not roots:raise ValueError('cyclic DAG')
            remain-=roots
        g['nodes']=canon;g['edges']=pairs
        g['node_types']={n:('measured' if n in variables else 'latent') for n in canon}
        g['canonicalization_audit']=[{'original':old,'canonical':new} for old,new in conversion.items() if old!=new]
        signatures.append(frozenset(map(tuple,pairs)))
    if len(set(signatures))<2:raise ValueError('identical rival DAGs')
    return item


def _priority_pair(mechanisms):
    """PREDECLARED priority rule: first two model-ordered rivals remain live.

    Scientific prompts tell the proposer to put its two strongest rivals first.
    Other candidate graphs are preserved in the archived round response, but
    cannot proliferate into subsequent rounds or receive a post-hoc evidence test.
    """
    if not isinstance(mechanisms,list) or len(mechanisms)<2:
        raise ValueError('missing primary rivals')
    return {'primary':mechanisms[:2],
            'retired_or_deprioritized_ids':[m['id'] for m in mechanisms[2:]],
            'selection_rule':'first_two_model_ranked_before_any_test_results'}


# The scientific proposal has THREE fixed adversarial exchanges before the
# one irreversible evidence request. A "round" is one independent critic call
# followed by one proposer reply. No empirical result is accessible until the
# third proposer reply and its prediction/test choice have been checkpointed.
EATD_ADVERSARIAL_ROUNDS=3


def _validate_single_mechanism(mechanism, variables):
    """Apply the same DAG constraints to a critic's counterproposal."""
    if not isinstance(mechanism,dict):
        raise ValueError('missing countermechanism')
    # _validate_graphs requires two distinct DAGs, so pair this with a
    # synthetic, structurally distinct valid DAG for single-graph validation.
    # This is a deterministic syntax check, not a science-quality score.
    dummy={'id':'__validation_only__','description':'validator placeholder',
           'nodes':['X','Y'],'edges':[['X','Y']]}
    if mechanism.get('id')=='__validation_only__':
        raise ValueError('reserved countermechanism ID')
    if mechanism.get('edges')==dummy['edges'] and set(mechanism.get('nodes',[]))=={'X','Y'}:
        # Equivalent edge signature is checked separately; use reverse edge
        # so a perfectly legitimate X -> Y countermodel is not excluded.
        dummy['edges']=[['Y','X']]
    _validate_graphs({'mechanisms':[mechanism,dummy]},variables)
    return mechanism


def _validate_critic(raw,variables):
    value=json.loads(raw)
    needed={'counter_mechanism','disagreement','contrasting_predictions','rationale','requests','remaining_uncertainty'}
    if not isinstance(value,dict) or set(value)!=needed:
        raise ValueError('bad adversarial challenge structure')
    _validate_single_mechanism(value['counter_mechanism'],variables)
    if (not isinstance(value['requests'],list) or len(value['requests'])>2 or
        not all(isinstance(x,str) and x.strip() for x in value['requests'])):
        raise ValueError('critic proposed invalid evidence candidates')
    for field in needed-{'requests','counter_mechanism'}:
        if not isinstance(value[field],str) or not value[field].strip():
            raise ValueError('missing adversarial scientific reasoning')
    return value


def _validate_proposer(raw,variables,final_round):
    value=json.loads(raw)
    needed={'mechanisms','reply_to_counterargument','changes_or_reason_for_no_change','remaining_uncertainty'}
    if final_round:needed |= {'contrasting_predictions','requests','selection_rationale'}
    if not isinstance(value,dict) or set(value)!=needed:
        raise ValueError('bad proposer response structure')
    _validate_graphs({'mechanisms':value['mechanisms']},variables)
    for field in needed-{'mechanisms','requests'}:
        if not isinstance(value[field],str) or not value[field].strip():
            raise ValueError('missing proposer explanation')
    if final_round:
        if (not isinstance(value['requests'],list) or len(value['requests'])>2 or
            not all(isinstance(x,str) and 8<=len(x)<=2400 for x in value['requests'])):
            raise ValueError('single evidence batch must contain zero to two specific requests')
    return value


# A repair is NOT an additional scientific exchange. It can correct a returned
# malformed JSON / DAG representation, but cannot request evidence or extend the
# three proposer-adversary rounds. This is deliberately separate from provider
# transport errors, whose paid outcome may be uncertain.
C_TECHNICAL_REPAIR_ALLOWANCE=2
TECHNICAL_REPAIR_MARKER='TECHNICAL_REPAIR_ONLY'


def _corrected_c_call(client, *, system, user, schema, stage, validator, state, checkpoint=None):
    """Use one original C call and at most two *global* syntax repairs per run.

    Only responses actually returned by client.call can trigger a repair.
    Exceptions from client.call, including unknown-cost transport outcomes,
    are never intercepted or retried. Each attempted repair is checkpointed.
    """
    response = client.call(system=system,user=user,tools=[],schema=schema,arm='C',stage=stage)
    while True:
        raw = response.get('text','') if isinstance(response,dict) else ''
        try:
            return validator(_text(response))
        except (ValueError,TypeError) as error:
            if state['repairs']>=C_TECHNICAL_REPAIR_ALLOWANCE:
                raise
            state['repairs']+=1
            count=state['repairs']
            # The original context may be large. Use a bounded representation;
            # never replay arbitrary prior conversation, receipts or secret truth.
            repair_system=(TECHNICAL_REPAIR_MARKER+': Correct the invalid structure or '
               'serialization of the PREVIOUS answer for the SAME scientific stage. '
               'Do not introduce new evidence, alter causal claims or submit an '
               'additional experiment. Preserve the original scientific content. '
               'Return only the original required output format.')
            payload={'stage':stage,'original_instruction':system[:1700],
                     'original_input':user[:4600],
                     'invalid_response':str(raw)[:4000],
                     'validation_error':str(error)[:300]}
            repair_user=json.dumps(payload,ensure_ascii=False)
            # Validate against the real 16-kB request limit *before* any call.
            # Lowering the excerpt never increases information visible to C.
            from transport import build_request
            while True:
                try:
                    build_request(repair_system,repair_user,[],schema,'C',stage)
                    break
                except ValueError as exc:
                    if str(exc)!='request_too_large' or len(payload['invalid_response'])<=200:
                        raise
                    payload['invalid_response']=payload['invalid_response'][:len(payload['invalid_response'])//2]
                    repair_user=json.dumps(payload,ensure_ascii=False)
            if checkpoint:
                checkpoint(f'C_technical_repair_{count}',{
                    'stage':stage,'reason':str(error)[:300],
                    'invalid_response_sha256':hashlib.sha256(str(raw).encode()).hexdigest(),
                    'repair_only':True,'evidence_requested':False})
            # This distinct guarded provider request consumes a *technical*
            # allowance. A transport error here fails closed; no automatic retry.
            response=client.call(system=repair_system,user=repair_user,tools=[],
                                 schema=schema,arm='C',stage=stage)


def run_c(client,study,desk,checkpoint=None):
    if desk.used:raise ValueError('desk already used')
    variables=study['variables']
    repair_state={'repairs':0}
    original=_corrected_c_call(client,system=(
        'You are the theory PROPOSER. Develop at least two substantively distinct organizational '
        'explanations, using concise directed acyclic graphs and explicit causal assumptions. '
        'You have no test results or test menu. The public study gives a neutral inventory of '
        'existing datasets; the evidence desk cannot implement new studies. '
        'Do not assume a mechanism is identified. '
        'Return JSON with mechanisms: [{id,description,nodes,edges}] (at least two). '
        'Use X for randomized/observed framing and Y for interest, and measured public variable names exactly. '
        'Other conceptual nodes are latent; the parser will label them as such. '
        'Order mechanisms from strongest to weaker; only the FIRST TWO are primary live rivals.'),
        user=json.dumps({'question':QUESTION,'conceptual_background':BACKGROUND,'public_study':study},ensure_ascii=False),
        schema='mechanisms_json',stage='accounts',validator=lambda raw:_validate_graphs(json.loads(raw),variables),
        state=repair_state,checkpoint=checkpoint)
    if checkpoint:checkpoint('C_pre_evidence_graphs',original)
    initial_priority=_priority_pair(original['mechanisms'])
    if checkpoint:checkpoint('C_initial_priority',initial_priority)
    current={'mechanisms':initial_priority['primary']}
    # The archived mechanisms retain their full content. Model inputs contain
    # the actual DAG and short descriptions, not redundant local audit metadata.
    # This is important now that the public-study context includes a data inventory.
    def _input_graphs(value):
        return {'mechanisms':[
            {'id':m['id'],'description':m['description'][:650],
             'nodes':m['nodes'],'edges':m['edges']}
            for m in value['mechanisms']]}
    rounds=[]
    for round_number in range(1,EATD_ADVERSARIAL_ROUNDS+1):
        # No prior raw transcript, full bibliography, evidence receipts, or
        # available-test names: keep model inputs bounded and independent.
        emphases={1:'Challenge the strongest rival assumption or omitted causal explanation.',
                  2:'Attack the revised explanation on confounding, exclusions, causal timing, or observational equivalence.',
                  3:'Find the strongest unresolved vulnerability and identify what observation would separate the live rivals.'}
        challenge=_corrected_c_call(client,system=(
            'You are an INDEPENDENT adversarial scientific critic, not an ally seeking consensus. '
            'Evaluate only the current TWO PRIMARY graphs. Offer one substantive counterproposal '
            'as an explicit DAG, contrasting predictions, and up to two possible discriminating '
            'evidence ideas LIMITED to analyses of the existing public-study datasets. '
            'You may propose unavailable interventions as future research separately, '
            'but not as evidence-desk requests. You may recommend retaining uncertainty or no-change when justified. '
            'Never claim to have seen test results; no evidence may be requested yet. '
            +emphases[round_number]+
            ' Return JSON with counter_mechanism {id,description,nodes,edges}, disagreement, '
            'contrasting_predictions, rationale, requests (0-2 ordinary-language IDEAS only), '
            'remaining_uncertainty.'),
            user=json.dumps({'question':QUESTION,'public_study':study,
                'round':round_number,'current_proposer_graphs':_input_graphs(current)},ensure_ascii=False),
            schema='challenge_json',stage='challenge',validator=lambda raw:_validate_critic(raw,variables),
            state=repair_state,checkpoint=checkpoint)
        if checkpoint:checkpoint(f'C_round_{round_number}_challenge',challenge)

        final_round=round_number==EATD_ADVERSARIAL_ROUNDS
        proposer_system=(
            'You are the original scientific PROPOSER responding to a genuinely independent '
            'adversarial critique. You must either revise your mechanisms in response to '
            'the causal objection or explain why retaining them is scientifically warranted. '
            'Preserve real uncertainty. Rank the TWO strongest live rival mechanisms FIRST, '
            'explain which weaker alternatives should be deprioritized, and give '
            'scientific reasons for retaining or rejecting the challenge. '
            'Return a full set of at least two distinguishable '
            'DAG mechanisms and a concise, falsifiable answer to the challenge. '
            'No test results exist in your context; do not fabricate them. ')
        if final_round:
            proposer_system+=(
                'This is your THIRD AND FINAL PRE-EVIDENCE response. You now have exactly ONE '
                'irreversible evidence opportunity with at most TWO tests. Select the most '
                'informative feasible analyses of the EXISTING public-study datasets, '
                'in ordinary language, or [] if no available analysis '
                'can distinguish your claims. Freeze clear contrasting predictions BEFORE seeing '
                'any evidence. The critic recommendations are optional, not an executable menu. '
                'Return JSON with mechanisms, reply_to_counterargument, '
                'changes_or_reason_for_no_change, remaining_uncertainty, contrasting_predictions, '
                'requests, selection_rationale.')
        else:
            proposer_system+=(
                'You are NOT allowed to submit an evidence request in this round. '
                'Return JSON with mechanisms, reply_to_counterargument, '
                'changes_or_reason_for_no_change, remaining_uncertainty.')
        revised=_corrected_c_call(client,system=proposer_system,
            user=json.dumps({'question':QUESTION,'round':round_number,'public_study':study,
                'current_proposer_graphs':_input_graphs(current),
                'independent_counterproposal':{**challenge,
                    'counter_mechanism':{k:challenge['counter_mechanism'][k]
                        for k in ('id','description','nodes','edges')}},
                'prior_round_outcomes':[{
                    'round':x['round'],
                    'proposer_update':x['proposer']['changes_or_reason_for_no_change'][:500],
                    'unresolved':x['proposer']['remaining_uncertainty'][:350]
                } for x in rounds]},ensure_ascii=False),
            schema='evidence_decision_json' if final_round else 'revision_json',
            stage='evidence_decision' if final_round else 'revision',
            validator=lambda raw:_validate_proposer(raw,variables,final_round),
            state=repair_state,checkpoint=checkpoint)
        if checkpoint:checkpoint(f'C_round_{round_number}_proposer',revised)
        priority=_priority_pair(revised['mechanisms'])
        if checkpoint:checkpoint(f'C_round_{round_number}_priority',priority)
        rounds.append({'round':round_number,'challenge':challenge,'proposer':revised,
                       'priority':priority})
        current={'mechanisms':priority['primary']}

    final_decision=rounds[-1]['proposer']
    requests=final_decision['requests']
    # Freeze all pre-evidence claims BEFORE touching the test service.
    freeze={'rounds_completed':EATD_ADVERSARIAL_ROUNDS,
            'final_proposer_graphs':current,
            'contrasting_predictions':final_decision['contrasting_predictions'],
            'verbatim_request':requests,
            'selection_rationale':final_decision['selection_rationale'],
            'primary_rival_ids':[m['id'] for m in current['mechanisms']],
            'deprioritized_ids':rounds[-1]['priority']['retired_or_deprioritized_ids']}
    if checkpoint:checkpoint('C_frozen_evidence_decision',freeze)
    receipts=desk.request(requests if requests else ['invalid or absent evidence request'])
    if not requests:receipts=[]
    if checkpoint:checkpoint('C_requested_evidence',{'verbatim_request':requests,'receipts':receipts})

    # Checkpoints retain ALL literal original reports. The adjudicator needs
    # the competing structures and evidence, not multiple verbatim copies of
    # every preceding dissertation-length graph description.
    def compact_mechanisms(value):
        return [{'id':m['id'],'description':m['description'][:420],
                 'nodes':m['nodes'],'edges':m['edges']}
                for m in value['mechanisms']]

    def compact_receipt(value):
        return {k:value[k] for k in ('status','resolved_test','receipt_id','result','reason','no_substitution')
                if k in value}

    final=_corrected_c_call(client,system=(
        'Scientific adjudicator: use the test results to assess the final PRE-EVIDENCE DAGs '
        'as retained, challenged, rejected, or revised. Explain exactly what the evidence '
        'discriminates and what remains unidentified; do not assume statistical null equals '
        'causal zero. Distinguish total effects from mediated mechanisms and note any '
        'assumptions needed for intervention interpretation. A post-evidence change is '
        'legitimate updating but may NOT be presented as an original prediction. '
        'You cannot request any further evidence.'),
        user=json.dumps({'question':QUESTION,
            'public_study':{k:v for k,v in study.items() if k not in ('existing_data','evidence_scope')},
            'initial_rival_graphs':compact_mechanisms(original),
            'final_pre_evidence_primary_graphs':compact_mechanisms(current),
            'frozen_contrasting_predictions':freeze['contrasting_predictions'][:1800],
            'frozen_selection_reason':freeze['selection_rationale'][:700],
            'round_summary':[{'round':x['round'],
                'critic_objection':x['challenge']['disagreement'][:310],
                'proposer_response':x['proposer']['changes_or_reason_for_no_change'][:310],
                'deprioritized_ids':x['priority']['retired_or_deprioritized_ids']}
                for x in rounds],
            'evidence_receipts':[compact_receipt(r) for r in receipts],
            'note':'Full unabridged scientific outputs and evidence requests are frozen in prior checkpoints.'},
            ensure_ascii=False),
        schema=None,stage='adjudicate',validator=lambda raw:raw,
        state=repair_state,checkpoint=checkpoint)
    if checkpoint:checkpoint('C_final',final)
    return {'pre_evidence_graphs':original,
        'pre_evidence_rounds':rounds,
        'primary_rival_selection_rule':'first_two_model_ranked_before_evidence',
        'final_pre_evidence_graphs':current,
        'frozen_challenge':rounds[-1]['challenge'],
        'frozen_evidence_decision':freeze,
        'verbatim_request':requests,'receipts':receipts,
        'final':final,'scientific_calls':1+2*EATD_ADVERSARIAL_ROUNDS+1,
        'repair_calls':repair_state['repairs'],
        'model_calls':1+2*EATD_ADVERSARIAL_ROUNDS+1+repair_state['repairs']}
