# Draft immune/audit atomicity correction

Laboratory target: `velantrian/Velantrim-Exo-Cortex-Crystal-Test`.
Baseline: `b2c0063fb63992915ef80016ad4cf4b1e3c5f158`.

The existing explicit immune guard can block repeated normalized threat patterns.
Previously `record_threat` and `forget_threat` committed their mutation before
calling the audit writer in a separate transaction. If audit append failed, the
guard changed despite the operation raising an error and leaving no matching event.
Two baseline regressions reproduced both directions.

The proposal reuses `audit.append_event` on the same active SQLite connection as
the guard mutation. The existing shared audit lock is acquired before BEGIN
IMMEDIATE and held through commit/rollback; retry wraps the complete operation.
No second journal, policy owner, schema migration or background worker is added.
The optional `connection` argument does not commit/retry a caller-owned transaction
and refuses an inactive one. Callers must obey the documented shared-lock order.

Focused tests include failure before append, failure after the event/checkpoint
insertion, caller rollback and preserved record/block/unblock positive controls.
Model calls, real private content and production stores are not used.

```bash
python -m pytest -o addopts='' tests/test_immune_atomicity.py tests/test_immune.py \
  tests/test_review.py tests/test_audit.py -q
```

This fixes the existing explicit threat guard, not the meaning of curator reject.
`review.reject` still rejects a record; it does not automatically turn its content
into a threat. The earlier new-ID reentry experiment is not claimed fixed here.
No semantic paraphrase block, scope authorization, crash/power-loss, full-database
rollback protection, external attestation or legal GDPR compliance is established.
Main Crystal is untouched. Full required gates remain a pre-merge obligation.

Research context: Atlas `append-only-memory-audit`, commit
`da21abdef437812925c8332a8f6ff9bd90093faa`: mutation and its journal must be consistent.
That is an idea source; the reproduction and repair use Crystal-Test's own code.
No donor implementation or external-model discussion was copied.
