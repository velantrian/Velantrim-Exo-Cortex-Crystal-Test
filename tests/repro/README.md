# Repro: `supersede()` with different objects

Standalone script. It is not part of the pytest suite: the filename does
not match `test_*.py`, and `python_files` in `pyproject.toml` only collects
`test_*.py`. Do not add a pytest wrapper here.

The script never writes into the Crystal checkout. It creates a temporary
SQLite database, imports `core` from `CRYSTAL_MAIN_ROOT`, calls
`supersede(old about M, new about L)`, and prints one JSON object to stdout.

## Command

```bash
CRYSTAL_MAIN_ROOT=/path/to/velantrim-exocortex-crystal \
  python tests/repro/repro_supersede_different_objects.py
```

Example used for the recorded observation:

```bash
CRYSTAL_MAIN_ROOT=/workspace/velantrim-exocortex-crystal \
  python tests/repro/repro_supersede_different_objects.py
```

## Observed output on main Crystal `ba8e84a`

Recorded file: `observed_supersede_different_objects_ba8e84a.json`.

That run used checkout `/workspace/velantrim-exocortex-crystal` at
`ba8e84a4f8f24bdb816ea8fb89485f1dedccd0a3`. These fields follow the
machine and must not be treated as a stable contract:

- `crystal_root` — the `CRYSTAL_MAIN_ROOT` you passed
- `temp_db` — a fresh directory each run (recorded value was
  `/tmp/crystal-supersede-repro-9ymj93mr/test.db`)
- `functions.*.file` — `$CRYSTAL_MAIN_ROOT/core/reconcile.py` or
  `$CRYSTAL_MAIN_ROOT/core/memory.py`

Stable observations from that `ba8e84a` run:

- `supersede` is `core.reconcile.supersede`, lines 287–334
- `store_fact` starts at `core/memory.py:740`; `get_fact` at 934;
  `transition_esm` at 1149
- `supersede_source_mentions_object_or_period` is `[]`
- `supersede_checks_object_match` is `false`
- `facts` columns: `fact_id`, `claim`, `source`, `confidence`,
  `epistemic_state`, `claim_type`, `source_status`, `significance`,
  `created_at`, `updated_at`, `metadata`, `restricted`, `revision`
- after `store_fact`, top-level `primary_object` and `object` are absent
  (`null`); the values survive only in `metadata`
- `store_fact` of the old M record plus `transition_esm` → `Validated`
- `supersede("obj-m", new fact about L)` returns `"obj-l"` with no error
- afterwards the M record is `Deprecated` (`deprecated_m_record: true`)
- the L record is `Validated`
- `SUPERSEDED_BY` neighbor of `obj-m` is `obj-l`

The script does not change historical-read rules or the receipt digest.
