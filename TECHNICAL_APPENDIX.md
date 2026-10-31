# TRACE | Technical appendix (Stage 1 working draft)

## Research question and intended contribution

Can a structured adversarial AI workflow improve the development of organizational theories by forcing explicit competing causal accounts, graph-consistent predictions, and prospective selection of discriminating evidence? TRACE is designed as **an auditable method for theory refinement**. It does not assume that iterative agent debate yields superior truth recovery.

## Controlled comparison

A: ordinary chatbot, question only; B: capable evidence-equipped chatbot with the same public empirical resources as TRACE; C: TRACE with exactly three challenger/proposer rounds. A is a practical baseline; B is the relevant architectural control. A/B do not receive enforced DAG or adversarial roles. B/C receive the same neutral conceptual background, visible dataset inventory and one evidence-request opportunity (no more than two analyses). Every request and intermediate model response is checkpointed. The single-batch rule reduces post-results evidence fishing; revising theory after receiving requested evidence remains allowed.

## Full TRACE workflow

1. An initial proposer specifies two or more competing causal accounts as DAGs. DAG validity is checked structurally; arrows represent assumptions, not discovered truths.
2. Three adversarial rounds introduce causal counter-accounts, audit exclusions and revise the live priority ranking. All rounds occur before empirical evidence retrieval.
3. Proposer freezes its competing predictions and sends **one** natural-language evidence batch (up to two specific investigations) to a deterministic evidence desk. No list of preferred tests or precomputed results is provided, but the public study inventory identifies what observational/experimental datasets exist.
4. Evidence desk executes only feasible statistical analyses and returns confidence intervals/limitations where implemented. Infeasible or only partially supported requests are documented, not silently replaced by unrelated results.
5. Final adjudication updates and qualifies theoretical predictions, preserving the initial DAGs and pre-evidence exchanges.

## Demonstration (synthetic `dev_03`)

The private generating world includes both legitimacy and usefulness-related pathways, and also a small direct effect. Before evidence retrieval, the proposer–adversary exchanges broadened the two restrictive initial explanations into parallel-versus-serial accounts and froze predictions for what should happen when mediators are experimentally constrained.

Returned intervention-specific estimates on synthetic expressed adoption interest were approximately +0.605 (95% CI 0.477–0.733) with legitimacy fixed at zero, and +0.416 (0.307–0.524) with usefulness fixed at zero. The results are incompatible with some strict zero-effect predictions **under the interpretation of these manipulations as implemented**. They do not identify natural indirect effects, guarantee that latent psychological states were controlled, or uniquely establish the full causal graph. B independently requested relevant intervention evidence and produced a similarly cautious final account. The present demonstration does **not** establish that TRACE outperforms B.

## Implementation and boundary conditions

A/B/C scientific code paths are separate; EATD schemas apply only to C. The frozen v6.3 pipeline consumes eight normal scientific C model calls (one initial proposer, six critique/response calls and a final adjudication) and permits up to two technical-format repairs. A uses one, B normally two. This asymmetry is a resource difference that must be reported in all evaluations. The original API provider calls and original scientific outputs are available for verification in `demo_locked/`. Model settings, transport limits and budgeting are recorded there; this archive does not supply credentials or live historical ledger records.

The evidence service supports predefined families of analyses on preexisting synthetic datasets, not arbitrary real experiments. The frozen v6.3 run shows partial request fulfillment and imperfect receipt attribution, which restricts the strength of conclusions about discriminating-test selection. Round-to-round improvements, causal identification and superiority over ordinary AI require independent blinded assessment on fresh tasks. Human reviewers should rate the informativeness of frozen predictions, graph coherence, reasonable abstention, and whether an evidence request was feasible, with failures of the evidence desk classified separately from failures of scientific reasoning.

## Research and ethical risks

Three agent rounds can amplify shared initial bias or produce polished but unfounded explanations. Graph formatting can falsely suggest causal certainty. Simulated experiments lack ecological validity, especially for disability-related evaluation, and text-based research artifacts cannot be read as evidence about disabled people or real organizations. Separating the conceptual prototype from claims about disability stigma is essential; future validation should use independently sampled organizational problems, open and preregistered evaluation criteria, human blind reviewers, and more realistic data-access constraints.

## Next development stages

Freeze and publicly document the v6.3 process, improve evidence-request fidelity prospectively, validate epistemic calibration and genuine adversarial value on independently created tasks, and test how well TRACE transfers across theories and substantive domains. The research artifact is intended to be reusable across organizational science topics, not restricted to assistive technology.
