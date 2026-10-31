"""Separate $20 guard and bounded Responses transport for the next run.

Callers must hold the historical pilot run lock across reserve and settlement.
"""
import copy
import json
import re
from pathlib import Path
from .local_corpus import ROOT, file_hash, project_path
from .pilot import (read_json, write_json, now, reservation_nano, usage_cost,
                    response_text, load_client, input_bytes)
from .ingest import digest

CAP_NANO = 20_000_000_000
HISTORICAL = (ROOT/'results/pilot_v1/ledger.json', ROOT/'results/challenge_v1/ledger.json',
              ROOT/'results/eatd_v1/ledger.json')


class NextGuard:
    def __init__(self, path, historical=HISTORICAL):
        self.path = project_path(path, 'results')
        self.historical = tuple(project_path(p, 'results') for p in historical)
        if len(self.historical) != 3 or len(set(self.historical)) != 3 or self.path in self.historical:
            raise ValueError('three distinct historical ledgers are required')
        self.data = read_json(self.path)
        if self.data.get('budget_nano') != CAP_NANO:
            raise ValueError('next-run cumulative cap must be $20')
        self.validate()

    @staticmethod
    def _sum(ledger):
        entries = ledger.get('entries')
        if not isinstance(entries, dict):
            raise ValueError('missing ledger entries')
        values = [e.get('charged_nano') for e in entries.values()]
        if any(type(n) is not int or n < 0 for n in values):
            raise ValueError('missing or invalid historical charges')
        return sum(values)

    def validate(self):
        for path in self.historical:
            relative = path.relative_to(ROOT).as_posix()
            if file_hash(path) != self.data['historical_sha256'].get(relative):
                raise ValueError('historical ledger changed; stop for reconciliation')
            old = read_json(path)
            if old.get('budget_nano') != 10_000_000_000:
                raise ValueError('unexpected historical budget; stop for reconciliation')
            self._sum(old)
        return True

    @property
    def spent(self):
        self.validate()
        return self._sum(self.data) + sum(self._sum(read_json(path)) for path in self.historical)

    def reserve(self, request_id, nano, request_hash, role=None):
        self.data = read_json(self.path)
        if self.data.get('budget_nano') != CAP_NANO:
            raise ValueError('next-run cumulative cap changed')
        if not request_id or request_id in self.data['entries']:
            raise ValueError('duplicate/invalid request; no replay')
        if type(nano) is not int or nano <= 0:
            raise ValueError('invalid reservation')
        if self.spent + nano > CAP_NANO:
            raise ValueError('cumulative $20 guard would be exceeded')
        self.data['entries'][request_id] = {'status':'reserved_unknown_outcome','charged_nano':nano,
            'reserved_nano':nano,'request_hash':request_hash,'started_utc':now(),'role':role}
        write_json(self.path, self.data)

    def settle(self, request_id, nano, status, **details):
        self.data = read_json(self.path)
        if self.data.get('budget_nano') != CAP_NANO:
            raise ValueError('next-run cumulative cap changed')
        if type(nano) is not int or nano < 0:
            raise ValueError('invalid charge')
        entry = self.data['entries'][request_id]
        if entry['status'] != 'reserved_unknown_outcome':
            raise ValueError('attempt already settled')
        if nano > entry['reserved_nano']:
            # Persist actual charge, never hide an overrun.
            entry.update(details, status='cost_warning', charged_nano=nano, finished_utc=now())
            write_json(self.path, self.data)
            raise ValueError('actual charge exceeded reservation; stop')
        entry.update(details, status=status, charged_nano=nano, finished_utc=now())
        write_json(self.path, self.data)


def initialize(path, historical=HISTORICAL):
    path = project_path(path, 'results')
    if path.exists():
        return NextGuard(path, historical)
    hashes = {project_path(p, 'results').relative_to(ROOT).as_posix():file_hash(p) for p in historical}
    write_json(path, {'budget_nano':CAP_NANO,'entries':{},'historical_sha256':hashes,
                      'authority':'Researcher authorized $20 cumulative total; platform limit separately unresolved.'})
    return NextGuard(path, historical)


