# Qualification transitions must bind the evaluated evidence

Observed: 2026-10-02, main `6e990fc`. Tracking: [Issue #8](https://github.com/wangkeyu-u/VisionQC/issues/8).

## Failure

Evaluation checked the evidence package's core digest against the registered digest and
cached its metrics and gates. Approval, activation, and rollback later verified only
the package's internal file checksums. They ignored the returned core digest and used
the cached `GO` gates.

With real API requests and synthetic evidence, replacing a passing package at the same
path with a correctly rehashed `CUSTOMER_PILOT_NO_GO` package still produced:

| Transition | Expected | Before repair |
| --- | --- | --- |
| EVALUATED → approve | 422, remain EVALUATED | 200, APPROVED |
| APPROVED → activate | 422, remain APPROVED | 200, ACTIVE |
| RETIRED → rollback | 422, remain RETIRED | 200, ACTIVE |
| RETIRED + revoked dataset → rollback | 403, remain RETIRED | 200, ACTIVE |

The unchanged-evidence lifecycle control passed before the repair. The four negative
cases failed against the old implementation, demonstrating authorization/integrity
failures rather than an invalid test setup.

## Repair

All four evidence-consuming transitions now use the same identity check: internal
checksums, model package digest, registered evidence digest, source type, and dataset
fingerprint must agree before lifecycle changes.

The core digest excludes `release-decision.json` to avoid a circular hash. Pinning that
digest alone cannot detect a changed release authorization field. Approval, activation,
and rollback also require the current release metadata to declare `GO`,
`PENDING_APPROVAL`, and `CUSTOMER_PILOT`.

Rollback now shares activation's current dataset checks: a tenant-scoped, validated
customer registration with the same fingerprint and consent is required. Evidence
verification errors return 422 before a success audit or state change.

## Reproduce

```bash
cd backend
uv sync --locked --python 3.12 --extra dev
.venv/bin/python -m pytest tests/test_model_qualification.py -q
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests
.venv/bin/mypy app
```

The qualification test module covers a valid complete lifecycle, three rehashed
replacement cases, revoked-data rollback, three corrupt-file cases, and six release
metadata cases. The release metadata cases keep the registered core digest unchanged
to isolate the need for that separate check. Existing role and missing-evidence tests
remain in place. Backend CI runs against Python 3.12 and the checked-in lockfile.

## Scope

These are synthetic API contract fixtures. Their passing metrics are test inputs and
do not represent trained-model accuracy, customer data, or a production deployment.
Historical `BENCHMARK_NO_GO / DRAFT_ONLY` reports remain valid historical evidence.

The verifier uses ordinary filesystem reads; it does not provide a transactional
snapshot against a concurrent writer. Evidence storage still needs immutable snapshots
for that guarantee. This change also does not independently recompute evaluation
metrics from raw images or provide enterprise identity integration.
