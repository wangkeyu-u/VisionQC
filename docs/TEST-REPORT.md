# VisionQC for Dürr — 验收测试报告

日期：2026-08-24（Asia/Shanghai）

> 本项目是面向 Dürr 业务场景设计的独立作品集概念方案 / Independent portfolio concept; not commissioned or endorsed by Dürr。`dxq_mock`、MES 和 QMS 均为 simulated/mock 适配器，不是真实 DXQ API。

## 结论摘要

工程闭环已实现并通过可执行的后端、边缘网关、前端、门禁校准、部署包和合成数据验证。真实 benchmark 的已登记历史证据按当前 `visionqc-pilot-gates.v3` 重新审计后仍为 `BENCHMARK_NO_GO / DRAFT_ONLY`，没有被改口径为通过。

当前不能宣称生产准确率，也不能宣称真实 Dürr 集成。完整正式 PatchCore 运行和 Compose 端到端启动分别受本机缺少可选 ML 运行时和 Docker daemon 阻塞；这些状态已在下面列出。

## 基线与最终回归

| 范围 | 迭代前基线 | 当前最终结果 |
| --- | --- | --- |
| Backend | `37 passed, 1 warning` | `42 passed, 1 warning` |
| Edge Gateway | `17 passed` | `21 passed` |
| Frontend | `9 passed`; typecheck/build 通过 | `10 passed`; typecheck/build 通过 |
| ML | `32 passed, 1 skipped, 3 failed`（PatchCore 可选运行时缺失） | `36 passed, 1 skipped, 3 failed`（同一环境阻塞） |
| ML qualification/calibration | — | `17 passed` |
| Backend/Edge/ML lint & typecheck | Backend 有 2 个既有 import-sort；其余通过 | Backend、Edge、ML Ruff 与 mypy 全部通过 |

关键命令：

```bash
cd backend && uv run pytest -q
cd ../edge-gateway && uv run pytest -q
cd ../ml && uv run pytest -q
cd ../frontend && npm test -- --run && npm run typecheck && npm run build
```

ML 的 3 个失败是：`anomalib` 未安装的 PatchCore contract test 以及两个需要 `pandas`/Anomalib 的训练 smoke；代码会明确抛出 `ModelRuntimeUnavailable`，没有用 stub 结果伪造通过。当前 ML 环境是 Python 3.13，而项目的可选模型运行时要求 Python 3.10–3.12。

## Pilot Gate Recovery

- 门禁版本：`visionqc-pilot-gates.v3`。
- 阈值只接受 `validation`；非 validation source 会产生 `threshold_source_split=FAIL`，并且 `write_qualification_package` 已有回归测试确保该字段不会被丢失。
- `defect_error_auto_release_rate <= 0.0` 是 `HARD_GATE`。
- `review_hold_recall >= 0.95`、`hold_recall >= 0.80` 是 `HARD_GATE`。
- `normal_review_hold_rate <= 0.35` 是明确的 `OPERATIONAL_TARGET`；数据不足时为 `INSUFFICIENT_EVIDENCE`，不篡改阈值。
- OOD、坏图、模糊、欠曝、过曝、低对比度和推理失败均安全降级到人工复核/Hold，不能自动放行。
- 历史 transistor MVTec 证据的真实结果仍是：异常自动放行 `0.30`、Review + Hold recall `0.70`、Hold recall `0.50`；因此仍为 `NO-GO / DRAFT_ONLY`。`image AUROC=1.0` 和 P95 `96.6 ms` 不足以覆盖安全门禁。
- 证据包包含机器可读 gates、confusion matrix、分组指标、validation provenance、holdout 使用声明、SHA-256 inventory、运行限制和人类可读报告。现有包已重算 v3 摘要与清单。

报告文件：

- [Factory A transistor evaluation report](../reports/pilot-qualification/Factory%20A/transistor/evaluation-report.md)
- [Factory A release decision](../reports/pilot-qualification/Factory%20A/transistor/release-decision.json)
- [Factory B bottle insufficient-evidence report](../reports/pilot-qualification/Factory%20B/bottle/evaluation-report.md)
- [Historical MVTec run summary](../reports/pilot-qualification/real-mvtec-run.json)

历史 evidence package 的 Backend manifest/digest 检查通过；ML 侧当前无法重新检查 source-evidence 中指向的历史 `ml/.artifacts` 文件，因为这些文件不在本 worktree，报告中明确标为 `BLOCKED_SOURCE_ARTIFACTS_UNAVAILABLE`。不把历史校验结果冒充为当前重新执行。

## Blender 合成数据 smoke

命令：

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python tools/blender/generate_paint_quality_dataset.py -- \
  --output-dir /tmp/visionqc-paint-final-a.phRVWp \
  --count 5 --seed 20260823 --width 160 --height 120
