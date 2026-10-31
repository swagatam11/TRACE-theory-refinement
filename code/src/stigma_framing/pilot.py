"""Frozen 50-text development pilot; prepare offline, then explicitly approve live canary."""
import argparse
import json
import math
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from .ingest import digest
from .local_corpus import ROOT, file_hash, project_path
from .pilot_sample import select_sample
from .pilot_schema import output_schema, validate_output

METHODS = ('direct', 'evidence_first', 'discovery')
PROMPT = ROOT / 'prompts/stigma_framing_llm_pilot_prompts_v1.md'
OUTPUT = ROOT / 'results/pilot_v1'
VERSION = 'PILOT_2026-10-29_v1'
LOCAL_BUDGET_NANO = 10_000_000_000


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    tmp.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def prompt_parts(path=PROMPT):
    # Extract literal Markdown bodies; do not author a replacement scientific prompt.
    text = path.read_bytes().decode('utf-8')
    normalized = text.replace('\r\n', '\n')
    headings = list(re.finditer(r'^## (.+)$', normalized, re.M))
    sections = {}
    for i, match in enumerate(headings):
        body = normalized[match.end():headings[i + 1].start() if i + 1 < len(headings) else len(normalized)]
        sections[match.group(1)] = re.sub(r'\n---\s*$', '', body).strip()
    shared = next(v for k, v in sections.items() if k.startswith('Shared scientific system'))
    discovery = next(v for k, v in sections.items() if k.startswith('Mode 3: Open-ended'))
    system, user = discovery.split('### Mode 3: User message\n', 1)
    return {'direct': {'system': shared, 'user': next(v for k, v in sections.items() if k.startswith('Mode 1:'))},
            'evidence_first': {'system': shared, 'user': next(v for k, v in sections.items() if k.startswith('Mode 2:'))},
            'discovery': {'system': system.strip(), 'user': user.strip()}}


def request_body(item, method, parts, config):
    # A single regex substitution prevents placeholder-like source text being replaced twice.
    values = {'ITEM_ID': item['item_id'], 'TITLE': item['title'], 'ABSTRACT': item['abstract']}
    user = re.sub(r'\{\{(ITEM_ID|TITLE|ABSTRACT)\}\}', lambda m: values[m.group(1)], parts[method]['user'])
    return {'model': config['model'], 'store': False, 'service_tier': 'default',
            'reasoning': {'effort': config['reasoning_effort']},
            'max_output_tokens': config['max_output_tokens'], 'truncation': 'disabled',
            'input': [{'role': 'system', 'content': parts[method]['system']}, {'role': 'user', 'content': user}],
            'text': {'format': {'type': 'json_schema', 'name': 'pilot_' + method,
                                'strict': True, 'schema': output_schema(method)}}}


