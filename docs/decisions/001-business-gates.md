# Use business-risk gates in addition to AUROC

Recorded: 2026-09-15. This document retrospectively records the rationale behind the current implementation. Code-supported reasoning is an interpretation of the implementation, not a claim that an unrecorded historical experiment took place.

## Context
The transistor benchmark reports AUROC=1.000 while abnormal auto-release=30%.

## Options Considered

### Option A
Approve a model by ranking metrics alone. Pros: simple comparison. Cons: unsafe threshold outcomes can pass.

### Option B
Require release/hold/review metrics and data provenance. Pros: decisions align with workflow risk. Cons: models may remain DRAFT despite strong AUROC.

## Decision
Retain BENCHMARK_NO_GO / DRAFT_ONLY and separate source eligibility from model score.

## Why
A ranking metric does not measure the safety of a chosen operating threshold.

## Validation
[Benchmark report](../../reports/benchmark-evaluation.md); `backend/tests/test_dataset_sources.py`, `ml/tests/test_modelops.py`.

## Trade-offs
False holds create review work; benchmark data cannot establish a customer deployment result.

## What Would Change My Mind
Customer-approved data, frozen threshold protocol and acceptable risk metrics plus approval—not just improved AUROC.
