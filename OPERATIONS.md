# VisionQC 运行与验证

## 三分钟体验

### 完全不懂代码：双击启动（macOS）

1. 安装并启动 [Docker Desktop](https://www.docker.com/products/docker-desktop/)。
2. 在项目文件夹中双击 `start-demo.command`。
3. 浏览器打开后，点击首页的“使用演示图片开始”。
4. 体验结束后双击 `stop-demo.command`。

详细截图式说明、常见问题和术语解释见 [零基础使用指南](docs/BEGINNER-GUIDE.md)。

### 熟悉终端：命令启动

```bash
cd infra
docker compose up --build
```

服务就绪后打开：

- Web UI：[http://localhost:3000](http://localhost:3000)
- API 文档：[http://localhost:8000/docs](http://localhost:8000/docs)
- Factory A/B Gateway 状态：`8091 / 8092`

推荐演示路径：

1. 在运营总览确认租户、Gateway 和待复核队列。
2. 上传异常图片，查看异常分数、热力图和策略证据。
3. 在复核工作台确认异常并触发批次暂扣。
4. 在质量事件中查看 MES/QMS 幂等动作并完成验证关闭。
5. 在 ModelOps 查看数据来源、Benchmark NO-GO 和模型 DRAFT 状态。

完整口播和镜头表见 [三分钟演示脚本](docs/DEMO-SCRIPT.md)。停止环境：

```bash
cd infra
docker compose down
```

## 可选数据来源

项目不携带、不自动下载、也不要求 Benchmark 或客户数据。

| 来源 | 用途 | 可产生的最高状态 |
| --- | --- | --- |
| `DEMO_SYNTHETIC` | Blender 可复现合成样本与默认业务演示 | `DEMO_ONLY` |
| `OFFICIAL_BENCHMARK` | 实验室基准验证 | `READY_FOR_CUSTOMER_DATA` |
| `CUSTOMER_PILOT` | 客户现场 Pilot | 完整 provenance 与 Gate 通过后才可审批 |

受控上传会检查许可证确认、扩展名、压缩包路径穿越、特殊文件、文件数量、压缩/解压大小、压缩比和内容哈希。原始数据进入租户隔离对象存储，不进入 Git 或前端静态目录。服务端挂载导入在生产环境还必须配置 `VQC_DATASET_IMPORT_ROOTS`。

### Blender 合成演示

内置晶体管样本不是不可追溯的占位图，而是由
[`tools/blender/generate_transistor_demo.py`](tools/blender/generate_transistor_demo.py)
参数化生成。脚本会输出正常样本、弯折引脚缺陷、像素掩码、检测工位全景、SHA-256 清单和可编辑 `.blend` 场景。

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python tools/blender/generate_transistor_demo.py -- \
  --output-dir frontend/public/mock/blender \
  --blend-file artifacts/blender/visionqc-inspection-station.blend
```

Blender 合成数据只用于新手演示、接口联调和流程测试，不能替代 MVTec Benchmark，更不能证明客户现场效果。完整边界见 [Blender 合成数据说明](docs/07-blender-synthetic-data.md)。


## 完整回归

```bash
cd backend && uv sync --extra dev && uv run pytest -q
cd ../ml && uv sync --extra model --extra dev && uv run pytest -q
cd ../edge-gateway && uv sync --extra dev && uv run pytest -q
cd ../frontend && npm ci && npm test -- --run && npm run typecheck && npm run build
```

双客户 Compose 冒烟测试：

```bash
cd backend
uv run python ../scripts/compose_smoke.py
```

