# 评测交付验证报告

## Overall Assessment: Needs revision

实现质量门禁、`DEMO_SYNTHETIC` smoke 和 transistor 的只读 `OFFICIAL_BENCHMARK` evidence 足以证明工程/评测链路可运行，但没有客户数据；transistor 业务 gate 为 `BENCHMARK_NO_GO`。结果不应分享为现场或生产性能结论。

## Methodology Review

- 问题定义匹配：目标是异常证据、区域定位、双阈值路由和生命周期治理；没有把异常解释成 defect/root cause。
- 数据选择：配置固定了可选 MVTec AD `transistor`/`bottle`、许可证、archive hash、category-only extraction；transistor 使用用户提供的只读 evidence，bottle 未导入。
- 人群/样本：官方 benchmark 的 train/validation/test 规则已实现；`DEMO_SYNTHETIC` smoke 只含每产品 4 张 test 图，不能代表 benchmark 或现场。
- 指标：Image AUROC、阈值处 precision/recall/F1、false-accept、hold recall、Pixel AUROC/AUPRO、cold/warm latency 已实现；图像级 bootstrap CI 和样本量限制会随 evaluation JSON 输出。
- 阈值：validation-only，review 先控 false-accept，hold 再控 hold recall；约束失败有 warning，不会强行宣称通过。

## Issues Found

1. **Severity: High** — No customer data is registered; the customer-data gate blocks Pilot approval. Impact: no customer/production evidence exists.
2. **Severity: High** — The transistor benchmark candidate failed defect auto-release, review+hold recall and hold recall gates. Impact: candidate cannot move to APPROVED/ACTIVE and remains DRAFT.
3. **Severity: High** — Bottle has no optional benchmark evidence and remains `BENCHMARK_INSUFFICIENT_EVIDENCE`.
4. **Severity: Medium** — Cold/warm timing was measured on macOS CPU with MPS available but unused. Impact: it does not validate the Deployment Pack CUDA hardware targets.
5. **Severity: Medium** — Human override rate is unavailable offline by design. Impact: requires named reviewer decisions from the business workflow feedback contract.

## Calculation Spot-Checks

- Package file hashes: **Verified** for both synthetic products, including explicit feature bank files.
- Category isolation: **Verified** by package verification and bottle single-image inference with `expected_category="bottle"`.
- Threshold boundary semantics: **Verified** by policy regression tests at `< review`, `== review`, `< hold`, `== hold`.
- Manifest determinism/tamper detection: **Verified** for synthetic transistor and bottle contracts.
- Official benchmark AUROC/AUPRO: **Verified** for transistor from the read-only evidence package; business gate remains `BENCHMARK_NO_GO`.

## Visualization Review

The evaluation output uses a dependency-free HTML gallery with original, heatmap, overlay, score, thresholds, route, label and error type. The report artifact uses a native comparison chart for smoke execution status; it explicitly labels the data as synthetic and uses the chart as implementation evidence, not model quality evidence.

## Suggested Improvements

1. Register an authorized pinned benchmark file while preserving SHA-256, layout and license receipt.
2. Run both full configs, review false-positive/false-negative/gray-zone galleries, and attach human sign-off to the registry evidence summary.
3. Add customer normal/confirmed-label cohorts and site-specific robustness slices before calibration approval.
4. Re-run shadow after each candidate change and rehearse rollback to the previous ACTIVE package.

## Required Caveats for Stakeholders

- No customer, factory, or production performance is claimed in this revision; benchmark values are explicitly source-scoped.
- `DEMO_SYNTHETIC` smoke metrics are not benchmark, customer, or production quality evidence.
- Anomaly score/heatmap is not a confirmed defect type, root cause or disposition.
- MVTec AD is CC BY-NC-SA 4.0 non-commercial research data; review license terms before any commercial use.
