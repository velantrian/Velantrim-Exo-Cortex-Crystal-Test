#!/usr/bin/env bash
# Crystal-Test local lab smoke — not the upstream 9-job CI gate.
# Independent .github/workflows/lab.yml is allowed; upstream workflows are not.
# Fail closed: one selected interpreter, one pytest invocation, no retry fallback.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

for upstream in \
  .github/workflows/ci.yml \
  .github/workflows/l3-benchmark-history.yml \
  .github/workflows/postgresql-integration.yml
do
  if [[ -e "$upstream" ]]; then
    echo "FAIL: excluded upstream workflow must remain absent: $upstream" >&2
    exit 1
  fi
done

if ! grep -q 'upstream_snapshot_commit: 692e05e319d1a789752fe797235798d4380e60d4' FORGE_LAB_PROVENANCE.md; then
  echo "FAIL: FORGE_LAB_PROVENANCE.md missing explicit upstream snapshot pin" >&2
  exit 1
fi

if ! grep -q 'upstream_workflows_present: false' FORGE_LAB_PROVENANCE.md; then
  echo "FAIL: FORGE_LAB_PROVENANCE.md must declare upstream_workflows_present: false" >&2
  exit 1
fi

if ! grep -q 'lab_ci_is_not_canonical_crystal_proof: true' FORGE_LAB_PROVENANCE.md; then
  echo "FAIL: FORGE_LAB_PROVENANCE.md must declare lab CI is not canonical proof" >&2
  exit 1
fi

PY=""
if command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PY="$(command -v python)"
fi
if [[ -z "$PY" ]]; then
  echo "FAIL: python3/python not found" >&2
  exit 1
fi

"$PY" -m pytest -o addopts='' tests/test_security_reproducibility_contract.py -q

echo "LAB smoke OK — upstream workflows absent; lab.yml may exist but is not canonical Crystal proof."
