# Repro: `supersede()` with different objects

This is an observation script, not a regression test. It is not part of
the pytest suite: the filename does not match `test_*.py`, and
`python_files` in `pyproject.toml` only collects `test_*.py`. Do not add
a pytest wrapper here. A passing run records what the named Crystal
checkout did; it is not a CI gate for Crystal-Test.

The script never writes into the Crystal checkout. It creates a temporary
SQLite database, imports `core` from `CRYSTAL_MAIN_ROOT`, calls
`supersede(old about M, new about L)`, and prints one JSON object to
stdout.

## Normal reproduction mode

The script first checks that `CRYSTAL_MAIN_ROOT` is a clean git checkout
of the full expected commit
`ba8e84a4f8f24bdb816ea8fb89485f1dedccd0a3`. Clean means
`git status --porcelain --untracked-files=all` is empty: any tracked
modification or untracked file makes the tree dirty. It does not pass
`--ignored`, so gitignored files are not listed.

If the HEAD does not match or the tree is dirty, the script prints a JSON
error (`mode: error`, `reproduction_of_expected_head: false`) and exits
non-zero. It does not run `supersede()` and it does not clean the
checkout.

`CRYSTAL_REPRO_EXPECTED_HEAD` is not accepted in normal mode. If it is
set, the script prints a JSON error
(`error: expected_head_override_not_allowed`, `mode: error`,
`reproduction_of_expected_head: false`, `expected_head` still the pinned
SHA) and exits 1 without calling `supersede()`. An arbitrary clean commit
cannot be labeled a reproduction this way.

On a matching clean tree it runs the observation and prints JSON with
`mode: reproduction` and `reproduction_of_expected_head: true`.

```bash
CRYSTAL_MAIN_ROOT=/path/to/velantrim-exocortex-crystal \
  python tests/repro/repro_supersede_different_objects.py
```

Example used for the recorded observation:

```bash
CRYSTAL_MAIN_ROOT=/workspace/velantrim-exocortex-crystal \
  python tests/repro/repro_supersede_different_objects.py
```

## Diagnostic mode

To observe whatever version is checked out, without claiming it is a
reproduction of `ba8e84a`:

```bash
CRYSTAL_MAIN_ROOT=/path/to/velantrim-exocortex-crystal \
  python tests/repro/repro_supersede_different_objects.py --diagnostic
```

or:

```bash
CRYSTAL_MAIN_ROOT=/path/to/velantrim-exocortex-crystal \
CRYSTAL_REPRO_DIAGNOSTIC=1 \
  python tests/repro/repro_supersede_different_objects.py
```

Diagnostic mode still runs `supersede()` when HEAD or cleanliness does
not match. The JSON then has `mode: diagnostic`,
`reproduction_of_expected_head: false`, plus `crystal_head`,
`expected_head`, `checkout_clean`, and `dirty_status`.

`CRYSTAL_REPRO_EXPECTED_HEAD` is honored only in diagnostic mode. It
changes which commit `expected_head` is compared against; it does not
turn the run into `mode: reproduction`.

```bash
CRYSTAL_MAIN_ROOT=/path/to/checkout CRYSTAL_REPRO_EXPECTED_HEAD=ffffffffffffffffffffffffffffffffffffffff   python tests/repro/repro_supersede_different_objects.py --diagnostic
```

Checkout guards (head mismatch, dirty tree, and override in normal mode)
are covered by `tests/test_repro_supersede_checkout.py`. Those tests use
temporary git repositories and do not need a Crystal checkout.

## Observed output on main Crystal `ba8e84a`

Recorded file: `observed_supersede_different_objects_ba8e84a.json`
(normal-mode observation on a clean `ba8e84a` tree). It includes
`mode: reproduction`, `reproduction_of_expected_head: true`, the full
`expected_head`, `head_matches_expected`, `checkout_clean`, and
`dirty_status`.

That run used checkout `/workspace/velantrim-exocortex-crystal` at
`ba8e84a4f8f24bdb816ea8fb89485f1dedccd0a3`. These fields follow the
machine and must not be treated as a stable contract:

- `crystal_root` — the `CRYSTAL_MAIN_ROOT` you passed
- `temp_db` — a fresh directory each run (recorded value was
  `/tmp/crystal-supersede-repro-cy4_ofvs/test.db`)
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
