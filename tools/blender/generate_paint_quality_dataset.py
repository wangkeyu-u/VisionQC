"""Generate a deterministic DEMO_SYNTHETIC automotive paint-quality dataset.

This is a neutral, unbranded panel/paint-sample scene for workflow and
annotation smoke tests.  It is not a physical paint-process simulator and it
must not be used to claim production accuracy or customer pilot performance.

Example (headless Blender):

    /Applications/Blender.app/Contents/MacOS/Blender --background \
      --python tools/blender/generate_paint_quality_dataset.py -- \
      --output-dir artifacts/demo-synthetic/paint-quality \
      --count 5 --seed 20260823 \
      --blend-file artifacts/blender/paint-quality-last.blend
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import struct
import sys
import zlib
from array import array
from contextlib import suppress
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20260823
DEFECT_CLASSES = ("dust_nib", "scratch", "paint_run_sag", "orange_peel")
PAINT_COLORS = {
    "deep_blue": (0.018, 0.07, 0.22, 1.0),
    "pearl_white": (0.72, 0.78, 0.84, 1.0),
    "signal_red": (0.38, 0.025, 0.018, 1.0),
    "graphite": (0.08, 0.095, 0.12, 1.0),
    "silver": (0.42, 0.46, 0.50, 1.0),
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=240)
    parser.add_argument("--blend-file", type=Path, default=None)
    return parser.parse_args(argv)


def material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    metallic: float = 0.0,
    roughness: float = 0.42,
) -> bpy.types.Material:
    value = bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
    shader = value.node_tree.nodes.get("Principled BSDF")
    if shader is not None:
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Metallic"].default_value = metallic
        shader.inputs["Roughness"].default_value = roughness
    return value


def emission_material(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    value = material(name, color, roughness=1.0)
    shader = value.node_tree.nodes.get("Principled BSDF")
    if shader is not None:
        emission = shader.inputs.get("Emission Color") or shader.inputs.get("Emission")
        if emission is not None:
            emission.default_value = color
        strength = shader.inputs.get("Emission Strength")
        if strength is not None:
            strength.default_value = 1.0
    return value


def assign_material(obj: bpy.types.Object, value: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(value)


def look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def box(
    name: str,
    location: tuple[float, float, float],
    dimensions: tuple[float, float, float],
    value: bpy.types.Material,
    *,
    bevel: float = 0.0,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    assign_material(obj, value)
    if bevel:
        modifier = obj.modifiers.new("Panel edge softening", "BEVEL")
        modifier.width = bevel
        modifier.segments = 3
    return obj


def sphere(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    value: bpy.types.Material,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=24,
        ring_count=12,
        location=location,
    )
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    assign_material(obj, value)
    return obj


def cylinder(
    name: str,
    location: tuple[float, float, float],
    radius: float,
    depth: float,
    value: bpy.types.Material,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    assign_material(obj, value)
    return obj


def area_light(
    name: str,
    location: tuple[float, float, float],
    energy: float,
    size: float,
    color: tuple[float, float, float],
) -> bpy.types.Object:
    data = bpy.data.lights.new(name, type="AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    look_at(obj, (0.0, 0.0, 0.2))
    return obj


def configure_scene(rng: random.Random, width: int, height: int) -> bpy.types.Scene:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.compression = 35
    scene.render.film_transparent = False
    scene.render.use_file_extension = True
    scene.world = bpy.data.worlds.new("Neutral paint-quality world")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.018, 0.022, 0.03, 1.0)
        background.inputs["Strength"].default_value = 0.22
    with suppress(TypeError):
        scene.view_settings.look = "AgX - Medium High Contrast"
    # Exposure is a controlled nuisance variable, not a hidden model input.
    scene.view_settings.exposure = rng.uniform(-0.8, 0.8)
    return scene


def build_panel(scene: bpy.types.Scene, rng: random.Random) -> dict[str, Any]:
    color_name = rng.choice(sorted(PAINT_COLORS))
    paint = material(
        f"Automotive paint {color_name}",
        PAINT_COLORS[color_name],
        metallic=0.25 if color_name == "silver" else 0.08,
        roughness=rng.uniform(0.18, 0.34),
    )
    edge = material("Panel edge", (0.03, 0.038, 0.05, 1.0), roughness=0.58)
    backdrop = material("Neutral background", (0.035, 0.045, 0.06, 1.0), roughness=0.8)
    panel = box("Unbranded painted body panel", (0.0, 0.0, 0.25), (6.6, 4.6, 0.42), paint, bevel=0.22)
    edge_strip = box("Panel lower edge", (0.0, -2.05, 0.48), (6.1, 0.12, 0.12), edge, bevel=0.03)
    floor = box("Neutral capture surface", (0.0, 0.0, -0.12), (10.0, 8.0, 0.12), backdrop, bevel=0.04)
    background = box("Neutral vertical background", (0.0, 3.1, 2.5), (10.0, 0.12, 5.0), backdrop)
    del edge_strip, floor, background

    distance = rng.uniform(8.4, 11.0)
    azimuth = rng.uniform(-0.42, 0.42)
    elevation = rng.uniform(5.4, 7.4)
    camera_data = bpy.data.cameras.new("Paint inspection camera")
    camera = bpy.data.objects.new("Paint inspection camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = (math.sin(azimuth) * distance, -math.cos(azimuth) * distance, elevation)
    camera.data.lens = rng.uniform(48.0, 62.0)
    look_at(camera, (0.0, 0.0, 0.2))
    scene.camera = camera

    key_angle = rng.uniform(-0.75, 0.75)
    key = area_light(
        "Softbox key light",
        (math.sin(key_angle) * 5.5, -4.8, rng.uniform(5.5, 8.0)),
        rng.uniform(650, 1050),
        rng.uniform(2.0, 4.0),
        (1.0, rng.uniform(0.78, 0.96), rng.uniform(0.68, 0.88)),
    )
    fill = area_light(
        "Cool fill light",
        (-4.5, 2.2, rng.uniform(4.0, 6.0)),
        rng.uniform(380, 760),
        rng.uniform(2.5, 4.5),
        (0.66, 0.82, 1.0),
    )
    rim = area_light(
        "Inspection rim light",
        (rng.uniform(-2.0, 2.0), 4.0, rng.uniform(3.5, 6.5)),
        rng.uniform(250, 560),
        rng.uniform(1.2, 3.0),
        (0.78, 0.9, 1.0),
    )
    del key, fill, rim
    return {"panel": panel, "paint_color": color_name, "camera": camera}


def build_defect(
    defect_type: str,
    rng: random.Random,
) -> tuple[list[bpy.types.Object], dict[str, Any]]:
    defect_material = material("Visible defect material", (0.015, 0.008, 0.004, 1.0), roughness=0.6)
    x = rng.uniform(-2.1, 2.1)
    y = rng.uniform(-1.25, 1.25)
    z = 0.5
    objects: list[bpy.types.Object] = []
    parameters: dict[str, Any] = {"center_xy": [round(x, 4), round(y, 4)]}
    if defect_type == "dust_nib":
        radius = rng.uniform(0.08, 0.18)
        objects.append(sphere("Dust nib / particle contamination", (x, y, z + radius * 0.65), (radius, radius, radius), defect_material))
        parameters.update({"radius": round(radius, 4), "visual_model": "raised_sphere"})
    elif defect_type == "scratch":
        length = rng.uniform(0.8, 1.8)
        width = rng.uniform(0.035, 0.08)
        scratch = box("Paint surface scratch", (x, y, z + 0.015), (length, width, 0.025), defect_material, bevel=0.02)
        scratch.rotation_euler[2] = rng.uniform(-0.7, 0.7)
        objects.append(scratch)
        parameters.update({"length": round(length, 4), "width": round(width, 4), "angle": round(scratch.rotation_euler[2], 4)})
    elif defect_type == "paint_run_sag":
        length = rng.uniform(0.7, 1.45)
        width = rng.uniform(0.12, 0.26)
        run = sphere("Paint run or sag", (x, y, z + 0.035), (width, length, 0.055), defect_material)
        objects.append(run)
        parameters.update({"length": round(length, 4), "width": round(width, 4), "visual_model": "elongated_run"})
    elif defect_type == "orange_peel":
        count = rng.randint(12, 22)
        radius = rng.uniform(0.025, 0.055)
        for index in range(count):
            local_x = x + rng.uniform(-0.5, 0.5)
            local_y = y + rng.uniform(-0.38, 0.38)
            objects.append(
                sphere(
                    f"Orange peel micro texture {index}",
                    (local_x, local_y, z + radius * 0.65),
                    (radius, radius, radius * 0.35),
                    defect_material,
                )
            )
        parameters.update({"micro_bumps": count, "radius": round(radius, 4), "visual_model": "micro_bumps"})
    else:
        raise ValueError(f"unsupported defect type: {defect_type}")
    return objects, parameters


def render(scene: bpy.types.Scene, path: Path) -> None:
    scene.render.filepath = str(path.resolve())
    bpy.ops.render.render(write_still=True)
    normalize_png(path)


def normalize_png(path: Path) -> None:
    """Strip Blender's wall-clock PNG metadata for byte-stable outputs."""
    raw = path.read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"expected PNG output: {path}")
    chunks: list[tuple[bytes, bytes]] = []
    offset = 8
    idat_parts: list[bytes] = []
    while offset < len(raw):
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        kind = raw[offset + 4 : offset + 8]
        payload = raw[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IDAT":
            idat_parts.append(payload)
        elif kind in {b"IHDR", b"sRGB", b"gAMA", b"cHRM", b"PLTE", b"tRNS"}:
            chunks.append((kind, payload))
        elif kind == b"IEND":
            break
    if not idat_parts or not any(kind == b"IHDR" for kind, _ in chunks):
        raise ValueError(f"PNG is missing image data: {path}")
    deterministic_idat = zlib.compress(zlib.decompress(b"".join(idat_parts)), level=9)
    chunks.append((b"IDAT", deterministic_idat))
    chunks.append((b"IEND", b""))
    output = bytearray(b"\x89PNG\r\n\x1a\n")
    for kind, payload in chunks:
        output.extend(struct.pack(">I", len(payload)))
        output.extend(kind)
        output.extend(payload)
        output.extend(struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))
    path.write_bytes(output)


