# TRACE — Theory Refinement through Adversarial Causal Evaluation

**Stage 1 proof of concept | Frozen scientific implementation: EATD v6.3**  
**Public-facing name:** TRACE. The historical Python module names, stage labels and hashes retain `EATD` to preserve scientific provenance. **No scientific code in the released frozen implementation has been rewritten or renamed.**

## What is provided

- `code/synthetic_benchmark_v1/v6_one_shot/`: the actual v6.3 three-round proposer–adversary workflow, arm A and B comparators, evidence desk, schemas and no-cost unit tests; reconstructed by layering the earlier reviewed patch archives in order. `generator.py`, `validate_v6.py`, and `admin_score.py`, plus generator-dependent tests, intentionally reside **only in a separate administrator archive**, because they contain or access hidden causal truth.
- `code/synthetic_benchmark_v1/preflight_rebuild/transport.py`: frozen bounded request mock/transport contract.
- `code/src/stigma_framing/`: support dependencies from the earlier audited project. The guarded live runner depends on additional persistent historical budget ledgers, provider credentials and project configuration; **do not interpret this archive as a plug-and-play authorized live API service**.
- `data/.../public/development/dev_03/`: authentic baseline and follow-up synthetic datasets for the demonstration. `public/manifest.json` is the original full-manifest file; other cases are intentionally not shipped. `live_v6.py inspect` supports the included `dev_03` case only.
- `demo_locked/dev_03/`: the **unmodified scientific stage records**, sanitized original model-input prompts, plaintext output fixtures, and a SHA-256 science-only lock. The original complete 48-file lock and provider envelopes (including encrypted reasoning payloads) are retained administrator-only.
- `TECHNICAL_APPENDIX.md`: architecture and scientifically limited proof-of-concept interpretation.
- `SOURCE_MANIFEST.json`: SHA-256 file hashes and archive provenance.

## Architecture

**A (question-only ordinary chatbot):** one plain response; no background/data.  
**B (evidence-equipped ordinary chatbot):** question, neutral background and public data inventory; independently proposes at most two analyses in one batch, receives those feasible, then finalizes; no mandatory DAG or adversarial instruction.  
**C (TRACE):** constructs competing DAGs, completes **three** proposer–adversary exchanges *before seeing any test results*, freezes predictions, submits one irreversible evidence batch (at most two analyses) and adjudicates.

Data availability is disclosed neutrally and equally to B/C. The evidence service is **not** an arbitrary statistical-programming agent: it interprets a bounded family of analyses and may refuse or only partially fulfill a complex request. The actual demo documents this limitation.

## Offline demo

From the project root of this archive, Python 3.11+:

```bash
python -m pip install -r requirements.txt
export PYTHONPATH="code/synthetic_benchmark_v1/v6_one_shot:code/synthetic_benchmark_v1/preflight_rebuild:code/src"
python -m unittest discover -s code/synthetic_benchmark_v1/v6_one_shot -p 'test_v6*.py' -v
python replay_trace_dev03.py
python code/synthetic_benchmark_v1/v6_one_shot/live_v6.py inspect --case dev_03 --dataset data/synthetic_benchmark_v1/v6_synthetic_cases
python verify_locked_demo.py
```

On Windows PowerShell use `$env:PYTHONPATH="code/synthetic_benchmark_v1/v6_one_shot;code/synthetic_benchmark_v1/preflight_rebuild;code/src"` instead of `export`. Running `inspect` **does not initiate provider calls**.

The public archive runs **7 public offline unit tests**; the separately held full administrator source suite passed **55 offline tests** before packaging. `live` requires a separately authorized API connection and the full historical guarded-ledger project; **The Stage 1 artifact** is an offline replay by design; no provider calls are needed. A live harness that runs with a user-supplied API key is a Stage 2 deliverable.

## Research status and limits

The October 30, 2026 `dev_03` synthetic pilot completed A/B/C. The TRACE arm completed 3 adversarial rounds and produced frozen, competing causal graphs before receiving requested evidence; its final response challenged a restrictive serial-mechanism account using randomized framing effects from separate mediator-intervention datasets. The standard evidence-equipped baseline also generated relevant mechanisms and requested mediator interventions. **No superiority claim is made.**

The study is synthetic expressed interest, not actual organizational adoption or empirical evidence for disability-stigma mechanisms. Follow-up datasets and mediator intervention assumptions were written into the generator; intervention fidelity and transport to field organizations remain untested. The evidence desk returned an incomplete subset of each arm's requests; evaluator labels alone do not constitute graph recovery or validated causal identification. The demonstration is a process proof of concept, not a powered benchmark or independent replication.

## Sharing separation

**Public research artifact for the Stage 1 submission.**  
**Keep private:** administrator causal generator, private truth and holdout datasets; they are retained in the separately delivered `TRACE_ADMIN_PRIVATE_REPRODUCIBILITY.zip` archive.  
No API keys or credential files, encrypted reasoning contents, private causal equations, or holdout files are included.
