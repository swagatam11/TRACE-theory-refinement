# TRACE — Stage 1 reviewer guide

**Purpose.** This repository contains a frozen v6.3 proof of process for adversarial, evidence-guided theory refinement. It does not claim superiority over a capable evidence-equipped chatbot or recovery of the true causal graph.

## Navigate the artifact

| Material | Location |
| --- | --- |
| Architecture, limits and offline commands | [`README.md`](README.md) |
| Frozen TRACE (C) proposer–adversary implementation | [`code/synthetic_benchmark_v1/v6_one_shot/`](code/synthetic_benchmark_v1/v6_one_shot/) |
| Comparator arms A and B | Same directory, `arms.py` |
| Deterministic bounded evidence service | Same directory, `evidence_desk.py` |
| Public synthetic data for the illustrative case | [`data/synthetic_benchmark_v1/v6_synthetic_cases/public/development/dev_03/`](data/synthetic_benchmark_v1/v6_synthetic_cases/public/development/dev_03/) |
| Original A/B/C demonstration records | [`demo_locked/dev_03/scientific/`](demo_locked/dev_03/scientific/) |
| Frozen C rival graphs and evidence decision | [`C_pre_evidence_graphs.json`](demo_locked/dev_03/scientific/C/C_pre_evidence_graphs.json), [`C_frozen_evidence_decision.json`](demo_locked/dev_03/scientific/C/C_frozen_evidence_decision.json) |
| Frozen final evaluation | [`C_final.json`](demo_locked/dev_03/scientific/C/C_final.json) |
| Integrity verification | `SOURCE_MANIFEST.json`, `demo_locked/dev_03/PUBLIC_SCIENCE_LOCK.json`, `verify_locked_demo.py` |

## Reproduce without new model calls

Follow the **Offline demo** section of [`README.md`](README.md) for dependencies, tests, offline replay, inspection and integrity checks. These commands are intended for local use and do not initiate paid model calls. Live API reruns are not supplied as a plug-and-play service.

## Boundaries

The included example is a *synthetic development case*. Both the evidence-equipped comparator and TRACE identified relevant theories and requested related evidence. The evidence desk only partially fulfilled some requested estimands. The frozen records demonstrate an auditable prospective revision process, **not** independent comparative superiority or identification of psychological mediators. Generator equations, private holdouts and administrator-only transport envelopes are not in this public package.

**Provenance.** The original release-candidate scientific source files, datasets, results, and source manifest are preserved byte-for-byte. This reviewer guide and `.gitignore` are packaging-only additions.
