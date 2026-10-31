"""Full-corpus local inventory, transparent retrieval and purposive review sampling.

This module has no model client. Heuristic hits are retrieval events, not labels.
"""
import argparse
import csv
import hashlib
import itertools
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .ingest import digest
from .pipeline import save

ROOT = Path(__file__).resolve().parents[2]
WORD = re.compile(r"\b[\w]+(?:[-'][\w]+)*\b", re.UNICODE)
STOP = set("a an and are as at be been being by can comprises comprising for from has have in into is it its of on or said such that the their thereof therein these this to using was were which with wherein may not one two first second plurality having each other more than least also provided present invention method apparatus system device includes including".split())


def project_path(path, subtree=None):
    path = Path(path).resolve()
    base = ROOT / subtree if subtree else ROOT
    if not path.is_relative_to(base):
        raise ValueError(f"path must remain under project {subtree or 'root'}")
    return path


def file_hash(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def write_csv(path, rows, columns):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def distribution(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    def q(p):
        return values[round((len(values) - 1) * p)]
    return {"n": len(values), "min": values[0], "p25": q(.25), "median": q(.5),
            "p75": q(.75), "p95": q(.95), "max": values[-1], "mean": sum(values) / len(values)}


def cues_for(fields, rules):
    hits = []
    for field, text in fields.items():
        if text is None:
            continue
        # Context is a bounded literal window; no sentence parser or semantic claim.
        for rule in rules:
            for match in rule['_regex'].finditer(text):
                left, right = max(0, match.start()-160), min(len(text), match.end()+200)
                hits.append({"cue": rule['id'], "field": field, "start": match.start(),
                    "end": match.end(), "quote": match.group(), "context_start": left,
                    "context_end": right, "context": text[left:right]})
    return hits


def score_index(path):
    if not path.exists():
        return {}, {"available": False, "warning": "No frozen score table; baseline unknown, not zero"}
    index, duplicates, invalid = {}, [], []
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        required = {'patent_id_norm', 'corpus', 'new_primary_count', 'new_device_count'}
        if not required <= set(reader.fieldnames or []):
            raise ValueError('frozen score schema differs from verified mapping')
        for row in reader:
            key = (row['patent_id_norm'], row['corpus'])
            if key in index:
                duplicates.append(list(key))
                continue
            try:
                primary, device = int(row['new_primary_count']), int(row['new_device_count'])
                if primary < 0 or device < 0:
                    raise ValueError('negative count')
                index[key] = {'primary': primary, 'device': device}
            except ValueError:
                invalid.append(list(key))
    if duplicates or invalid:
        raise ValueError(f'ambiguous/invalid frozen scores: duplicates={len(duplicates)}, invalid={len(invalid)}')
    return index, {"available": True, "rows": len(index), "sha256": file_hash(path),
                   "join_key": ['patent_id_norm', 'corpus'], "role": "unchanged lexical anchoring diagnostic, not stigma ground truth"}


def select_review(inventory, target, seed, cue_ids):
    """Quota retrieval, then domain/length/year coverage. No population weights."""
    if target < 1:
        raise ValueError('sample size must be positive')
    eligible = [r for r in inventory if r['eligible_text']]
    chosen, reasons, chosen_hashes = {}, defaultdict(list), set()
    def rank(row, salt):
        return digest([seed, salt, row['input_hash'], row['patent_id_norm'], row['source_row']])
    def take(pool, n, reason):
        for row in sorted(pool, key=lambda r: rank(r, reason)):
            if len(chosen) >= target:
                return
            key = row['source_row']
            if key not in chosen and row['input_hash'] not in chosen_hashes:
                chosen[key] = row
                chosen_hashes.add(row['input_hash'])
                reasons[key].append(reason)
                n -= 1
                if n == 0:
                    return
    # Iterative development refinement: the broad social-evaluation cue retrieved
    # many technical homonyms. Explicitly named stigma gets a small dedicated quota.
    take([r for r in eligible if 'explicit_stigma_language' in r['cue_ids']], 8,
         'developmental narrow retrieval: explicit_stigma_language')
    strata = defaultdict(list)
    for row in eligible:
        strata[(row['corpus'], row['primary_bin'], row['device_bin'])].append(row)
    # Up to eight per lexical/cohort combination; rare strata are retained in full.
    for stratum, pool in sorted(strata.items()):
        take(pool, 8, 'lexical/cohort quota: ' + '|'.join(stratum))
    for cue in cue_ids:
        take([r for r in eligible if cue in r['cue_ids']], 6, 'cue retrieval: ' + cue)
    strata = defaultdict(list)
    for row in eligible:
        strata[(row['corpus'], row['first_cpc_subclass'], row['year_bin'], row['length_bin'])].append(row)
    groups = sorted(strata, key=lambda s: digest([seed, list(s)]))
    while len(chosen) < min(target, len(eligible)):
        old = len(chosen)
        for group in groups:
            take(strata[group], 1, 'coverage: ' + '|'.join(group))
        if len(chosen) == old:
            break
    return [{**row, 'selection_reason': reasons[key][0]} for key, row in chosen.items()]


def audit(snapshot, output, patterns_path, sample_size=160, seed=20261029):
    snapshot = project_path(snapshot, 'data/local')
    output = project_path(output, 'results')
    patterns_path = project_path(patterns_path)
    output.mkdir(parents=True, exist_ok=True)
    path = snapshot / 'corpus_frozen.parquet'
    table = pq.read_table(path)
    required = {'patent_id_norm', 'patent_title', 'patent_abstract', 'corpus', 'grant_year', 'cpc_group_list_full'}
    if not required <= set(table.column_names):
        raise ValueError('corpus schema differs from inspected source')
    rows = table.to_pylist()  # Entire corpus; no row/sample cap.
    config = json.loads(patterns_path.read_text(encoding='utf-8'))
    rules = [{**rule, '_regex': re.compile(rule['pattern'], re.IGNORECASE)} for rule in config['rules']]
    scores, baseline = score_index(snapshot / 'finalized_v2_llm/patent_level_dictionary_v2_vs_old.csv')
    cue_counts, cooccurrence, phrase_counts = Counter(), Counter(), Counter()
    phrase_examples = {}
    inventory, input_issues, seen_hashes = [], [], {}
    ids = Counter(row['patent_id_norm'] for row in rows)
    pair_ids = Counter((row['patent_id_norm'], row['corpus']) for row in rows)
    joined = set()
    with (output / 'candidate_passages.jsonl').open('w', encoding='utf-8', newline='\n') as passages:
        for source_row, row in enumerate(rows, 1):
            fields = {'title': row['patent_title'], 'abstract': row['patent_abstract']}
            invalid_text = any(v is not None and not isinstance(v, str) for v in fields.values())
            if invalid_text:
                raise ValueError(f'non-string text at source row {source_row}; refusing coercion')
            if not row['patent_id_norm'] or not isinstance(row['patent_id_norm'], str):
                raise ValueError(f'invalid source ID at row {source_row}')
            input_hash = digest(fields)
            local_id = 'local-' + digest([row['patent_id_norm'], row['corpus']])[:20]
            hits = cues_for(fields, rules)
            cues = sorted({hit['cue'] for hit in hits})
            cue_counts.update(cues)
            cooccurrence.update(itertools.combinations(cues, 2))
            for hit in hits:
                passages.write(json.dumps({'item_id': local_id, 'source_row': source_row,
                    'patent_id_norm': row['patent_id_norm'], 'input_hash': input_hash,
                    'kind': 'regex_retrieval_not_classification', **hit}, ensure_ascii=False) + '\n')
            # Repeated phrase inventory: document frequency, not raw repetition count.
            tokens = [t.lower() for t in WORD.findall(' '.join(v or '' for v in fields.values()))]
            phrases = set()
            for size in (2, 3):
                for start in range(len(tokens)-size+1):
                    chunk = tokens[start:start+size]
                    if not any(t in STOP or len(t) < 3 or not t.isalpha() for t in chunk):
                        phrases.add(' '.join(chunk))
            phrase_counts.update(phrases)
            for phrase in phrases:
                if phrase not in phrase_examples:
                    phrase_examples[phrase] = row['patent_id_norm']
            score = scores.get((row['patent_id_norm'], row['corpus']))
            if score:
                joined.add((row['patent_id_norm'], row['corpus']))
            words = {f: len(WORD.findall(v or '')) for f, v in fields.items()}
            total = sum(words.values())
            group = sorted(set(filter(None, row['cpc_group_list_full'].split('|')))) if row['cpc_group_list_full'] else []
            cpc = re.match(r'[A-HY]\d{2}[A-Z]', group[0]) if group else None
            eligible = any((v or '').strip() for v in fields.values())
            issues = [f'{f}_missing_or_blank' for f, v in fields.items() if not (v or '').strip()]
            if ids[row['patent_id_norm']] > 1:
                issues.append('duplicate_patent_id')
            if issues:
                input_issues.append({'source_row': source_row, 'patent_id_norm': row['patent_id_norm'], 'issues': issues})
            inventory.append({**row, 'source_row': source_row, 'item_id': local_id, 'input_hash': input_hash,
                'title_chars': len(fields['title'] or ''), 'abstract_chars': len(fields['abstract'] or ''),
                'title_words_local': words['title'], 'abstract_words_local': words['abstract'],
                'words_local': total, 'eligible_text': eligible,
                'duplicate_text_of_row': seen_hashes.get(input_hash), 'issues': issues,
                'frozen_primary_count': score['primary'] if score else None,
                'frozen_device_count': score['device'] if score else None,
                'primary_bin': 'unknown' if score is None else ('positive' if score['primary'] > 0 else 'zero'),
                'device_bin': 'unknown' if score is None else ('present' if score['device'] > 0 else 'zero'),
                'device_heavy_3plus': bool(score and score['device'] >= 3),
                'first_cpc_subclass': cpc.group() if cpc else 'unknown',
                'year_bin': f"{(row['grant_year']//10)*10}s" if row['grant_year'] is not None else 'unknown',
                'length_bin': 'short_0_75' if total <= 75 else ('medium_76_150' if total <= 150 else 'long_151plus'),
                'cue_ids': cues, 'cue_hit_count': len(hits), 'heuristic_classification': 'not_performed'})
            seen_hashes.setdefault(input_hash, source_row)
    if any(n > 1 for n in pair_ids.values()):
        raise ValueError('duplicate patent/cohort keys; inventory requires reconciliation before sampling')
    pq.write_table(pa.Table.from_pylist(inventory), output / 'text_inventory.parquet', compression='zstd')
    sample = select_review(inventory, sample_size, seed, [r['id'] for r in rules])
    save(output / 'review_sample.json', sample)
    save(output / 'input_issues.json', input_issues)
    coverage = []
    for factor in ('corpus', 'primary_bin', 'device_bin', 'device_heavy_3plus', 'first_cpc_subclass', 'year_bin', 'length_bin'):
        all_counts = Counter(str(r[factor]) for r in inventory)
        sample_counts = Counter(str(r[factor]) for r in sample)
        coverage.extend({'factor': factor, 'value': key, 'corpus_n': count,
                         'review_n': sample_counts[key]} for key, count in sorted(all_counts.items()))
    for cue in [r['id'] for r in rules]:
        coverage.append({'factor': 'cue_retrieval', 'value': cue, 'corpus_n': cue_counts[cue],
                         'review_n': sum(cue in r['cue_ids'] for r in sample)})
    write_csv(output / 'coverage.csv', coverage, ['factor', 'value', 'corpus_n', 'review_n'])
    strata_counts = Counter((r['corpus'], r['primary_bin'], r['device_bin'], r['year_bin'], r['length_bin']) for r in inventory)
    review_strata = Counter((r['corpus'], r['primary_bin'], r['device_bin'], r['year_bin'], r['length_bin']) for r in sample)
    write_csv(output / 'sampling_strata.csv', [{'corpus': k[0], 'primary': k[1], 'device': k[2], 'decade': k[3],
        'length_bin': k[4], 'corpus_n': n, 'review_n': review_strata[k]} for k, n in sorted(strata_counts.items())],
        ['corpus', 'primary', 'device', 'decade', 'length_bin', 'corpus_n', 'review_n'])
    write_csv(output / 'phrase_inventory.csv', [{'phrase': phrase, 'document_frequency': n,
        'example_patent': phrase_examples[phrase]} for phrase, n in phrase_counts.most_common(500)],
        ['phrase', 'document_frequency', 'example_patent'])
    save(output / 'cue_cooccurrence.json', [{'a': a, 'b': b, 'documents': n} for (a, b), n in cooccurrence.most_common()])
    checks = {}
    for name in ('BUILD_COMPLETE.json', 'finalized_v2_llm/DICTIONARY_V2_FREEZE_AUDIT.json'):
        manifest_path = snapshot / name
        if manifest_path.exists():
            checks[name] = json.loads(manifest_path.read_text(encoding='utf-8'))
    corpus_hash = file_hash(path)
    build_hash = checks.get('BUILD_COMPLETE.json', {}).get('inputs', {}).get('corpus_frozen_sha256')
    freeze_hash = checks.get('finalized_v2_llm/DICTIONARY_V2_FREEZE_AUDIT.json', {}).get('source', {}).get('stage1_corpus_sha256')
    warnings = ['All cue counts are lexical retrieval coverage, not framing prevalence or validated classifications.',
        'Review sample is purposefully enriched, not representative; no sampling weights or population inference.',
        'The documented focal AT cohort has 24,121 patents; this corpus has 24,120 AT. Other cohort not supplied; one-record discrepancy remains unresolved.',
        'Historical controls are already matched/selected; this is not the universe of all non-AT patents.',
        'Original abstract resolution may omit social evaluation; no cue is not evidence of frame absence.',
        'Exact duplicate texts remain in the full inventory; review sampling takes one representative per input hash. Patent-family metadata were not supplied.',
        'Narrow stigma-language retrieval was added after observing broad-cue homonyms in the first scan. This is iterative development, not untouched evaluation.']
    stats = {'rows_processed': len(rows), 'schema': str(table.schema), 'columns': table.column_names,
        'null_counts': {name: table[name].null_count for name in table.column_names},
        'cohort_counts': dict(Counter(r['corpus'] for r in inventory)),
        'grant_year_min': min(r['grant_year'] for r in inventory if r['grant_year'] is not None),
        'grant_year_max': max(r['grant_year'] for r in inventory if r['grant_year'] is not None),
        'year_counts': dict(sorted(Counter(str(r['grant_year']) for r in inventory).items())),
        'duplicate_patent_ids': sum(n-1 for n in ids.values() if n > 1),
        'duplicate_text_rows': sum(r['duplicate_text_of_row'] is not None for r in inventory),
        'ineligible_text_rows': sum(not r['eligible_text'] for r in inventory), 'rows_with_issues': len(input_issues),
        'title_words_local': distribution([r['title_words_local'] for r in inventory]),
        'abstract_words_local': distribution([r['abstract_words_local'] for r in inventory]),
        'combined_words_local': distribution([r['words_local'] for r in inventory]),
        'cue_document_counts': dict(cue_counts), 'documents_without_any_cue': sum(not r['cue_ids'] for r in inventory),
        'baseline': {**baseline, 'joined_rows': len(joined), 'unmatched_corpus_rows': len(rows)-len(joined),
                     'score_rows_not_in_corpus': len(set(scores)-joined),
                     'primary_positive_documents': sum((r['frozen_primary_count'] or 0) > 0 for r in inventory),
                     'device_positive_documents': sum((r['frozen_device_count'] or 0) > 0 for r in inventory)},
        'source_checks': {'corpus_sha256': corpus_hash, 'matches_build_manifest': corpus_hash == build_hash,
                          'matches_freeze_manifest': corpus_hash == freeze_hash},
        'sample': {'seed': seed, 'requested': sample_size, 'selected': len(sample),
                   'algorithm': 'up to eight distinct-text explicit stigma-language cases, eight per cohort/primary/device stratum, six additional per cue family, then shuffled domain/decade/length coverage; one representative per exact input hash',
                   'cohort_counts': dict(Counter(r['corpus'] for r in sample)),
                   'distinct_first_cpc_subclasses': len({r['first_cpc_subclass'] for r in sample}),
                   'without_cue_matches': sum(not r['cue_ids'] for r in sample),
                   'duplicate_text_rows': len(sample) - len({r['input_hash'] for r in sample}), 'split': 'development_only'},
        'warnings': warnings, 'tokenization': 'Unicode word regex for local descriptions only; frozen v2 scores not recomputed'}
    save(output / 'audit.json', stats)
    save(output / 'run_manifest.json', {'created_utc': datetime.now(timezone.utc).isoformat(),
        'corpus_sha256': corpus_hash, 'patterns_sha256': file_hash(patterns_path), 'patterns_version': config['version'],
        'code_sha256': file_hash(Path(__file__)), 'seed': seed, 'sample_source_rows': [r['source_row'] for r in sample],
        'packages': {'pyarrow': pa.__version__}, 'api_requests': 0, 'all_analysis_inputs': 'project-local copies'})
    render_review(output, inventory, sample, stats, rules)
    return stats


def render_review(output, inventory, sample, stats, rules):
    from .html_review import STYLE, h, highlighted
    notes_path = ROOT / 'config/exploration/close_reading_notes_v0.json'
    notes = json.loads(notes_path.read_text(encoding='utf-8'))['notes'] if notes_path.exists() else []
    rendered_notes = []
    rule_map = {r['id']: r for r in rules}
    cards = []
    for index, row in enumerate(sample, 1):
        fields = {'title': row['patent_title'], 'abstract': row['patent_abstract']}
        hits = cues_for(fields, rules)
        interpretations = []
        for cue in row['cue_ids']:
            rule = rule_map[cue]
            evidence = []
            group = [hit for hit in hits if hit['cue'] == cue]
            for hit in group[:3]:
                evidence.append(f'<li><code>{h(hit["field"])} [{hit["start"]}, {hit["end"]})</code>: <b>{h(hit["quote"])}</b><blockquote>{h(hit["context"])}</blockquote></li>')
            interpretations.append(f'<section class="unit"><h4>{h(cue)}</h4><p><b>Text-supported observation:</b> the following literal cue occurs. {len(group)} matches; showing at most three, all retained in the full passage inventory.</p><ul>{"".join(evidence)}</ul><p><b>Provisional interpretation to inspect:</b> {h(rule["question"])}</p><p><b>Competing reading / uncertainty:</b> {h(rule["alternative"])}</p><p><b>Judgment status:</b> not classified; semantic support and source stance await researcher/authorized model review.</p></section>')
        if not interpretations:
            interpretations.append('<p>No configured cue matched. Framing remains unassessed; lack of retrieval is not absence of attribute, relational, institutional or stigma attribution.</p>')
        close_reading = []
        for note in notes:
            if row['patent_id_norm'] not in note['patent_ids']:
                continue
            raw = fields[note['field']]
            start = raw.find(note['quote']) if raw else -1
            if start < 0:
                raise ValueError('close-reading note does not match original patent')
            checked = {**note, 'patent_id_norm': row['patent_id_norm'], 'start': start,
                       'end': start + len(note['quote']), 'input_hash': row['input_hash']}
            rendered_notes.append(checked)
            close_reading.append(f'<section class="critique"><h4>Focused agent close reading — provisional</h4><blockquote>{h(note["quote"])}</blockquote><p><code>{h(note["field"])} [{start}, {checked["end"]})</code></p><p><b>Interpretation:</b> {h(note["interpretation"])}</p><p><b>Competing reading:</b> {h(note["competing"])}</p><p><b>Candidate for discussion:</b> {h(note["candidate_dimension"])}</p><p>No independent semantic validation; no taxonomy change.</p></section>')
        rendered = ''.join(f'<h4>{h(field)}</h4><p class="fulltext">{highlighted(text, [hit for hit in hits if hit["field"] == field]) if text is not None else "Missing original field"}</p>' for field, text in fields.items())
        cards.append(f'<article class="case" id="patent-{h(row["patent_id_norm"])}"><h3>{index:03d} · Patent {h(row["patent_id_norm"])}</h3><p><span class="badge">Unclassified · local retrieval only</span></p>{rendered}<p><b>Selected because:</b> {h(row["selection_reason"])}</p><p><b>Coordinator diagnostics, withheld from future model inputs:</b> {h(row["corpus"])} · {h(row["grant_year"])} · first CPC subclass {h(row["first_cpc_subclass"])} · frozen primary count {h(row["frozen_primary_count"])} · device count {h(row["frozen_device_count"])}. Lexical counts are not stigma labels.</p>{"".join(close_reading)}<details><summary>Evidence-linked provisional readings and competing explanations</summary>{"".join(interpretations)}</details><p class="meta">Input SHA-256: {h(row["input_hash"])} · source row {row["source_row"]} · {h(row["item_id"])}</p></article>')
    count_rows = ''.join(f'<tr><th>{h(cue)}</th><td>{n:,}</td><td>{sum(cue in r["cue_ids"] for r in sample)}</td></tr>' for cue,n in sorted(stats['cue_document_counts'].items()))
    rule_rows = ''.join(f'<tr><th>{h(r["id"])}</th><td><code>{h(r["pattern"])}</code></td><td>{h(r["alternative"])}</td></tr>' for r in rules)
    warnings = ''.join(f'<li>{h(w)}</li>' for w in stats['warnings'])
    text = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Real patent corpus — local exploratory review</title><style>{STYLE}</style></head><body><main>
<header><p>FULL-CORPUS LOCAL AUDIT · DEVELOPMENT REVIEW</p><h1>Framing questions in {len(sample)} real patents</h1><p>{stats['rows_processed']:,} original patent records processed locally. No LLM classifications or paid requests.</p></header>
<section class="intro"><p class="notice">Original titles and abstracts are reproduced from the local frozen snapshot. Yellow highlighting is literal regex evidence. Interpretations are provisional questions, not validated labels or automated stigma findings. The taxonomy is unchanged.</p><h2>What is known from the files</h2><p>Corpus: {h(stats['cohort_counts'])}. Years {stats['grant_year_min']}–{stats['grant_year_max']}. Duplicate patent IDs: {stats['duplicate_patent_ids']}; repeated exact-text rows beyond their first occurrence: {stats['duplicate_text_rows']}; rows with input issues: {stats['rows_with_issues']}. Frozen score joins: {stats['baseline']['joined_rows']:,}/{stats['rows_processed']:,}. The corpus hash matches build and freeze manifests: {h(stats['source_checks']['matches_build_manifest'])}, {h(stats['source_checks']['matches_freeze_manifest'])}.</p><p>Combined word counts (local descriptive tokenizer): {h(stats['combined_words_local'])}. This does not replace the frozen scorer's denominator.</p><ul>{warnings}</ul></section>
<section class="intro"><h2>How to read these candidate interpretations</h2><p>Attribute locus requires a text-supported explanation through a person's attribute; a disability mention alone is insufficient. Relational locus requires an articulated interaction/mismatch, not broad applicability. Institutional locus concerns rules and arrangements; technical policies are potential homonyms. Category-linked stigma attribution additionally needs a discrediting judgment or a separately defined exclusion mechanism, with source and stance retained. A quoted or negated evaluation is not automatically endorsed.</p><p>Inspect the full passage before inferring a frame. Cue families offer alternative readings, not positive/negative statuses. No-hit documents are deliberately available as coverage controls. The prior scientific ambiguity over exclusion versus devaluation remains unresolved.</p><h3>Open candidate dimensions, not additions to the taxonomy</h3><p>Visibility/concealment, autonomy/care dependence, safety/risk, restoration/normalization, user control/participation and broad applicability are retrieval facets for discussion. They were specified before this scan, not induced and validated by an LLM. Evaluate whether they are framing dimensions, technical content, remedy subcodes or irrelevant homonyms. Repeated phrases are saved separately as data-driven lexical observations, not theoretical categories.</p></section>
<section class="intro"><h2>Coverage and reproducible selection</h2><p>Seed {stats['sample']['seed']}. {h(stats['sample']['algorithm'])}. Selected cohorts: {h(stats['sample']['cohort_counts'])}. This is a purposive enriched development sample, not an evaluation holdout or representative prevalence sample. Corpus-wide statistics use all records, independent of this review sample.</p><div class="scroll"><table><thead><tr><th>Retrieval family</th><th>Full-corpus documents</th><th>Review documents</th></tr></thead><tbody>{count_rows}</tbody></table></div><p>Full field/year/domain strata and gaps are saved in coverage.csv and sampling_strata.csv; all candidate spans are retained in candidate_passages.jsonl.</p></section>
<div class="controls"><label for="search">Find a title, passage, cue, patent ID or provisional reading</label><input id="search" type="search" placeholder="Search these patents"><label><input id="cues" type="checkbox"> Show only patents with cue matches</label><p id="shown" role="status"></p><button id="expand" type="button">Expand all provisional readings</button></div>{''.join(cards)}
<details><summary>Complete transparent retrieval rules and limitations</summary><div class="scroll"><table><thead><tr><th>Family</th><th>Regex (case-insensitive)</th><th>Alternative reading</th></tr></thead><tbody>{rule_rows}</tbody></table></div></details>
<footer><p>All model classifications, human validation and semantic evaluation remain unperformed. Results are local descriptive/retrieval artifacts. Reviewers should record support, counterexamples, source/stance and conceptual uncertainty before any versioned taxonomy change.</p></footer>
</main><script>const cards=[...document.querySelectorAll('article.case')];function filter(){{let n=0;const q=document.querySelector('#search').value.toLowerCase();cards.forEach(c=>{{c.hidden=!(c.textContent.toLowerCase().includes(q)&&(!document.querySelector('#cues').checked||c.querySelector('.unit')));if(!c.hidden)n++;}});document.querySelector('#shown').textContent=n+' of '+cards.length+' patents shown';}}document.querySelector('#search').addEventListener('input',filter);document.querySelector('#cues').addEventListener('change',filter);document.querySelector('#expand').addEventListener('click',()=>document.querySelectorAll('details').forEach(d=>d.open=true));filter();</script></body></html>'''
    (output / 'real_patent_review.html').write_bytes(text.encode('utf-8'))
    save(output / 'close_reading_notes.json', {'status': 'provisional_agent_commentary_not_human_labels',
        'notes_sha256': file_hash(notes_path) if notes_path.exists() else None, 'notes': rendered_notes})
    summary = ['# Full-corpus local audit', '', f"Processed {len(inventory):,} rows; reviewed sample contains {len(sample)} real patents.",
               f"Cohorts: {stats['cohort_counts']}. Baseline matched {stats['baseline']['joined_rows']:,} rows.", '', *stats['warnings']]
    (output / 'audit.md').write_text('\n\n'.join(summary)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=ROOT / 'data/local/frozen_snapshot')
    parser.add_argument('--output', type=Path, default=ROOT / 'results/real_corpus')
    parser.add_argument('--patterns', type=Path, default=ROOT / 'config/exploration/local_patterns_v0.json')
    parser.add_argument('--sample-size', type=int, default=160)
    parser.add_argument('--seed', type=int, default=20261029)
    args = parser.parse_args()
    result = audit(args.snapshot, args.output, args.patterns, args.sample_size, args.seed)
    print(json.dumps({'rows_processed': result['rows_processed'], 'sample': result['sample'],
        'baseline': result['baseline'], 'source_checks': result['source_checks']}, indent=2))


if __name__ == '__main__':
    main()
