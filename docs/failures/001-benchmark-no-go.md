# High ranking quality failed the release policy

## Symptom
Historical transistor benchmark: image AUROC 1.000, abnormal auto-release 30%, review+hold recall 70%, hold recall 50%.

## Reproduction
Inspect [benchmark report](../../reports/benchmark-evaluation.md). Re-running model quality requires external dataset/model assets; workflow contract verification is recorded separately.

## Root Cause
The operating thresholds and policy consequences are not summarized by AUROC. This is a documented business-gate failure, not an AI-generated incident.

## Attempts
Kept candidate DRAFT; preserved report and separated benchmark source eligibility from customer pilot approval.

## Final Fix
No model-quality fix claimed. The safety control rejects promotion: BENCHMARK_NO_GO / DRAFT_ONLY.

## Remaining Risk
Real customer distributions and acceptable review burden remain unvalidated; benchmark success alone would still not authorize production.
