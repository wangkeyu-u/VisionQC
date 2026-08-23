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
