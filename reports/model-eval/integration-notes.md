# ModelOps 后端集成说明

本说明定义 `ml/` 与后端/Deployment Pack 的读取合同，并补充可选数据源绑定；默认应用不要求任何数据。原始 benchmark/customer 数据不进入 Git、前端静态目录或本说明。

## 包加载与隔离

生产 worker 应在绑定前执行：

```python
from pathlib import Path
from visionqc_ml.inference import VisionQCInferenceService

service = VisionQCInferenceService.from_package(
    Path("/models/patchcore-bottle/<version>"),
    device="auto",
    expected_category="bottle",
)
health = service.health()
result = service.infer(image_path, inspection_id, evidence_root)
```

`from_package` 在加载 TorchInferencer 前验证 `model-package.json`、逐文件 hash、聚合 package hash、feature bank hash、训练/预处理/阈值/评测/manifest provenance 和 category。`expected_category` 是防止跨产品错绑的显式边界；不同 tenant/product 必须选择各自 registry 包。数据源还必须匹配 `source_type` 和不可变 dataset fingerprint。

## 输出字段映射

`InferenceResult` 保持现有 backend schema：

| ML contract | 语义 | 后端/业务使用限制 |
| --- | --- | --- |
| `model.id`, `model.version` | 模型 identity | 写入检测与审计，不得只存 current version |
| `model.feature_bank_version`, `model.package_sha256` | 特征库/包可追溯性 | 用于证据和回滚，不作为质量结论 |
| `input.sha256`, dimensions, mime | 原始图引用 | 原图与 heatmap 分开保存 |
| `anomaly.score` | `[0,1]` normalized anomaly evidence | 不改写为 defect probability |
| `anomaly.heatmap`, `overlay` | 异常区域证据 | UI 使用疑似问题/异常区域措辞 |
| `anomaly.semantic_defect_confirmed=false` | 语义边界 | 永远不能由模型置 true |
| `anomaly.root_cause_confirmed=false` | 根因边界 | 必须由授权人工/标准确认 |
| `policy.version`, thresholds, decision | 确定性双阈值路由 | `AUTO_RELEASE`、`REVIEW_REQUIRED`、`BATCH_HOLD_AND_REVIEW` 精确按边界运行 |
| `latency` | preprocess/inference/postprocess/total + warm | 用于运行监控，不直接证明质量 |

任何模型缺失、包篡改、输入非法、非有限 score 或 runtime 失败，都应进入既有 `INFERENCE_FAILED` 安全路径，不自动放行。

## Deployment Pack 映射

| Pack | category | ML model contract | 当前注意事项 |
| --- | --- | --- | --- |
| `factory_a/transistor` | `transistor` | `patchcore-transistor`, `fb-transistor-20260804` | demo pack；`DEMO_ONLY`，不得作效果声明 |
| `factory_b/bottle` | `bottle` | `patchcore-bottle`, `fb-bottle-20260802` | category demo pack；可选 benchmark/customer source 必须独立注册和绑定 |

发布流程应对照 registry 条目核验 model ID/version/category/package SHA-256/feature bank version、source type、dataset fingerprint，并保留审批摘要和 rollback target。MVTec 只能形成 `BENCHMARK_*` / `READY_FOR_CUSTOMER_DATA`，不能直接进入 ACTIVE。

## 生命周期与在线边界

`ml.registry.ModelRegistry` 是离线索引，不是在线数据库，也不替代后端权限/审计。推荐流程：

```text
package build → DRAFT → offline evaluation → EVALUATED
             → quality approval + evidence → APPROVED
             → explicit activation → ACTIVE
             → superseded/rollback → RETIRED (or explicit rollback reactivation)
```

`shadow.py` 只读 active/candidate score JSONL，输出 route diff、score delta 和回滚检查项；`feedback.py` 只校验人工反馈并生成新的离线 re-evaluation input。两者不调用 MES/QMS、不修改生产阈值、不更新 ACTIVE 包。

## 接入前检查

- 部署镜像安装与 package 相同的 `visionqc-ml[model]` lock；禁止运行时从网络下载权重。
- 挂载只读、版本化的 package 目录；健康检查必须验证 package hash 与 category。
- 每条检测保存 model/package/feature-bank/policy version 和 input hash。
- 高风险质量操作保持人工权限与确定性策略；模型 score 只提供异常证据。
- Customer Pilot 前补齐客户 provenance、站点校准、鲁棒性切片、shadow 结果、审批和回滚演练；MVTec 仅作为非商业 benchmark，不代表现场效果。
