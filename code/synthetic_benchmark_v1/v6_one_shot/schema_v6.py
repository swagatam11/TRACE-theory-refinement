"""EATD C-only strict JSON schema; no baseline uses this file."""
STRING={'type':'string'}
LIST={'type':'array','items':STRING}
MECHANISM={'type':'object','additionalProperties':False,
 'properties':{'id':STRING,'description':STRING,'nodes':LIST,
    'edges':{'type':'array','items':{'type':'array','items':STRING}}},
 'required':['id','description','nodes','edges']}
SCHEMAS={
 'mechanisms_json':{'type':'object','additionalProperties':False,
   'properties':{'mechanisms':{'type':'array','items':MECHANISM}},'required':['mechanisms']},
 'challenge_json':{'type':'object','additionalProperties':False,
   'properties':{'counter_mechanism':MECHANISM,'disagreement':STRING,
                 'contrasting_predictions':STRING,'rationale':STRING,
                 'requests':LIST,'remaining_uncertainty':STRING},
   'required':['counter_mechanism','disagreement','contrasting_predictions','rationale','requests','remaining_uncertainty']},
 'revision_json':{'type':'object','additionalProperties':False,
   'properties':{'mechanisms':{'type':'array','items':MECHANISM},
       'reply_to_counterargument':STRING,'changes_or_reason_for_no_change':STRING,
       'remaining_uncertainty':STRING},
   'required':['mechanisms','reply_to_counterargument','changes_or_reason_for_no_change','remaining_uncertainty']},
 'evidence_decision_json':{'type':'object','additionalProperties':False,
   'properties':{'mechanisms':{'type':'array','items':MECHANISM},
       'reply_to_counterargument':STRING,'changes_or_reason_for_no_change':STRING,
       'remaining_uncertainty':STRING,'contrasting_predictions':STRING,
       'requests':LIST,'selection_rationale':STRING},
   'required':['mechanisms','reply_to_counterargument','changes_or_reason_for_no_change',
       'remaining_uncertainty','contrasting_predictions','requests','selection_rationale']}}

def response_format(arm,stage,schema):
    if arm in ('A','B'):
        if schema is not None:raise ValueError('baseline_schema_leak')
        return {'type':'text'}
    if arm!='C':raise ValueError('unknown arm')
    required={'accounts':'mechanisms_json','challenge':'challenge_json',
              'revision':'revision_json','evidence_decision':'evidence_decision_json'}
    if stage in required and schema!=required[stage]:raise ValueError('missing_eatd_schema')
    if stage not in required and schema is not None:raise ValueError('spurious_eatd_schema')
    if schema is None:return {'type':'text'}
    return {'type':'json_schema','name':schema,'strict':True,'schema':SCHEMAS[schema]}
