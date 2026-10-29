# Forge Lab Provenance

This repository is an **isolated experimental copy** prepared for controlled Forge testing; it is not the upstream repository. The snapshot comes from the tracked-file tree at commit `692e05e319d1a789752fe797235798d4380e60d4` (tree `fa5ab819abdcd62bdee53dfaa2ac8f33922df1e6`) in [velantrian/velantrim-exocortex-crystal](https://github.com/velantrian/velantrim-exocortex-crystal). Git history was not copied. The source code, documentation, tests, configuration, and AGPL-3.0 license were copied without intentional production-logic changes. No secrets or credentials were identified by the preparation audit.

The three upstream GitHub Actions workflows were deliberately excluded: `.github/workflows/ci.yml`, `.github/workflows/l3-benchmark-history.yml`, and `.github/workflows/postgresql-integration.yml`. Consequently, the unmodified `tests/test_security_reproducibility_contract.py` has two checks that fail because the excluded workflow files are absent. In the complete run, the remaining suite reported 2,372 passed and 13 skipped, with 100% coverage. This repository has not been submitted to Forge.

## Proposed lab-only verification workflow (2026-10-29)

This branch introduces a new minimal `lab.yml` for Crystal-Test; it does not restore the three intentionally excluded upstream workflows or their authority. Its two Python-version jobs install development extras, compile the runtime and run the full local suite with a 100% coverage gate. It uses pinned actions, read-only repository permissions and no configured model API/secrets. It does not claim security scanning, upstream CI equivalence, production readiness or model-backed evaluation. Local and hosted results are reported separately; adding a workflow is not evidence it passed on GitHub. The two inherited tests expecting absent upstream workflows are adapted to check this lab contract while preserving the security-tool pin check. Their old upstream expectations are historical, not silently treated as satisfied.

A reusable experiment evidence template is available at `docs/lab/EXPERIMENT_TEMPLATE.md`; it does not authorize experiments or code transfers by itself.