def input_bytes(body):
    return len(json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def reservation_nano(body, config):
    bound = input_bytes(body) + config['input_bound_overhead_tokens']
    return math.ceil(bound * config['cache_write_usd_per_million'] * 1000
                     + body['max_output_tokens'] * config['output_usd_per_million'] * 1000)


def projected_nano(body, config, output_tokens=None):
    return math.ceil(math.ceil(input_bytes(body) / 4) * config['input_usd_per_million'] * 1000
                     + (output_tokens if output_tokens is not None else config['expected_output_tokens'])
                     * config['output_usd_per_million'] * 1000)


def usage_cost(usage, config):
    for key in ('input_tokens', 'output_tokens'):
        if type(usage.get(key)) is not int or usage[key] < 0:
            raise ValueError('missing/invalid measured usage; keep full reservation')
    cached = (usage.get('input_tokens_details') or {}).get('cached_tokens', 0)
    if type(cached) is not int or not 0 <= cached <= usage['input_tokens']:
        raise ValueError('invalid cached usage')
    written = (usage.get('input_tokens_details') or {}).get('cache_write_tokens', 0)
    if type(written) is not int or not 0 <= written <= usage['input_tokens'] - cached:
        raise ValueError('invalid cache-write usage')
    standard = math.ceil(((usage['input_tokens'] - cached - written) * config['input_usd_per_million']
                         + cached * config['cached_input_usd_per_million']
                         + written * config['cache_write_usd_per_million']
                         + usage['output_tokens'] * config['output_usd_per_million']) * 1000)
    conservative = math.ceil((usage['input_tokens'] * config['cache_write_usd_per_million']
                             + usage['output_tokens'] * config['output_usd_per_million']) * 1000)
    return standard, conservative


def prepare(output=OUTPUT):
    import pyarrow.parquet as pq
    from dotenv import dotenv_values
    output = project_path(output, 'results')
    if (output / 'manifest.json').exists():
        verify_frozen(output)
        return read_json(output / 'dry_run.json')
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'ledger.json').exists():
        raise ValueError('existing ledger without manifest; refuse to replace')
    rules_path = ROOT / 'config/exploration/pilot_gate_v1.json'
    config_path = ROOT / 'config/models/pilot_v1.json'
    inventory_path = ROOT / 'results/real_corpus/text_inventory.parquet'
    rules, config = read_json(rules_path), read_json(config_path)
    inputs, coordinator, composition = select_sample(pq.read_table(inventory_path).to_pylist(), rules)
    if len(inputs) != 50:
        raise ValueError('pilot requires exactly 50 unique texts')
    parts = prompt_parts()
    (output / 'prompts_source.md').write_bytes(PROMPT.read_bytes())
    write_json(output / 'prompt_parts.json', parts)
    write_json(output / 'inputs.json', inputs)
    write_json(output / 'coordinator.json', coordinator)
    write_json(output / 'selection_rules.json', rules)
    write_json(output / 'config.json', config)
    requests = [{'custom_id': i['item_id'] + '-' + m, 'item_id': i['item_id'], 'method': m,
                 'input_hash': digest(i), 'prompt_hash': digest(parts[m]),
                 'body': request_body(i, m, parts, config)} for i in inputs for m in METHODS]
    write_json(output / 'requests.json', requests)
    projected = sum(projected_nano(r['body'], config) for r in requests) / 1e9
    frozen_files = ['prompts_source.md', 'prompt_parts.json', 'inputs.json', 'coordinator.json',
                    'selection_rules.json', 'config.json', 'requests.json']
    code_paths = [Path(__file__), ROOT / 'src/stigma_framing/pilot_sample.py',
                  ROOT / 'src/stigma_framing/pilot_schema.py', ROOT / 'src/stigma_framing/pilot_report.py']
    manifest = {'version': VERSION, 'created_utc': now(),
                'files': {p: file_hash(output / p) for p in frozen_files},
                'code': {p.relative_to(ROOT).as_posix(): file_hash(p) for p in code_paths},
                'scientific_prompt_sha256': file_hash(PROMPT),
                'taxonomy_sha256': file_hash(ROOT / 'config/constructs/v0.json'),
                'inventory_sha256': file_hash(inventory_path),
                'prompt_method_hashes': {m: digest(parts[m]) for m in METHODS},
                'packages': {p: version(p) for p in ('openai', 'python-dotenv', 'pydantic', 'pyarrow')},
                'sample_size': 50, 'request_count': 150, 'canary_ids': composition['canary_ids']}
    write_json(output / 'manifest.json', manifest)
    report = {'status': 'DRY_RUN_AWAITING_RESEARCHER_CONFIRMATION', 'composition': composition,
              'model': config['model'], 'reasoning_effort': config['reasoning_effort'],
              'max_output_tokens_per_request': config['max_output_tokens'],
              'requests_prepared': len(requests), 'requests_sent': 0, 'estimated_spend_usd': 0,
              'projected_all_150_usd': projected,
              'projected_canary_9_usd': sum(projected_nano(r['body'], config) for r in requests[:9]) / 1e9,
              'all_max_output_planning_usd': sum(projected_nano(r['body'], config, config['max_output_tokens']) for r in requests) / 1e9,
              'sum_conservative_reservations_usd': sum(reservation_nano(r['body'], config) for r in requests) / 1e9,
              'canary_max_reservations_usd': sum(reservation_nano(r['body'], config) for r in requests[:9]) / 1e9,
              'prompt_source_unchanged': file_hash(PROMPT) == file_hash(output / 'prompts_source.md'),
              'prompt_sha256': file_hash(PROMPT), 'method_prompt_hashes': manifest['prompt_method_hashes'],
              'manifest_sha256': file_hash(output / 'manifest.json'),
              'dotenv_file_exists': (ROOT / '.env').is_file(),
              'dotenv_key_configured': bool(dotenv_values(ROOT / '.env', interpolate=False).get('OPENAI_API_KEY')),
              'platform_limit': 'Separate $12 platform hard limit requires user confirmation; not inferred from API key.',
              'cost_assumptions': config['notes']}
    write_json(output / 'dry_run.json', report)
    write_json(output / 'ledger.json', {'budget_nano': LOCAL_BUDGET_NANO, 'entries': {}, 'created_utc': now()})
    from .pilot_report import render
    render(output)
    return report


