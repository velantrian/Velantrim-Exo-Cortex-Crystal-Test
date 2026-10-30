# Crystal-Test experiment template

Copy this into an experiment-specific record. `LAB_ONLY`: the lab repository is independent of the canonical Crystal runtime. A merge here, a green check, or repeated model outputs do not themselves prove upstream behavior or grant production authority.

## Identity and hypothesis

- Full lab repository name, lab base and experiment head SHA:
- Exact upstream repository and SHA used for comparison; identify whether the lab derives from it:
- Observation motivating the change, relevant source files and current behavior:
- Falsifiable hypothesis and precise scope:
- Intended user action and what remains outside the claim:

## Authority and risk boundaries

- Guardian / TruthGate / Canon ownership preserved? Cite implementation and tests.
- Does a read, model output, ranking or score cause a write or promotion? Describe all producers and consumers.
- Does it affect evidence, privacy, erasure, scope, permissions, source history, audit or receipts? Record what is retained and what is actually removed.
- Transaction boundaries, concurrent writers, restart/crash behavior, retry, recovery and resource limits:
- Known out-of-scope paths, assumptions and independent verification requirements:

## Test protocol and result

- Fixed inputs, versioned fixtures, synthetic data, exact commands and environment:
- Predeclared PASS, FAIL, BLOCKED and NOT_APPLICABLE criteria; a positive control and a negative control:
- Baseline behavior on the correct lab/upstream snapshots and final behavior on the experiment head:
- Test logs, counts, skipped cases, expected baseline failures, coverage method and exact CI URL:
- If model-backed: provider/model/version/settings, sessions, budget, no-memory baseline and actual calls. `NOT_RUN` when keys or calls are absent.
- Result and remaining limitations; no summary of planned tests as executed:

## Comparison and owner decision

- Exact patch to consider transferring and differences in upstream consumers, schema and tests:
- Whether transfer requires an explicit policy/authority decision:
- `LAB_ONLY / DRAFT / NOT MERGED` until a specific owner decision and actual merge.
