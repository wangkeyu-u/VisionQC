# VisionQC PatchCore 模型卡

## Model Card A：`patchcore-transistor`

- **用途**：`DEMO_SYNTHETIC` / 可选 `OFFICIAL_BENCHMARK` 晶体管异常证据与异常区域定位的离线候选，不代表任何客户现场。
- **算法**：Anomalib PatchCore 2.0.0；预训练 `wide_resnet50_2`，使用 `layer2/layer3`；客户/数据集正常样本形成 feature bank。
- **输入**：RGB 图像；resize 256×256、center crop 224×224、ImageNet mean/std；最小尺寸 32×32，最大 25M pixels。
- **输出**：`score ∈ [0,1]`、heatmap、overlay、延迟和版本引用；不输出语义 defect type、root cause 或不可逆处置。
- **版本与数据**：`1.0.0-rc1`；feature bank version `fb-transistor-20260804`；数据指纹来自固定 manifest；代码与依赖 hash 进入 package。
- **校准目标**：policy `factory-a-transistor-policy-1.0.0`；默认 pack review 0.40 / hold 0.80，benchmark/customer source 必须分别校准。
- **已知限制**：MVTec 是非商业研究 benchmark；本卡不包含客户/工厂数据；相机/光照/工艺漂移、标签不确定性、缺陷根因均未被模型解决。
- **安全使用**：高分仅触发确定性路由与人工复核；不得直接报废、返工或写入 MES/QMS。

## Model Card B：`patchcore-bottle`

- **用途**：`DEMO_SYNTHETIC` / 可选 `OFFICIAL_BENCHMARK` 瓶体异常证据与异常区域定位的离线候选，不代表任何客户现场。
- **算法**：Anomalib PatchCore 2.0.0；预训练 `resnet50`，使用 `layer2/layer3`；瓶体正常样本形成独立 feature bank。
- **输入**：RGB 图像；resize 320×320、center crop 288×288、ImageNet mean/std；最小尺寸 64×64，最大 40M pixels。
- **输出**：`score ∈ [0,1]`、heatmap、overlay、延迟和版本引用；异常不等于裂纹、污染、根因或质量 disposition。
- **版本与数据**：`2.3.0`；feature bank version `fb-bottle-20260802`；数据指纹来自独立固定 manifest；代码与依赖 hash 进入 package。
- **校准目标**：policy `factory-b-bottle-policy-2.1.0`；默认 pack review 0.28 / hold 0.68，`CELL-12` 还有站点 override，必须在客户数据 provenance 通过后重校准。
- **已知限制**：玻璃透明度和照明变化需要站点校准；当前是 category demo/adaptation placeholder，不是客户或生产模型。
- **安全使用**：高分只进入人工 review/hold 流程；禁止模型单独确认裂纹、报废或根因。

## 公共发布门槛

两张模型卡都依赖明确 `source_type`、数据 fingerprint、阈值约束、人工复核、shadow 对比和可验证回滚；`DEMO_SYNTHETIC` 结果不能替代 benchmark 或客户证据。MVTec 即使通过也只能是 `BENCHMARK_PASS / READY_FOR_CUSTOMER_DATA`。
