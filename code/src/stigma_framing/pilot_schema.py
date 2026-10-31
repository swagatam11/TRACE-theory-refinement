"""Literal implementation of the researcher pilot output contracts; separate from v0."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


Support = Literal['direct_statement', 'contextual_inference', 'insufficient']
FieldName = Literal['title', 'abstract']


class Proposition(Strict):
    claim: str
    evidence_field: FieldName
    evidence_quote: str | None
    reported_speaker: str
    speaker_stance: Literal['asserts', 'rejects', 'questions', 'anticipates', 'unresolved']
    narrator_stance: Literal['endorses', 'rejects', 'reports_without_resolving', 'unresolved']
    problem_locus: list[Literal['person_attribute', 'person_task_environment_mismatch',
                               'environment', 'institutional_rule', 'technical_system']]
    category_reference: Literal['neutral', 'functional', 'evaluated', 'none', 'unresolved']
    stigma_attribution: Literal['explicit_supported', 'implicit_supported',
                                'absent_in_observed_text', 'indeterminate']
    social_exclusion_observed: Literal['yes', 'no', 'indeterminate']
    stigma_response: list[str]
    remedy_target: list[Literal['person', 'technology', 'interaction', 'environment', 'institution']]
    support_level: Support
    important_alternative: str | None


class Classification(Strict):
    item_id: str
    method: Literal['direct', 'evidence_first']
    has_interpretable_framing: Literal['yes', 'no', 'indeterminate']
    propositions: list[Proposition]
    document_synthesis: str
    uncertainty_note: str | None


class Candidate(Strict):
    descriptive_name: str
    what_text_does: str
    relevance_to_stigma_scholarship: str
    evidence_field: FieldName
    evidence_quote: str
    alternative_interpretation: str
    support_level: Support
    already_explained_by_common_framing: Literal['yes', 'no', 'unclear']


class Discovery(Strict):
    item_id: str
    method: Literal['discovery']
    candidate_patterns: list[Candidate] = Field(max_length=3)
    no_candidate_reason: str | None
    open_question_for_researcher: str | None


def output_schema(method):
    return (Discovery if method == 'discovery' else Classification).model_json_schema()


def validate_output(text, item, method):
    cls = Discovery if method == 'discovery' else Classification
    parsed = cls.model_validate_json(text)
    if parsed.item_id != item['item_id'] or parsed.method != method:
        raise ValueError('response item/method mismatch')
    if method != 'discovery' and len(parsed.document_synthesis.split()) > 100:
        raise ValueError('synthesis exceeds 100 words')
    units = parsed.candidate_patterns if method == 'discovery' else parsed.propositions
    spans = []
    for index, unit in enumerate(units):
        quote = unit.evidence_quote
        if quote is None:
            positive = (unit.problem_locus or unit.stigma_response or unit.remedy_target
                        or unit.category_reference not in ('none', 'unresolved')
                        or unit.stigma_attribution.endswith('_supported')
                        or unit.social_exclusion_observed == 'yes')
            if positive or unit.support_level != 'insufficient':
                raise ValueError('substantive positive interpretation without evidence')
            continue
        field = unit.evidence_field
        if not quote.strip() or quote not in item[field]:
            raise ValueError('evidence quote is not a verbatim input substring')
        # Retain all exact occurrences: repeated quotes do not identify one location.
        starts, start = [], 0
        while (start := item[field].find(quote, start)) >= 0:
            starts.append(start)
            start += 1
        spans.append({'unit_index': index, 'field': field, 'quote': quote,
                      'occurrences': [{'start': x, 'end': x + len(quote)} for x in starts]})
    return parsed.model_dump(), spans