def render_mask(scene: bpy.types.Scene, defect_objects: list[bpy.types.Object], path: Path) -> None:
    white = emission_material("Mask white", (1.0, 1.0, 1.0, 1.0))
    originals = {obj.name: list(obj.data.materials) for obj in bpy.context.scene.objects if obj.type == "MESH"}
    hidden = {obj.name: obj.hide_render for obj in bpy.context.scene.objects}
    for obj in bpy.context.scene.objects:
        obj.hide_render = obj.type != "MESH" or obj not in defect_objects
    for obj in defect_objects:
        assign_material(obj, white)
    background = scene.world.node_tree.nodes.get("Background")
    old_color = background.inputs["Color"].default_value[:] if background else None
    old_strength = background.inputs["Strength"].default_value if background else None
    if background:
        background.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        background.inputs["Strength"].default_value = 0.0
    render(scene, path)
    # Convert anti-aliased render edges to a true binary mask so downstream
    # annotation checks can distinguish evidence from a display artifact.
    source = bpy.data.images.load(str(path.resolve()), check_existing=False)
    width, height = int(source.size[0]), int(source.size[1])
    source_pixels = array("f", [0.0]) * (width * height * 4)
    source.pixels.foreach_get(source_pixels)
    binary_pixels = array("f", [0.0]) * (width * height * 4)
    for index in range(0, len(source_pixels), 4):
        value = 1.0 if max(source_pixels[index : index + 3]) >= 0.5 else 0.0
        binary_pixels[index] = value
        binary_pixels[index + 1] = value
        binary_pixels[index + 2] = value
        binary_pixels[index + 3] = 1.0
    binary = bpy.data.images.new("Binary defect mask", width=width, height=height, alpha=True)
    binary.colorspace_settings.name = "Non-Color"
    binary.pixels.foreach_set(binary_pixels)
    binary.filepath_raw = str(path.resolve())
    binary.file_format = "PNG"
    binary.save()
    normalize_png(path)
    bpy.data.images.remove(binary)
    bpy.data.images.remove(source)
    for obj in bpy.context.scene.objects:
        obj.hide_render = hidden[obj.name]
        if obj.type == "MESH":
            obj.data.materials.clear()
            for value in originals[obj.name]:
                obj.data.materials.append(value)
    if background and old_color is not None and old_strength is not None:
        background.inputs["Color"].default_value = old_color
        background.inputs["Strength"].default_value = old_strength


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def blender_version() -> str:
    return ".".join(str(value) for value in bpy.app.version)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> None:
    args = parse_args()
    if args.count < 1:
        raise SystemExit("--count must be positive")
    if args.width < 32 or args.height < 32:
        raise SystemExit("--width and --height must be at least 32")
    output_dir = args.output_dir.resolve()
    rgb_dir = output_dir / "rgb"
    mask_dir = output_dir / "masks"
    annotation_dir = output_dir / "annotations"
    for directory in (rgb_dir, mask_dir, annotation_dir):
        directory.mkdir(parents=True, exist_ok=True)

    samples: list[dict[str, Any]] = []
    for index in range(args.count):
        sample_seed = args.seed + index * 1009
        sample_rng = random.Random(sample_seed)
        scene = configure_scene(sample_rng, args.width, args.height)
        panel = build_panel(scene, sample_rng)
        defect_type = "normal" if index % (len(DEFECT_CLASSES) + 1) == 0 else DEFECT_CLASSES[(index - 1) % len(DEFECT_CLASSES)]
        defect_objects: list[bpy.types.Object] = []
        parameters: dict[str, Any] = {}
        if defect_type != "normal":
            defect_objects, parameters = build_defect(defect_type, sample_rng)
        sample_id = f"paint-panel-{index + 1:04d}"
        rgb_path = rgb_dir / f"{sample_id}.png"
        mask_path = mask_dir / f"{sample_id}.png"
        render(scene, rgb_path)
        render_mask(scene, defect_objects, mask_path)
        label = 0 if defect_type == "normal" else 1
        annotation = {
            "schema_version": "visionqc.paint-quality-annotation.v1",
            "sample_id": sample_id,
            "source_type": "DEMO_SYNTHETIC",
            "label": label,
            "anomaly_subtype": "good" if label == 0 else defect_type,
            "defect_type": defect_type,
            "seed": sample_seed,
            "generator_version": GENERATOR_VERSION,
            "blender_version": blender_version(),
            "parameters": {
                "paint_color": panel["paint_color"],
                "exposure": round(float(scene.view_settings.exposure), 4),
                "camera_location": [round(float(item), 4) for item in panel["camera"].location],
                "camera_lens": round(float(panel["camera"].data.lens), 4),
                "defect": parameters,
            },
            "usage_boundary": "DEMO_SYNTHETIC / workflow smoke only; not production or customer accuracy evidence",
            "files": {
                "rgb": f"rgb/{rgb_path.name}",
                "mask": f"masks/{mask_path.name}",
                "annotation": f"annotations/{sample_id}.json",
            },
        }
        annotation["files"]["rgb_sha256"] = sha256(rgb_path)
        annotation["files"]["mask_sha256"] = sha256(mask_path)
        annotation_path = annotation_dir / f"{sample_id}.json"
        annotation_path.write_text(json.dumps(annotation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        samples.append(annotation)
        if args.blend_file and index == args.count - 1:
            args.blend_file.resolve().parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=str(args.blend_file.resolve()))

    manifest = {
        "schema_version": "visionqc.synthetic.paint-quality-manifest.v1",
        "source_type": "DEMO_SYNTHETIC",
        "generator": {
            "name": "generate_paint_quality_dataset.py",
            "version": GENERATOR_VERSION,
            "blender_version": blender_version(),
        },
        "seed": args.seed,
        "count": len(samples),
        "image_size": {"width": args.width, "height": args.height},
        "defect_classes": list(DEFECT_CLASSES),
        "samples": samples,
        "usage_boundary": "Synthetic demo evidence only. Do not claim factory accuracy, MVTec performance, or customer pilot results.",
    }
    manifest["content_fingerprint"] = canonical_hash(manifest["samples"])
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output_dir": str(output_dir), "count": len(samples), "content_fingerprint": manifest["content_fingerprint"]}))


if __name__ == "__main__":
    main()
