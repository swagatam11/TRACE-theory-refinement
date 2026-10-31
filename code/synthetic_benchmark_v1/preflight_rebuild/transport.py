"""Phase 1 mock transport. No SDK, network or real provider is imported here."""
import copy,json

MAX_REQUEST_BYTES=16000
MAX_OUTPUT_BYTES=12000
MAX_TOKENS=60000
MAX_CALLS=8

def build_request(system,user,tools,schema,arm,stage):
    request={'system':system,'user':user,'tools':tools,'schema':schema,'arm':arm,'stage':stage}
    size=len(json.dumps(request,ensure_ascii=False,sort_keys=True).encode('utf8'))
    if size>MAX_REQUEST_BYTES: raise ValueError('request_too_large')
    return request

def compact_correction(error,invalid_excerpt):
    """Optional minimal error context; never include entire evidence packets."""
    return {'error':str(error)[:240],'invalid_excerpt':str(invalid_excerpt)[:600],
            'instruction':'Correct the indicated syntax or reference only.'}

class MockClient:
    """Simulate cost, uncertain outcome, caps, and exactly captured payloads."""
    def __init__(self,script,*,token_cap=MAX_TOKENS,call_cap=MAX_CALLS):
        self.script=list(script); self.calls=[]; self.tokens=0; self.token_cap=token_cap
        self.call_cap=call_cap; self.unknown_reservation=False
    def call(self,*,system,user,tools,schema,arm,stage):
        if self.unknown_reservation: raise ValueError('unknown_reservation_no_replay')
        if len(self.calls)>=self.call_cap: raise ValueError('call_limit')
        request=build_request(system,user,tools,schema,arm,stage)
        # This is a mock reservation, not provider billing or an estimate of real tokens.
        reserve=len(json.dumps(request,ensure_ascii=False).encode())+2000
        if self.tokens+reserve>self.token_cap: raise ValueError('token_limit')
        self.calls.append(copy.deepcopy(request))
        if not self.script: raise ValueError('mock_script_exhausted')
        result=self.script.pop(0)
        if result=='transport_error': self.unknown_reservation=True; self.tokens+=reserve; raise ConnectionError('unknown_cost_reserved')
        if isinstance(result,Exception): raise result
        if not isinstance(result,dict): raise ValueError('invalid_provider_response')
        if len(json.dumps(result,ensure_ascii=False).encode())>MAX_OUTPUT_BYTES: raise ValueError('response_too_large')
        used=result.get('mock_tokens',100)
        if type(used) is not int or used<0 or used>reserve: self.unknown_reservation=True; raise ValueError('invalid_usage')
        self.tokens+=used
        return copy.deepcopy(result)

class LiveTransportUnavailable:
    """Hard Phase 1 interlock; never falls back to an unguarded provider."""
    def call(self,**kwargs):
        raise RuntimeError('Live transport is not implemented or authorized: use existing $20 NextGuard under an exclusive run lock after independent review.')