python3 tools/blender/validate_paint_quality_manifest.py /tmp/visionqc-paint-final-a.phRVWp
```

两次独立 headless 运行均为 Blender `5.2.0 LTS`，均得到 5 张 RGB、5 张二值 mask 和一致的 content fingerprint：`c266650c70d86019b0ac946fa474b5d24c2ca20b8a9852854f143bf699a86622`。

类别计数均为 `normal=1`、`dust_nib=1`、`scratch=1`、`paint_run_sag=1`、`orange_peel=1`。同一 RGB 文件 SHA-1 为 `fbdd44ca04555dcaec0eea74c9927e80b3e591b5`，同一 mask 文件 SHA-1 为 `156f037d8f600468d50842db853c2378d429ffde`。manifest validator 通过，输出固定为 `DEMO_SYNTHETIC`；这批图不是物理喷涂仿真，也不是生产效果证据。

Blender 报告了 5.2 对 `World.use_nodes`/`Material.use_nodes` 的弃用提醒，不影响当前 smoke；后续 Blender 6 迁移时需要更新 API。

## 真实输入与闭环测试

- Folder watcher：坏图、重复文件、文件夹路径和状态提示覆盖。
- USB camera：OpenCV 可选依赖，缺少依赖时返回中文可执行错误；测试使用 mock camera，不假设本机有摄像头。
- Privacy：默认本地处理；上传必须同时满足显式 consent、用途和配置开关，队列支持断网、本地 spool、重试、幂等和恢复。
- Retention：支持按期限清理本地 spool；上传成功后是否删除原图由显式 `delete_after_upload` 控制。
- Dürr：`duerr-demo` Deployment Pack 与 Factory A/B 隔离回归通过；`dxq_mock` contract、重复发布幂等和关闭事件测试通过。
- UI：中文新手向导提供“示例图 / 文件夹 / USB 相机”三条路径，先预检再检测；检测详情展示车身数字质量档案、人工复核和 simulated MES/QMS/`dxq_mock` 闭环。

## Compose 与浏览器 QA

`docker compose -f infra/docker-compose.yml config --quiet` 通过，包含默认本地处理的基础服务和 `duerr-demo` Gateway `8093`。实际执行 `docker compose up --build -d` 时，Docker socket 指向 `/Users/wangkeyu/.colima/default/docker.sock`，本机 Colima/daemon 未运行；尝试启动 Colima 时停在磁盘镜像下载阶段并主动中断，未启动任何容器。因此 Compose API 端到端不是通过，而是环境阻塞。

Compose 恢复后可复现：

```bash
colima start
docker compose -f infra/docker-compose.yml up --build -d
python3 scripts/duerr_compose_smoke.py
```

浏览器在本地 Vite `http://127.0.0.1:4174/start` 完成关键路径视觉 QA：选择 USB 相机、确认默认“不发送原图”、进入现场设备连接页；切换 `duerr-demo` 后检查 ModelOps 页面显示 `Dürr Demo Paint Quality`、`Pilot Gate Recovery`、`DRAFT` 和不可放行提示。浏览器 QA 未上传客户原图，也未启用遥测。

## 未满足门禁与真实 Pilot 还缺什么

1. MVTec transistor 当前业务门禁失败：异常自动放行 `30%`、Review + Hold recall `70%`、Hold recall `50%`。
2. 本机没有可运行的 Anomalib/PatchCore + pandas 组合，因此没有声称本次重新训练或重新评测通过。
3. 当前 worktree 没有历史证据包引用的 `.artifacts` source files，ML 完整 source-evidence recheck 不能通过。
4. Docker daemon/Colima 不可用，Compose API E2E 尚未执行。
5. 没有真实汽车涂装现场数据、相机/灯光标定、缺陷标签、工艺参数和客户授权；因此没有生产准确率、真实 DXQ 集成或自动放行/停线能力。

真实 Pilot 前至少需要：客户批准的数据处理与保存策略、现场相机和灯光标定、正常基线、覆盖四类缺陷的人工复核标签、验证/冻结 holdout 计划、质量责任人签字、真实 MES/QMS/DXQ 协议确认，以及在本地队列、权限、监控和回滚策略上的现场验收。

## 三分钟演示路径

1. `cd frontend && npm run dev -- --host 127.0.0.1 --port 4174`，打开 `/start`。
2. 选择“示例图”，确认 `DEMO_SYNTHETIC` 和默认本地处理，开始检测。
3. 打开检测详情：查看异常热力图、车身数字质量档案和质量信息。
4. 进入人工复核，选择 `INVESTIGATE`/`HOLD`，确认审计时间线。
5. 进入质量事件，展示 simulated MES/QMS 与 `dxq_mock` 的幂等外部动作；强调没有调用真实 DXQ API。
6. 切换租户到 `Dürr Demo Paint Quality`，打开 ModelOps，展示 v3 门禁、`DRAFT` 和未满足项；再切回 Factory A/B 验证多租户边界。
