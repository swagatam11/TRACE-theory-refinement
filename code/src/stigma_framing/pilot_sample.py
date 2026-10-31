"""Reproducible three-channel local gate. No model or external calls."""
import re
import unicodedata
from collections import Counter, defaultdict

from .ingest import digest


def normalized_hash(row):
    return digest([' '.join(unicodedata.normalize('NFC', row[k]).split()).casefold()
                   for k in ('patent_title', 'patent_abstract')])


def gate(row, rules):
    anchor = re.compile(rules['human_anchor'], re.I)
    families = {channel: {k: re.compile(v, re.I) for k, v in rules[channel + '_families'].items()}
                for channel in ('high', 'ambiguous')}
    hits = {'high': [], 'ambiguous': []}
    for field, source in [('title', 'patent_title'), ('abstract', 'patent_abstract')]:
        text = row[source]
        for sentence in re.finditer(r'[^.!?]+(?:[.!?]|$)', text):
            if not anchor.search(sentence.group()):
                continue
            # Radio systems call devices users; a disabled subsystem is not a person.
            if (re.search(r'\b(?:secondary users?|subscriber units?|user equipment)\b', sentence.group(), re.I)
                    and not re.search(r'\b(?:people|persons?|patients?|children|wearers?|workers?)\b', sentence.group(), re.I)):
                continue
            for channel, patterns in families.items():
                for name, pattern in patterns.items():
                    match = pattern.search(sentence.group())
                    if (name == 'participation_access' and match and
                            not re.search(r'\b(?:enabl\w*|allow\w*|facilitat\w*|support\w*|need\w*|problem\w*|'
                                          r'difficult\w*|disabil\w*|impair\w*|blind|deaf|wheelchair|limitation\w*)\b',
                                          sentence.group(), re.I)):
                        continue
                    if match:
                        hits[channel].append({'family': name, 'field': field,
                            'start': sentence.start(), 'end': sentence.end(), 'quote': sentence.group(),
                            'cue': match.group()})
    channel = 'high_potential' if hits['high'] else 'ambiguous' if hits['ambiguous'] else 'ungated'
    return channel, hits['high'] if hits['high'] else hits['ambiguous']


def select_sample(inventory, rules):
    groups = defaultdict(list)
    for row in inventory:
        if row['eligible_text']:
            groups[normalized_hash(row)].append(row)
    candidates = []
    for key, rows in sorted(groups.items()):
        row = min(rows, key=lambda r: (r['patent_id_norm'], r['corpus']))
        channel, hits = gate(row, rules)
        candidates.append({**row, 'normalized_text_hash': key, 'gate_channel': channel,
                           'gate_hits': hits, 'duplicate_patent_ids': sorted({r['patent_id_norm'] for r in rows})})
    selected, used = [], set()
    counts = Counter()
    def rank(row):
        return digest([rules['seed'], row['normalized_text_hash']])
    # Random controls are uniform hash-ranked from all unique eligible texts first.
    controls = sorted(candidates, key=rank)[:rules['channels']['random_control']]
    for row in controls:
        selected.append({**row, 'selection_channel': 'random_control'})
        used.add(row['normalized_text_hash'])
    for channel in ('high_potential', 'ambiguous'):
        pool = [r for r in candidates if r['gate_channel'] == channel and r['normalized_text_hash'] not in used]
        wanted = rules['channels'][channel]
        if len(pool) < wanted:
            raise ValueError(f'insufficient eligible {channel} texts: {len(pool)} < {wanted}')
        family_queue = list(rules['high_families']) if channel == 'high_potential' else []
        for _ in range(wanted):
            # Balance cohort x primary-score strata first, then domains and cue families.
            # Counts describe selection only; never interpretations or model inputs.
            def priority(row):
                stratum = (channel, row['corpus'], row['primary_bin'])
                family = min(counts[(channel, h['family'])] for h in row['gate_hits'])
                return (counts[stratum], counts[(channel, row['first_cpc_subclass'])], family, rank(row))
            family_pool = []
            while family_queue and not family_pool:
                family = family_queue.pop(0)
                family_pool = [r for r in pool if any(h['family'] == family for h in r['gate_hits'])]
            row = min(family_pool or pool, key=priority)
            pool.remove(row)
            selected.append({**row, 'selection_channel': channel})
            used.add(row['normalized_text_hash'])
            counts[(channel, row['corpus'], row['primary_bin'])] += 1
            counts[(channel, row['first_cpc_subclass'])] += 1
            for family in {h['family'] for h in row['gate_hits']}:
                counts[(channel, family)] += 1
    # Canary: one text from each channel; same three inputs for every method.
    ordered = [next(r for r in selected if r['selection_channel'] == channel)
               for channel in ('high_potential', 'ambiguous', 'random_control')]
    ordered += [r for r in selected if r not in ordered]
    inputs, coordinator = [], []
    for row in ordered:
        item_id = 'p-' + digest([rules['seed'], row['normalized_text_hash']])[:16]
        item = {'item_id': item_id, 'title': row['patent_title'], 'abstract': row['patent_abstract']}
        inputs.append(item)
        coordinator.append({**row, 'item_id': item_id, 'pilot_input_hash': digest(item),
                            'split': 'development_pilot'})
    summary = {'unique_eligible_texts': len(candidates),
               'candidate_pool': dict(Counter(r['gate_channel'] for r in candidates)),
               'selected': len(inputs), 'seed': rules['seed'],
               'channels': dict(Counter(r['selection_channel'] for r in coordinator)),
               'cohorts': dict(Counter(r['corpus'] for r in coordinator)),
               'lexical_primary': dict(Counter(r['primary_bin'] for r in coordinator)),
               'domains': dict(Counter(r['first_cpc_subclass'] for r in coordinator)),
               'year_range': [min(r['grant_year'] for r in coordinator), max(r['grant_year'] for r in coordinator)],
               'channel_strata': dict(Counter('|'.join([r['selection_channel'], r['corpus'], r['primary_bin']])
                                             for r in coordinator)),
               'canary_ids': [i['item_id'] for i in inputs[:3]],
               'limitations': ['Purposeful development sample; no prevalence or accuracy inference.',
                   'Gate requires local human/social/functional cues, not semantic confirmation.',
                   'Primary zero does not mean out of every dictionary; it is an anchoring diagnostic.',
                   'Patent-family linkage unavailable; normalized exact duplicates excluded.']}
    return inputs, coordinator, summary
