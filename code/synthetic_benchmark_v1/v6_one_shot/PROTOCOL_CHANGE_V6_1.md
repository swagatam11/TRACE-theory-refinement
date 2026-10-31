# EATD v6.1 — prospective three-round adversarial cycle

This change is to the v6 C scientific workflow **before any v6 paid run**. A, B,
public synthetic data, one-shot evidence desk, private causal truth, and post-lock
review are unchanged. It supersedes the original single-challenge C protocol.

## Exact EATD workflow

1. Proposer drafts at least two causal DAGs from the common public study card and
   conceptual background; no statistical results available.
2. Adversary round 1: independent challenger returns a causal counter-DAG,
   objections, contrasting predictions, and optional candidate evidence ideas.
3. Proposer responds round 1: revised DAGs or a justified no-change; no evidence.
4. Adversary round 2: probes confounding, exclusions, timing, equivalence.
5. Proposer responds round 2: revised DAGs or justified no-change; no evidence.
6. Adversary round 3: attacks strongest unresolved causal assumption.
7. Proposer responds round 3: final pre-evidence DAGs, contrasts, **one batch of
   at most two specific natural-language evidence requests** (zero permitted),
   and selection rationale. Freeze checkpoint BEFORE evidence service execution.
8. Evidence service returns only the chosen evidence and permanently closes.
9. Adjudicator assesses final pre-evidence DAGs and any post-evidence changes.

The 8 *model calls* are steps 1-7 and 9; step 8 is a deterministic local service.
Each critic and proposer invocation is separately logged. The same EATD model
can occupy the proposer role in several calls; the critic's calls are separate,
fresh role contexts. No agent gets a test menu or a private truth value.

## Scientific caveat

Three rounds may produce better critiques, but they may also produce redundant
objections, premature consensus, and extra cost. This is a prospective fixed
procedure, not a guarantee of better theory. Preserve all initial and intermediate
hypotheses and score whether later rounds actually corrected assumptions or
improved evidence choice. **Do not punish a reasoned no-change.** No results
may be retroactively described as predictions.

Arm A has one ordinary response. Arm B has its original two ordinary chatbot
calls (before and after one evidence request). Arm C now has eight stage calls,
subject to the existing 8-call/60k-token per-arm ceilings. C consequently uses
more inference resources; acknowledge this when interpreting performance and
report cost/latency as distinct outcomes. It would be invalid to attribute a
performance advantage solely to adversarial architecture without considering
this compute difference.

No changes to the benchmark generator, private truth, holdout, historical locks,
or $20 cumulative guard. Provider compatibility and live C performance remain
unverified. A future live execution requires *separate* authorization.
