# Workflow and model-contract validation

Executed 2026-09-15 on macOS arm64, using each component's `uv.lock`.

| Component | Command from its directory | Result | Python |
|---|---|---|---|
| backend | `uv sync --extra dev && uv run pytest -q` | 37 passed, one deprecation warning | 3.13.13 |
| ml | `uv sync --extra model --extra dev && uv run pytest -q` | 36 passed, 26 runtime warnings | 3.12.13 |
| edge-gateway | `uv sync --extra dev && uv run pytest -q` | 17 passed | 3.13.13 |

The first ML run omitted `--extra model` and produced 32 passed, 3 failed, 1 skipped because optional Anomalib/Pandas were absent. Installing the documented model extra made all 36 pass. This is an environment correction, not an improved model score.

## Experiments and expected failures

- `backend/tests/test_e2e.py::test_model_failure_routes_to_review_and_never_releases` injects an inference failure and checks conservative routing.
- `backend/tests/test_api_integration.py::test_review_claim_and_decision_use_optimistic_lock` checks stale/concurrent review decisions.
- `backend/tests/test_deployment_packs.py::test_cross_tenant_pack_and_asset_reads_are_not_discoverable` checks isolation.
- `backend/tests/test_e2e.py::test_connector_final_failure_remains_recoverable` checks external-action recovery with a test connector.
- The ML suite constructs small synthetic datasets and verifies PatchCore/package contracts. These are not MVTec holdout performance measurements.

## Limits

No real factory data, physical camera or customer MES/QMS endpoint was exercised. No new production throughput or defect-reduction metric was measured. Historical `BENCHMARK_NO_GO / DRAFT_ONLY` remains valid as the recorded model decision. Frontend and Compose commands remain available in README but are outside this backend/model/edge audit run.