def verify_frozen(output):
    manifest = read_json(output / 'manifest.json')
    for name, expected in manifest['files'].items():
        if file_hash(output / name) != expected:
            raise ValueError('frozen pilot artifact changed: ' + name)
    for name, expected in manifest['code'].items():
        if file_hash(ROOT / name) != expected:
            raise ValueError('pilot code changed since freeze: ' + name)
    if file_hash(PROMPT) != manifest['scientific_prompt_sha256']:
        raise ValueError('researcher prompt changed since freeze')
    if file_hash(ROOT / 'config/constructs/v0.json') != manifest['taxonomy_sha256']:
        raise ValueError('original taxonomy changed since freeze')
    requests, inputs = read_json(output / 'requests.json'), read_json(output / 'inputs.json')
    if len(inputs) != 50 or len(requests) != 150:
        raise ValueError('pilot must have 50 texts and 150 bounded requests')
    return manifest


class SpendingGuard:
    """Persist reservation before network; unknown outcomes remain charged at maximum."""
    def __init__(self, path):
        self.path = path
        self.data = read_json(path)
        if self.data['budget_nano'] != LOCAL_BUDGET_NANO:
            raise ValueError('pilot spending cap must match the authorized $10 cap')

    @property
    def spent(self):
        return sum(e['charged_nano'] for e in self.data['entries'].values())

    def reserve(self, key, nano, provenance):
        if key in self.data['entries']:
            raise ValueError('request already attempted; no automatic replay or retry')
        if self.spent + nano > self.data['budget_nano']:
            raise ValueError('spending guard: next reservation would exceed the $10 cap')
        self.data['entries'][key] = {'status': 'reserved_unknown_outcome', 'charged_nano': nano,
                                    'reserved_nano': nano, 'started_utc': now(), **provenance}
        write_json(self.path, self.data)

    def settle(self, key, charge, **fields):
        entry = self.data['entries'][key]
        entry.update(fields, charged_nano=charge, finished_utc=now())
        if charge > entry['reserved_nano'] or self.spent > self.data['budget_nano']:
            entry['status'] = 'cost_warning'
            write_json(self.path, self.data)
            raise ValueError('usage exceeded reservation; stop for cost review')
        write_json(self.path, self.data)


@contextmanager
def run_lock(output):
    path = output / 'run.lock'
    # Exclusive OS create blocks concurrent runners. A crash leaves a deliberate lock.
    with path.open('x', encoding='utf-8') as stream:
        stream.write(now())
    try:
        yield
    finally:
        path.unlink()


def load_client(config):
    from dotenv import dotenv_values
    from openai import OpenAI
    # Never traverse parents, interpolate other environment variables, or print values.
    values = dotenv_values(ROOT / '.env', interpolate=False)
    key = values.get('OPENAI_API_KEY')
    if not key or not key.strip():
        raise ValueError('OPENAI_API_KEY missing from project .env')
    return OpenAI(api_key=key, base_url='https://api.openai.com/v1',
                  max_retries=0, timeout=config['timeout_seconds'])


def response_text(response):
    if response.get('status') != 'completed':
        raise ValueError('provider response not completed')
    texts = []
    for unit in response.get('output', []):
        for block in unit.get('content', []):
            if block.get('type') == 'refusal':
                raise ValueError('provider refusal')
            if block.get('type') == 'output_text':
                texts.append(block['text'])
    if not texts:
        raise ValueError('no output text')
    return ''.join(texts)


