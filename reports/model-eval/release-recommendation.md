# VisionQC ModelOps 发布建议

## 当前建议：不批准 ACTIVE

`patchcore-transistor` 和 `patchcore-bottle` 均停留在候选阶段。当前没有客户/工厂数据；transistor 的只读官方 MVTec evidence 已接入并得到 `BENCHMARK_NO_GO`，bottle 仍缺少 benchmark evidence。不能批准、激活或绑定任何现有 Deployment Pack 的客户/生产 package URI。

## 发布门禁

| 门禁 | 必需证据 | 当前状态 |
| --- | --- | --- |
| 数据授权与导入 | `OFFICIAL_BENCHMARK` 归档、许可证确认、archive SHA-256 | transistor 已通过只读 receipt/hash 接入；bottle 未导入 |
| 固定切分 | `manifest.jsonl`、`failures.jsonl`、dataset fingerprint、split hashes | transistor manifest/split 已验证；bottle 仅 scaffold |
| PatchCore 包 | Torch weights + feature bank + preprocessing + threshold + evaluation + code commit | transistor package 已验证；bottle benchmark 包未生成 |
| 评测质量 | Image AUROC/F1/precision/recall、false-accept、hold recall、Pixel AUROC/AUPRO | transistor metrics 可用但业务 gate `NO-GO`；bottle 缺失 |
| 延迟 | cold + warm P50/P95、硬件记录 | synthetic CPU 已测；非生产硬件证据 |
| 阈值 | validation-only、目标/约束满足、样本量可接受 | smoke 两产品均失败 |
| 案例审阅 | false positive/negative/gray-zone gallery | transistor 50-case gallery 已 hash 验证；仍需人工审阅 |
| 治理 | registry EVALUATED→APPROVED→ACTIVE、审批摘要和回滚证据 | 离线 registry 合同已通过；无生产审批 |
| Shadow | active/candidate route diff 与 rollback 条件 | 离线比较器已通过；无真实候选对比 |
| 客户数据 gate | provenance、正常样本、确认标签、站点光照/相机鲁棒性 | 未提供；approval 阻断 |

## 批准前最小执行序列

1. 保持 transistor 的只读 evidence 绑定和 `BENCHMARK_NO_GO` 审计记录；如需 bottle benchmark，单独通过受控入口导入并确认 license acknowledgement、SHA-256 和类别/manifest。
2. 对 transistor 50-case gallery 做人工审阅；不要通过修改目标或读取 holdout 反向调阈值。
3. 由质量负责人审阅阈值 objective、validation 样本量、误放/hold recall 和案例画廊；如约束失败，候选保持 `DRAFT`，不人工“调到通过”。
4. 取得客户数据并提交完整 provenance；通过 customer-data gate 后再做站点校准和亮度/模糊/旋转/位移切片，candidate 与 ACTIVE 做离线 shadow。
5. 只有 Customer Pilot 证据、审批摘要、evaluation/package hash 和 rollback condition 齐全，才允许进入 APPROVED/ACTIVE；benchmark/demo 永远不能直接激活。
