# VisionQC Deployment Packs

Deployment configuration is split into two versioned inputs:

- `industry-packs/*.json` contains reusable vocabulary, field mapping,
  collection modes, model reference, risk strategy, workflow, connector
  capabilities, permissions, retention and localization defaults.
- `overlays/*.json` contains tenant/site identity, products, stations, local
  collection rules and approved connector endpoints. It must contain secret
  references only, never secret values.
- `examples/*/resolved-deployment-pack.json` is the immutable runtime artifact
  produced by resolving one Industry Pack with one tenant/site overlay.

All new artifacts use `visionqc.*.v1` contracts and carry a SHA-256 over
canonical JSON with `integrity.manifest_sha256` excluded from the input. The
resolved runtime artifact uses `visionqc.deployment-pack.v2`; the backend and
edge gateway continue to read the older `visionqc.deployment-pack.v1` files
for compatibility.

Validate or generate a package with:

```bash
python scripts/visionqc.py validate-pack backend/deployment-packs/industry-packs/*.json
python scripts/visionqc.py init-tenant --industry electronics \
  --tenant-id customer-1 --output-dir ./customer-1-pack
python scripts/visionqc.py preflight \
  --pack ./customer-1-pack/resolved-deployment-pack.json --skip-network
```

The automotive-paint Industry Pack is neutral. `overlays/examples/duerr-concept.json`
is an optional independent concept overlay and is not selected by the default
CLI, Compose service or gateway settings.