def execute_request(request, item, output, guard, config, client, attempt_id=None):
    key, body = attempt_id or request['custom_id'], request['body']
    provenance = {'request_hash': digest(body), 'input_hash': digest(item),
                  'prompt_hash': request['prompt_hash'], 'method': request['method'],
                  'retry_count': int(attempt_id is not None), 'attempt_id': key}
    guard.reserve(key, reservation_nano(body, config), provenance)
    # Save exact request before transmission; raw envelopes before any parsing.
    write_json(output / 'raw' / (key + '.request.json'), body)
    try:
        response = client.responses.create(**body).model_dump(mode='json')
    except Exception as exc:
        # Exception strings/bodies can echo authorization headers; retain safe metadata only.
        error = {'type': type(exc).__name__, 'http_status': getattr(exc, 'status_code', None),
                 'request_id': getattr(exc, 'request_id', None),
                 'message': 'Transport/API error; no automatic retry. Full reservation retained.'}
        failure = {'status': 'error', 'error': error, **provenance}
        write_json(output / 'parsed_attempts' / (key + '.json'), failure)
        write_json(output / 'parsed' / (request['custom_id'] + '.json'), failure)
        guard.settle(key, guard.data['entries'][key]['reserved_nano'], status='error_unknown_cost', error=error)
        raise ValueError('API request failed; stopped with reservation retained') from None
    write_json(output / 'raw' / (key + '.response.json'), response)
    record = {'status': 'error', 'annotation': None, 'spans': [], 'usage': response.get('usage'),
              'actual_model': response.get('model'), 'response_id': response.get('id'), **provenance}
    charge = guard.data['entries'][key]['reserved_nano']
    standard = None
    try:
        standard, charge = usage_cost(response.get('usage') or {}, config)
        record['annotation'], record['spans'] = validate_output(response_text(response), item, request['method'])
        if response.get('model') != body['model'] and not str(response.get('model', '')).startswith(body['model'] + '-'):
            raise ValueError('unexpected returned model')
        if response.get('service_tier', 'default') not in (None, 'default'):
            raise ValueError('unexpected service tier; review billing')
        record['status'] = 'ok'
    except (ValueError, KeyError, TypeError) as exc:
        # Validation exceptions can include model text; raw response is stored separately.
        record['annotation'], record['spans'] = None, []
        record['error'] = {'type': type(exc).__name__, 'message': 'Output/usage/model validation failed; inspect preserved response.'}
    record.update(estimated_standard_usd=None if standard is None else standard / 1e9,
                  guarded_estimated_usd=charge / 1e9)
    write_json(output / 'parsed_attempts' / (key + '.json'), record)
    write_json(output / 'parsed' / (request['custom_id'] + '.json'), record)
    guard.settle(key, charge, status=record['status'], usage=record['usage'],
                 actual_model=record['actual_model'], estimated_standard_usd=record['estimated_standard_usd'])
    if record['status'] != 'ok':
        raise ValueError('response failed validation; stop and review')
    return record


def check_canary(output, requests, config, guard):
    canary = requests[:9]
    records = [read_json(output / 'parsed' / (r['custom_id'] + '.json')) for r in canary]
    if any(r['status'] != 'ok' or not r.get('usage') for r in records):
        raise ValueError('all nine canary outputs must pass and record usage')
    # Scale measured output usage to remaining requests; estimate each actual input.
    means = {m: math.ceil(sum(r['usage']['output_tokens'] for r in records if r['method'] == m) / 3)
             for m in METHODS}
    remaining = [r for r in requests if r['custom_id'] not in guard.data['entries']]
    forecast = guard.spent + sum(projected_nano(r['body'], config, means[r['method']]) for r in remaining)
    report = {'status': 'passed' if forecast <= guard.data['budget_nano'] else 'budget_warning',
              'canary_requests': 9, 'mean_output_tokens_by_method': means,
              'guarded_spend_usd': guard.spent / 1e9, 'projected_final_usd': forecast / 1e9,
              'remaining_requests': len(remaining), 'checked_utc': now()}
    write_json(output / 'canary_check.json', report)
    if report['status'] != 'passed':
        raise ValueError('canary measured projection exceeds budget; stop')
    return report


