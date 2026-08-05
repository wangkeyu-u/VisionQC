# Model and runtime provenance notice

The VisionQC baseline uses the following third-party components. Their licenses
remain independent from VisionQC project code.

- PatchCore method: Roth et al., "Towards Total Recall in Industrial Anomaly
  Detection" (CVPR 2022), https://arxiv.org/abs/2106.08265
- Anomalib 2.0.0 implementation: Apache License 2.0,
  https://github.com/open-edge-platform/anomalib/tree/v2.0.0
- PyTorch 2.6.0 and torchvision 0.21.0: BSD-style licenses,
  https://github.com/pytorch/pytorch and https://github.com/pytorch/vision
- `wide_resnet50_2` pretrained feature extractor: loaded by the pinned Anomalib
  and timm/torchvision runtime. The exported `model.pt` file hash covers the
  actual embedded backbone and PatchCore feature bank.

The package's `config/training.yaml`, `provenance/uv.lock`, code commit,
individual file hashes, and package hash are the reproducibility authority for a
specific candidate. Review all model, weight, dependency, and data licenses
before commercial use.

