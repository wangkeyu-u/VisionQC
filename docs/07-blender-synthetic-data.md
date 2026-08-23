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

## 4. 扩展方式

新增缺陷时应把几何变化和像素掩码绑定在同一脚本对象组中。例如：缺失引脚、引脚偏移、外壳划伤和装夹偏位。每种变体需要独立名称、固定随机种子、缺陷描述和掩码，不得只在图片上后期绘制一个看似异常的色块。

真实 Pilot 到来后，Blender 样本继续保留为回归夹具，但模型校准、阈值和 Go/No-Go 必须只依据已登记且获授权的真实数据或正式 Benchmark。
