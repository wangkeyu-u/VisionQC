# AI-assisted development

Codex assisted the September 2026 code review, local validation and documentation changes. Historical model reports and earlier attribution are preserved.

## Evidence from this revision

- Backend, ML and edge-gateway suites passed with 37, 36 and 17 tests respectively. Commands and environment details are in the [validation record](experiments/workflow-validation.md).
- The first ML run failed because the optional model dependencies were absent; installing the documented extra fixed the environment. It did not improve a model score.
- The historical benchmark remains `BENCHMARK_NO_GO / DRAFT_ONLY`: AUROC 1.000 did not prevent a 30% abnormal auto-release rate. This revision did not rerun the original benchmark.

The developer owns the review policy and release decision. Mock connectors, synthetic workflows and passing tests do not establish real MES/QMS integration or customer acceptance.