def verify_approval(output, phase, config):
    approval = read_json(output / 'approval.json') if (output / 'approval.json').exists() else {}
    if (approval.get('manifest_sha256') != file_hash(output / 'manifest.json')
            or approval.get('dry_run_confirmed') is not True
            or approval.get('platform_hard_limit_confirmed_usd') != config['platform_project_limit_usd']
            or approval.get('local_cumulative_cap_usd') != config['budget_usd']):
        raise ValueError('live run requires confirmed dry-run, $10 local cap and $12 platform hard limit, bound to manifest')
    if approval.get('dry_run_sha256') != file_hash(output / 'dry_run.json'):
        raise ValueError('approval does not match the reviewed dry-run report')
    if phase not in approval.get('authorized_phases', []):
        raise ValueError('this phase requires further researcher authorization; current approval is canary only')


def run_live(output=OUTPUT, phase='canary', client=None, recover_connection_once=False):
    output = project_path(output, 'results')
    if output != OUTPUT:
        raise ValueError('live pilot uses one fixed cumulative ledger in results/pilot_v1')
    if phase not in ('canary', 'remaining'):
        raise ValueError('unknown live phase')
    verify_frozen(output)
    config = read_json(output / 'config.json')
    verify_approval(output, phase, config)
    requests = read_json(output / 'requests.json')
    items = {i['item_id']: i for i in read_json(output / 'inputs.json')}
    with run_lock(output):
        guard = SpendingGuard(output / 'ledger.json')
        attempted = guard.data['entries']
        reconciled = lambda e: (e['status'] == 'connection_failure_retained'
            and attempted.get(e.get('replaced_by'), {}).get('status') == 'ok')
        failures = {k: e for k, e in attempted.items() if e['status'] != 'ok' and not reconciled(e)}
        recover_key = None
        if recover_connection_once:
            if phase != 'canary' or len(failures) != 1:
                raise ValueError('connection recovery requires exactly one failed canary attempt')
            recover_key, failure = next(iter(failures.items()))
            if (failure.get('error', {}).get('type') != 'APIConnectionError'
                    or failure.get('error', {}).get('http_status') is not None
                    or recover_key.endswith('-connection-recovery-1')
                    or recover_key + '-connection-recovery-1' in attempted):
                raise ValueError('only one explicit connection recovery is permitted; not API or output errors')
        elif failures:
            raise ValueError('previous failed or uncertain request requires review; no automatic replay')
        if phase == 'remaining':
            check_canary(output, requests, config, guard)
        chosen = requests[:9] if phase == 'canary' else requests[9:]
        client = client or load_client(config)
        try:
            for request in chosen:
                key = request['custom_id']
                if key == recover_key:
                    retry_key = key + '-connection-recovery-1'
                    previous = output / 'parsed' / (key + '.json')
                    if previous.exists():
                        write_json(output / 'parsed_attempts' / (key + '.json'), read_json(previous))
                    execute_request(request, items[request['item_id']], output, guard, config, client,
                                    attempt_id=retry_key)
                    attempted[key].update(status='connection_failure_retained', replaced_by=retry_key,
                                          recovery_note='Explicit sandbox network recovery; original reservation retained.')
                    write_json(guard.path, guard.data)
                    continue
                if key in attempted:
                    continue
                execute_request(request, items[request['item_id']], output, guard, config, client)
            if phase == 'canary':
                check_canary(output, requests, config, guard)
        finally:
            from .pilot_report import render
            render(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['dry-run', 'canary', 'remaining', 'report'])
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--recover-connection-once', action='store_true',
                        help='Explicit one-time canary network recovery; retains original reservation')
    args = parser.parse_args()
    output = project_path(args.output, 'results')
    if args.command == 'dry-run':
        print(json.dumps(prepare(output), ensure_ascii=False, indent=2))
    elif args.command == 'report':
        from .pilot_report import render
        verify_frozen(output)
        render(output)
    else:
        run_live(output, args.command, recover_connection_once=args.recover_connection_once)


if __name__ == '__main__':
    main()
