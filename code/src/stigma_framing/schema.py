from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Span(StrictModel):
    field: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)


class Unit(StrictModel):
    unit_id: str
    axis: str
    label: str
    problem_or_evaluation: str = Field(min_length=1)
    category: str | None
    target: str | None
    voice: str = Field(min_length=1)
    stance: Literal["endorsed", "quoted", "rejected", "negated", "indeterminate"]
    evidence: list[Span] = Field(min_length=1)
    explanation: str = Field(min_length=1)


class Finding(StrictModel):
    status: Literal["present", "absent_in_observed_text", "indeterminate"]
    labels: list[str]
    supporting_units: list[str]
    ambiguity: str | None


class Annotation(StrictModel):
    schema_version: Literal["0.1"]
    units: list[Unit]
    findings: dict[str, Finding]


def verify_units(units: list[Unit], fields: dict[str, str], codebook: dict) -> None:
    ids = set()
    for unit in units:
        if unit.unit_id in ids:
            raise ValueError("duplicate evidence unit ID")
        ids.add(unit.unit_id)
        if unit.label not in codebook["axes"].get(unit.axis, {}):
            raise ValueError("unknown or disabled codebook label")
        for span in unit.evidence:
            text = fields.get(span.field)
            if text is None or span.end > len(text) or span.end <= span.start or text[span.start:span.end] != span.quote:
                raise ValueError("evidence span does not match original field")


def verify(annotation: Annotation, fields: dict[str, str], codebook: dict) -> None:
    verify_units(annotation.units, fields, codebook)
    if set(annotation.findings) != set(codebook["axes"]):
        raise ValueError("findings must cover every enabled axis")
    units = {u.unit_id: u for u in annotation.units}
    for axis, finding in annotation.findings.items():
        if len(set(finding.labels)) != len(finding.labels):
            raise ValueError("duplicate synthesis label")
        if finding.status != "present":
            if finding.labels or finding.supporting_units:
                raise ValueError("non-present finding cannot contain positive labels")
            if finding.status == "indeterminate" and not finding.ambiguity:
                raise ValueError("indeterminate requires ambiguity note")
            continue
        if not finding.labels or not finding.supporting_units:
            raise ValueError("positive finding requires labels and evidence")
        support = []
        for uid in finding.supporting_units:
            if uid not in units or units[uid].axis != axis:
                raise ValueError("invalid supporting unit")
            support.append(units[uid].label)
        if set(support) != set(finding.labels):
            raise ValueError("positive labels must match supporting units")
        if any(label not in codebook["axes"][axis] for label in finding.labels):
            raise ValueError("unknown synthesis label")