class NextTransport:
    """Checkpointed, bounded Responses transport; caller holds shared run lock.

    ``policy`` is a dictionary keyed by stage role. Each rule has ``max_calls``,
    ``max_output_tokens``, ``max_request_bytes``, ``max_stage_nano`` and may
    specify ``system_sha256`` and ``schema_sha256`` (canonical ``digest`` values).
    Config and policy are frozen on first construction. ``validator`` receives a
    parsed JSON object, returning its validated JSON-serializable form. Separate
    orchestration enforces source visibility and semantic-stage contracts.
    """
    def __init__(self, output, config, policy, guard, client=None):
        self.output = project_path(output, 'results')
        self.output.mkdir(parents=True, exist_ok=True)
        self.config, self.policy, self.guard, self.client = copy.deepcopy(config), copy.deepcopy(policy), guard, client
        for name, value in [('transport_config.json',config), ('transport_policy.json',policy)]:
            path = self.output/name
            if path.exists():
                if read_json(path) != value:
                    raise ValueError('frozen transport configuration differs')
            else:
                write_json(path,value)

    def _validate_body(self, request_id, role, body):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', request_id):
            raise ValueError('invalid request identifier')
        if role not in self.policy:
            raise ValueError('undeclared request role')
        rule = self.policy[role]
        for key in ('max_calls','max_output_tokens','max_request_bytes','max_stage_nano'):
            if type(rule.get(key)) is not int or rule[key] <= 0:
                raise ValueError('invalid stage budget: '+key)
        if set(body) != {'model','store','service_tier','reasoning','truncation','max_output_tokens','input','text'}:
            raise ValueError('unsupported request fields')
        if (body['model'] != self.config['model'] or body['store'] is not False
                or body['service_tier'] != 'default' or body['truncation'] != 'disabled'
                or body['reasoning'] != {'effort':self.config['reasoning_effort']}):
            raise ValueError('request model/settings violate frozen contract')
        if type(body['max_output_tokens']) is not int or not 0 < body['max_output_tokens'] <= rule['max_output_tokens']:
            raise ValueError('request exceeds frozen output ceiling')
        size = input_bytes(body)
        if size > rule['max_request_bytes'] or size + self.config['input_bound_overhead_tokens'] > 272000:
            raise ValueError('request exceeds frozen input/short-context bound')
        messages = body['input']
        if (not isinstance(messages,list) or len(messages) != 2
                or [m.get('role') for m in messages] != ['system','user']
                or any(set(m) != {'role','content'} or not isinstance(m['content'],str) for m in messages)):
            raise ValueError('request must use a fresh system/user context')
        form = body['text'].get('format',{}) if isinstance(body['text'],dict) else {}
        if form.get('type') != 'json_schema' or form.get('strict') is not True:
            raise ValueError('structured output contract required')
        if rule.get('system_sha256') and digest(messages[0]['content']) != rule['system_sha256']:
            raise ValueError('system template differs from frozen rule')
        if rule.get('schema_sha256') and digest(form.get('schema')) != rule['schema_sha256']:
            raise ValueError('output schema differs from frozen rule')
        return rule

    def _cost(self, response):
        usage = response.get('usage') or {}
        standard, guarded = usage_cost(usage, self.config)
        if usage.get('total_tokens') != usage['input_tokens'] + usage['output_tokens']:
            raise ValueError('invalid usage total')
        reasoning = (usage.get('output_tokens_details') or {}).get('reasoning_tokens',0)
        if type(reasoning) is not int or not 0 <= reasoning <= usage['output_tokens']:
            raise ValueError('invalid reasoning-token partition')
        return standard, guarded

    def call(self, request_id, role, body, validator, context):
        """Materialize and reserve before sending; never replay attempted calls."""
        if (read_json(self.output/'transport_config.json') != self.config
                or read_json(self.output/'transport_policy.json') != self.policy):
            raise ValueError('frozen transport configuration changed')
        self.guard.data = read_json(self.guard.path)
        self.guard.validate()
        rule = self._validate_body(request_id,role,body)
        if not isinstance(context,dict):
            raise ValueError('visibility context must be an object')
        request_hash = digest(body)
        for path,value in [(self.output/'raw'/(request_id+'.request.json'),body),
                           (self.output/'contexts'/(request_id+'.json'),
                            {'role':role,'request_hash':request_hash,'visibility':context})]:
            if path.exists():
                if read_json(path) != value:
                    raise ValueError('frozen request or context changed')
            else:
                write_json(path,value)
        parsed_path = self.output/'parsed'/(request_id+'.json')
        self.guard.data = read_json(self.guard.path)
        old = self.guard.data['entries'].get(request_id)
        if old:
            raw_path = self.output/'raw'/(request_id+'.response.json')
            if (old.get('status') == 'reserved_unknown_outcome' and raw_path.exists()
                    and old.get('request_hash') == request_hash and old.get('role') == role):
                # A completed envelope survived a process interruption. Settle it
                # offline; never transmit an attempted request again.
                return self._finish(request_id,role,body,validator,read_json(raw_path),
                                    request_hash,old['reserved_nano'],parsed_path)
            if old.get('status') != 'ok' or old.get('request_hash') != request_hash or old.get('role') != role:
                raise ValueError('previous failed/unknown attempt cannot be replayed')
            if not parsed_path.exists():
                raise ValueError('settled request missing parsed checkpoint')
            record = read_json(parsed_path)
            raw = read_json(self.output/'raw'/(request_id+'.response.json'))
            parsed = validator(json.loads(response_text(raw)))
            if (record.get('status') != 'ok' or record.get('request_hash') != request_hash
                    or record.get('payload') != parsed or record.get('response_id') != raw.get('id')
                    or old.get('response_id') != raw.get('id') or record.get('usage') != raw.get('usage')
                    or old.get('charged_nano') != self._cost(raw)[1]):
                raise ValueError('cached request/response/ledger mismatch')
            return parsed
        if any(e.get('request_hash') == request_hash for e in self.guard.data['entries'].values()):
            raise ValueError('identical request body was already attempted under another ID')
        entries = [e for e in self.guard.data['entries'].values() if e.get('role') == role]
        if len(entries) >= rule['max_calls']:
            raise ValueError('stage call ceiling reached')
        reserve = reservation_nano(body,self.config)
        if sum(e['charged_nano'] for e in entries) + reserve > rule['max_stage_nano']:
            raise ValueError('stage budget would be exceeded')
        self.guard.reserve(request_id,reserve,request_hash,role=role)
        try:
            if self.client is None:
                self.client = load_client(self.config)
            response = self.client.responses.create(**body).model_dump(mode='json')
        except Exception as exc:
            error = {'type':type(exc).__name__, 'message':'Transport failure; full reservation retained; no automatic retry.'}
            write_json(parsed_path, {'status':'error_unknown_cost','request_hash':request_hash,'error':error})
            self.guard.settle(request_id,reserve,'error_unknown_cost',error=error)
            raise ValueError('transport failed; reservation retained') from None
        write_json(self.output/'raw'/(request_id+'.response.json'),response)
        return self._finish(request_id,role,body,validator,response,request_hash,reserve,parsed_path)

    def _finish(self, request_id, role, body, validator, response, request_hash, reserve, parsed_path):
        """Settle either the fresh response or a preserved interrupted envelope."""
        returned_model = response.get('model','')
        if ((returned_model != body['model'] and not returned_model.startswith(body['model']+'-'))
                or response.get('service_tier','default') not in (None,'default')):
            # Unknown model/tier pricing cannot be settled at the configured rate.
            # Retain the full reservation and stop; even that is not an invoice.
            error={'type':'unexpected_model_or_tier',
                   'message':'Pricing may differ; full reservation retained and execution stopped.'}
            write_json(parsed_path, {'status':'error_unknown_cost','request_hash':request_hash,
                                      'response_id':response.get('id'),'error':error})
            self.guard.settle(request_id,reserve,'error_unknown_cost',error=error,
                              response_id=response.get('id'))
            raise ValueError('unexpected model or service tier; cost unknown')
        try:
            standard, charge = self._cost(response)
        except Exception:
            write_json(parsed_path, {'status':'error_unknown_cost','request_hash':request_hash,
                                      'error':{'type':'invalid_usage'}})
            self.guard.settle(request_id,reserve,'error_unknown_cost')
            raise ValueError('usage missing or invalid; full reservation retained') from None
        try:
            if not isinstance(response.get('id'),str) or not response['id']:
                raise ValueError('missing response identity')
            if any(e.get('response_id') == response['id'] for e in self.guard.data['entries'].values()):
                raise ValueError('duplicate response identity')
            value = validator(json.loads(response_text(response)))
        except Exception as exc:
            write_json(parsed_path, {'status':'error','request_hash':request_hash,
                'response_id':response.get('id'),'error':{'type':type(exc).__name__,
                'message':'Parsing, evidence or role validation failed; original response retained.'}})
            self.guard.settle(request_id,charge,'error',usage=response.get('usage'),
                              response_id=response.get('id'),standard_nano=standard)
            raise ValueError('response failed validation; retained without replay') from None
        write_json(parsed_path, {'status':'ok','request_hash':request_hash,'role':role,
             'response_id':response['id'],'payload':value,'usage':response['usage'],
             'standard_nano':standard,'guarded_nano':charge,'created_at':now()})
        self.guard.settle(request_id,charge,'ok',usage=response['usage'],
                          response_id=response['id'],standard_nano=standard)
        return value
