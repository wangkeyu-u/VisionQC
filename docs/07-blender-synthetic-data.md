# Blender 合成数据与 3D 资产规范

状态：`DEMO_SYNTHETIC / DEMO_ONLY`。本规范不构成 Benchmark、客户 Pilot 或生产效果声明。

## 1. 目的

VisionQC 在没有真实客户图片时仍需提供可重复的新手演示和接口联调样本。项目使用 Blender 参数化生成工业视觉工位、产品正常状态、可见缺陷与像素掩码，解决普通占位图无法追溯、无法复现、缺陷位置不明确的问题。

Blender 资产可用于：

- 零基础用户的三分钟业务演示；
- 上传、对象存储、证据展示和人工复核联调；
- 图像尺寸、格式、指纹和租户隔离测试；
- 前端视觉回归和演示视频。

不得用于：

- 计算或宣传真实模型准确率；
- 替代 MVTec 官方 Benchmark；
- 通过 `CUSTOMER_PILOT` 数据来源门禁；
- 支持生产上线、节拍或缺陷召回率声明。

## 2. 当前资产

生成器：`tools/blender/generate_transistor_demo.py`

| 输出 | 用途 |
| --- | --- |
| `transistor-normal.png` | 正常状态参考图 |
| `transistor-bent-lead.png` | 右侧引脚弯折并带表面损伤的演示缺陷 |
| `transistor-bent-lead-mask.png` | 缺陷区域二值像素掩码 |
| `station-overview.png` | 相机、环形灯、治具和产品的工位全景 |
| `manifest.json` | Blender 版本、随机种子、尺寸、边界和文件哈希 |
| `visionqc-inspection-station.blend` | 可编辑的 Blender 源场景 |

当前场景不依赖第三方 3D 模型或商标素材。产品使用无品牌的 TO-220 风格外形，工位、相机、灯光和治具全部由脚本创建。

汽车涂装场景使用 [`tools/blender/generate_paint_quality_dataset.py`](../tools/blender/generate_paint_quality_dataset.py)，是中性无品牌的 painted body panel / body test coupon。它通过固定 seed 改变涂装颜色、三点光照、曝光、相机距离/方位/仰角/焦距和背景，并输出以下四类视觉近似缺陷：

| 类别 | 视觉近似 | 边界 |
| --- | --- | --- |
| `dust_nib` | 凸起颗粒 | 不是颗粒沉积物理仿真 |
| `scratch` | 细长表面划痕 | 不是材料断裂/反射模型 |
| `paint_run_sag` | 拉长的流挂形状 | 不是流变过程仿真 |
| `orange_peel` | 微小起伏纹理 | 不是真实喷涂纹理统计 |

每张图包含 RGB、二值 mask、annotation（类别、参数、seed、版本）和 `manifest.json` provenance。manifest 的 source type 固定为 `DEMO_SYNTHETIC`，不得拿这批图校准生产阈值或声称真实准确率。

### 可复现 smoke 与校验

```bash
PAINT_OUT="$(mktemp -d /tmp/visionqc-paint-smoke.XXXXXX)"
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python tools/blender/generate_paint_quality_dataset.py -- \
  --output-dir "$PAINT_OUT" --count 5 --seed 20260823 --width 160 --height 120 \
  --blend-file "$PAINT_OUT/last.blend"
python3 tools/blender/validate_paint_quality_manifest.py "$PAINT_OUT"
```

验证器会检查 schema、source type、四类缺陷声明、内容 fingerprint、文件 SHA-256、RGB/mask 尺寸、二值 mask、normal 空 mask 和缺陷非空 mask。重复使用同一 seed 后，应比较两个输出的 `manifest.json` 与 RGB/mask SHA-256；Blender 版本变化应作为 provenance 差异保留。

## 3. 可复现生成

macOS 安装 Blender 后，在仓库根目录运行：

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python tools/blender/generate_transistor_demo.py -- \
  --output-dir frontend/public/mock/blender \
  --blend-file artifacts/blender/visionqc-inspection-station.blend \
  --seed 20260823
```

每次成功生成后必须检查：

1. `manifest.json` 中 `source_type` 为 `DEMO_SYNTHETIC`；
2. 正常图、缺陷图、掩码和全景图均存在；
3. 掩码只有黑色背景和白色缺陷区域；
4. 界面仍显示“只验证流程，不代表真实产线”的边界；
5. 生成文件全部小于仓库 10 MB 单文件限制。

涂装数据生成命令：

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python tools/blender/generate_paint_quality_dataset.py -- \
  --output-dir artifacts/demo-synthetic/paint-quality \
  --count 8 --seed 20260823 --blend-file artifacts/blender/paint-quality-last.blend
python3 tools/blender/validate_paint_quality_manifest.py artifacts/demo-synthetic/paint-quality
```

## 4. 扩展方式

新增缺陷时应把几何变化和像素掩码绑定在同一脚本对象组中。例如：缺失引脚、引脚偏移、外壳划伤和装夹偏位。每种变体需要独立名称、固定随机种子、缺陷描述和掩码，不得只在图片上后期绘制一个看似异常的色块。

真实 Pilot 到来后，Blender 样本继续保留为回归夹具，但模型校准、阈值和 Go/No-Go 必须只依据已登记且获授权的真实数据或正式 Benchmark。
