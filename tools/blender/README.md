# Blender synthetic demo assets

This directory contains the reproducible source for VisionQC's built-in visual
inspection sample. The model, fixture, lights, cameras, defect variant and mask
are created by Blender; no external 3D asset is required.

## Generate

From the repository root on macOS:

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python tools/blender/generate_transistor_demo.py -- \
  --output-dir frontend/public/mock/blender \
  --blend-file artifacts/blender/visionqc-inspection-station.blend
```

Outputs:

- `transistor-normal.png`: normal reference sample;
- `transistor-bent-lead.png`: synthetic bent-lead defect;
- `transistor-bent-lead-mask.png`: pixel-level synthetic ground-truth mask;
- `station-overview.png`: rendered inspection-station overview;
- `manifest.json`: seed, Blender version, source boundary and SHA-256 values;
- `artifacts/blender/visionqc-inspection-station.blend`: editable source scene.

These files are `DEMO_SYNTHETIC` evidence. They are useful for onboarding,
connector smoke tests and UI demonstrations, but must not pass a customer-data
gate or support claims about production model quality.

## Automotive paint-quality panel generator

`generate_paint_quality_dataset.py` creates a neutral, unbranded painted panel
scene in headless Blender. It varies paint color, light angle, exposure,
camera distance/angle/lens and background, and emits `rgb/`, `masks/`,
`annotations/` and a provenance `manifest.json`. The required visual classes
are `dust_nib`, `scratch`, `paint_run_sag` and `orange_peel`, plus `normal`.
These are controlled visual approximations, not physical paint-process
simulation.

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python tools/blender/generate_paint_quality_dataset.py -- \
  --output-dir /tmp/visionqc-paint-smoke \
  --count 5 --seed 20260823 --width 160 --height 120
python3 tools/blender/validate_paint_quality_manifest.py /tmp/visionqc-paint-smoke
```

The validator checks deterministic manifest identity, file hashes, mask
binary-ness and normal/defect foreground consistency. All output remains
`DEMO_SYNTHETIC` and must not be presented as production accuracy evidence.
