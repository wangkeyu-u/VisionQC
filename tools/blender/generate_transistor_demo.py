"""Generate reproducible VisionQC demo imagery with Blender.

Run from the repository root:

    /Applications/Blender.app/Contents/MacOS/Blender --background \
      --python tools/blender/generate_transistor_demo.py -- \
      --output-dir frontend/public/mock/blender \
      --blend-file artifacts/blender/visionqc-inspection-station.blend

The result is synthetic demonstration data. It must never be presented as
factory evidence, production model validation, or a substitute for a customer
Pilot dataset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from array import array
from datetime import datetime, timezone
from pathlib import Path

import bpy
from mathutils import Vector


GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20260823


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--blend-file", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args(argv)


def material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    metallic: float = 0.0,
    roughness: float = 0.45,
) -> bpy.types.Material:
    value = bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
    shader = value.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    return value


def emission_material(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    value = bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
    shader = value.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = 1.0
    emission_input = shader.inputs.get("Emission Color") or shader.inputs.get("Emission")
    if emission_input is not None:
        emission_input.default_value = color
    strength_input = shader.inputs.get("Emission Strength")
    if strength_input is not None:
        strength_input.default_value = 1.0
    ior_input = shader.inputs.get("IOR Level")
    if ior_input is not None:
        ior_input.default_value = 0.0
    return value


def assign_material(obj: bpy.types.Object, value: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(value)


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
        modifier = obj.modifiers.new("Soft industrial edges", "BEVEL")
        modifier.width = bevel
        modifier.segments = 3
    return obj


def cylinder(
    name: str,
    location: tuple[float, float, float],
    radius: float,
    depth: float,
    value: bpy.types.Material,
    *,
    vertices: int = 64,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    assign_material(obj, value)
    bevel = obj.modifiers.new("Machined edge", "BEVEL")
    bevel.width = min(radius * 0.08, 0.04)
    bevel.segments = 2
    return obj


def lead_segment(
    name: str,
    start: tuple[float, float],
    end: tuple[float, float],
    value: bpy.types.Material,
    *,
    width: float = 0.25,
    height: float = 0.11,
    z: float = 0.43,
) -> bpy.types.Object:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    obj = box(
        name,
        ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2, z),
        (width, length, height),
        value,
        bevel=0.035,
    )
    obj.rotation_euler[2] = -math.atan2(dx, dy)
    return obj


def area_light(name: str, location: tuple[float, float, float], energy: float, size: float, color: tuple[float, float, float]) -> bpy.types.Object:
    data = bpy.data.lights.new(name, type="AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    look_at(obj, (0.0, -0.35, 0.3))
    return obj


def look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def set_visible(objects: list[bpy.types.Object], visible: bool) -> None:
    for obj in objects:
        obj.hide_render = not visible
        obj.hide_viewport = not visible


def configure_scene() -> bpy.types.Scene:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.resolution_percentage = 100
    scene.render.image_settings.compression = 35
    scene.render.use_file_extension = True
    scene.render.fps = 24
    scene.world = bpy.data.worlds.new("VisionQC industrial world")
    scene.world.color = (0.01, 0.013, 0.018)
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.012, 0.017, 0.025, 1.0)
    background.inputs["Strength"].default_value = 0.24
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    return scene


def build_station() -> dict[str, object]:
    matte_black = material("Transistor body", (0.012, 0.016, 0.022, 1.0), roughness=0.32)
    edge_black = material("Body edge", (0.025, 0.03, 0.038, 1.0), roughness=0.4)
    steel = material("Tin plated copper", (0.48, 0.53, 0.58, 1.0), metallic=0.82, roughness=0.23)
    damaged_steel = material("Scuffed lead", (0.33, 0.25, 0.2, 1.0), metallic=0.55, roughness=0.48)
    belt = material("Inspection belt", (0.055, 0.067, 0.082, 1.0), roughness=0.78)
    fixture = material("Fixture blue", (0.035, 0.16, 0.26, 1.0), metallic=0.52, roughness=0.31)
    aluminum = material("Machine aluminum", (0.31, 0.36, 0.4, 1.0), metallic=0.8, roughness=0.28)
    lens = material("Camera lens", (0.004, 0.008, 0.014, 1.0), metallic=0.2, roughness=0.08)
    accent = material("Status accent", (0.08, 0.42, 0.9, 1.0), metallic=0.15, roughness=0.3)

    environment: list[bpy.types.Object] = []
    environment.append(box("Conveyor bed", (0, 0, 0), (9.2, 12, 0.48), belt, bevel=0.22))
    environment.append(box("Left guide rail", (-4.25, 0, 0.48), (0.28, 12, 0.65), aluminum, bevel=0.07))
    environment.append(box("Right guide rail", (4.25, 0, 0.48), (0.28, 12, 0.65), aluminum, bevel=0.07))
    environment.append(box("Inspection fixture", (0, -0.35, 0.31), (5.3, 6.25, 0.18), fixture, bevel=0.2))
    for x in (-2.18, 2.18):
        for y in (-2.55, 1.85):
            environment.append(cylinder(f"Locator pin {x} {y}", (x, y, 0.58), 0.13, 0.42, aluminum))

    product: list[bpy.types.Object] = []
    product.append(box("TO-220 body", (0, 0.35, 0.72), (3.1, 2.75, 0.72), matte_black, bevel=0.18))
    product.append(box("TO-220 shoulder", (0, -0.83, 0.7), (2.62, 0.42, 0.76), edge_black, bevel=0.12))
    product.append(cylinder("Mounting recess", (0, 0.95, 1.1), 0.43, 0.025, edge_black))
    product.append(cylinder("Mounting hole", (0, 0.95, 1.12), 0.25, 0.04, lens))

    common_leads = [
        lead_segment("Left lead", (-0.88, -0.88), (-0.88, -3.12), steel),
        lead_segment("Center lead", (0.0, -0.88), (0.0, -3.12), steel),
    ]
    product.extend(common_leads)

    normal_lead = [lead_segment("Right lead normal", (0.88, -0.88), (0.88, -3.12), steel)]
    defect_lead = [
        lead_segment("Right lead defect root", (0.88, -0.88), (0.88, -1.66), steel),
        lead_segment("Right lead bent tip", (0.88, -1.66), (1.52, -3.0), damaged_steel),
    ]
    scratch = box("Lead surface gouge", (1.18, -2.26, 0.505), (0.34, 0.11, 0.025), edge_black, bevel=0.02)
    scratch.rotation_euler[2] = -0.45
    defect_lead.append(scratch)
    product.extend(normal_lead + defect_lead)

    gantry: list[bpy.types.Object] = []
    for x in (-4.65, 4.65):
        gantry.append(box(f"Gantry column {x}", (x, 0.15, 3.3), (0.42, 0.62, 6.2), aluminum, bevel=0.09))
    gantry.append(box("Gantry crossbar", (0, 0.15, 6.2), (9.7, 0.7, 0.62), aluminum, bevel=0.1))
    gantry.append(box("Vision camera", (0, 0.15, 5.4), (1.25, 1.15, 1.2), fixture, bevel=0.12))
    gantry.append(cylinder("Vision lens", (0, 0.15, 4.65), 0.38, 0.52, lens))
    gantry[-1].rotation_euler[0] = 0
    gantry.append(box("Camera status", (0.44, -0.44, 5.56), (0.18, 0.035, 0.18), accent, bevel=0.03))
    bpy.ops.mesh.primitive_torus_add(major_radius=1.18, minor_radius=0.09, major_segments=64, minor_segments=12, location=(0, 0.15, 4.47))
    ring = bpy.context.object
    ring.name = "Inspection ring light"
    assign_material(ring, material("Ring light diffuser", (0.8, 0.88, 1.0, 1.0), roughness=0.18))
    gantry.append(ring)

    area_light("Key inspection light", (-3.8, -4.5, 7.5), 1050, 4.2, (0.72, 0.84, 1.0))
    area_light("Fill inspection light", (4.4, -1.2, 6.2), 820, 3.4, (1.0, 0.74, 0.52))
    area_light("Top inspection light", (0, 2.8, 8.5), 1150, 3.0, (0.8, 0.9, 1.0))

    camera_data = bpy.data.cameras.new("Inspection sample camera")
    sample_camera = bpy.data.objects.new("Inspection sample camera", camera_data)
    bpy.context.collection.objects.link(sample_camera)
    sample_camera.location = (0, -0.4, 10.2)
    sample_camera.data.type = "ORTHO"
    sample_camera.data.ortho_scale = 8.1
    look_at(sample_camera, (0, -0.4, 0.35))

    overview_data = bpy.data.cameras.new("Station overview camera")
    overview_camera = bpy.data.objects.new("Station overview camera", overview_data)
    bpy.context.collection.objects.link(overview_camera)
    overview_camera.location = (9.7, -12.5, 8.2)
    overview_camera.data.lens = 52
    look_at(overview_camera, (0, 0.2, 2.15))

    return {
        "environment": environment,
        "product": product,
        "normal_lead": normal_lead,
        "defect_lead": defect_lead,
        "defect_mask": defect_lead[1:],
        "gantry": gantry,
        "sample_camera": sample_camera,
        "overview_camera": overview_camera,
    }


def render(scene: bpy.types.Scene, output: Path, width: int, height: int) -> None:
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.filepath = str(output.resolve())
    bpy.ops.render.render(write_still=True)


def render_mask(scene: bpy.types.Scene, station: dict[str, object], output: Path) -> dict[str, int]:
    black = emission_material("Mask background", (0.0, 0.0, 0.0, 1.0))
    white = emission_material("Mask defect", (1.0, 1.0, 1.0, 1.0))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and not obj.hide_render]
    originals = {obj.name: list(obj.data.materials) for obj in objects}
    for obj in objects:
        assign_material(obj, white if obj in station["defect_mask"] else black)
    background = scene.world.node_tree.nodes.get("Background")
    old_background = background.inputs["Color"].default_value[:]
    old_strength = background.inputs["Strength"].default_value
    background.inputs["Color"].default_value = (0, 0, 0, 1)
    background.inputs["Strength"].default_value = 0
    render(scene, output, 1024, 768)
    source = bpy.data.images.load(str(output.resolve()), check_existing=False)
    width, height = int(source.size[0]), int(source.size[1])
    source_pixels = array("f", [0.0]) * (width * height * 4)
    source.pixels.foreach_get(source_pixels)
    binary_pixels = array("f", [0.0]) * (width * height * 4)
    white_pixels = 0
    for index in range(0, len(source_pixels), 4):
        value = 1.0 if max(source_pixels[index : index + 3]) >= 0.5 else 0.0
        white_pixels += int(value)
        binary_pixels[index] = value
        binary_pixels[index + 1] = value
        binary_pixels[index + 2] = value
        binary_pixels[index + 3] = 1.0
    binary = bpy.data.images.new("Binary defect mask", width=width, height=height, alpha=True)
    binary.colorspace_settings.name = "Non-Color"
    binary.pixels.foreach_set(binary_pixels)
    binary.filepath_raw = str(output.resolve())
    binary.file_format = "PNG"
    binary.save()
    bpy.data.images.remove(binary)
    bpy.data.images.remove(source)
    total_pixels = width * height
    if white_pixels == 0 or white_pixels == total_pixels:
        raise RuntimeError("binary defect mask must contain both foreground and background pixels")
    for obj in objects:
        obj.data.materials.clear()
        for value in originals[obj.name]:
            obj.data.materials.append(value)
    background.inputs["Color"].default_value = old_background
    background.inputs["Strength"].default_value = old_strength
    return {"foreground_pixels": white_pixels, "background_pixels": total_pixels - white_pixels}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    output_dir = args.output_dir.resolve()
    blend_file = args.blend_file.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    blend_file.parent.mkdir(parents=True, exist_ok=True)

    scene = configure_scene()
    station = build_station()
    scene.camera = station["sample_camera"]
    set_visible(station["gantry"], False)

    normal_path = output_dir / "transistor-normal.png"
    defect_path = output_dir / "transistor-bent-lead.png"
    mask_path = output_dir / "transistor-bent-lead-mask.png"
    overview_path = output_dir / "station-overview.png"

    set_visible(station["defect_lead"], False)
    set_visible(station["normal_lead"], True)
    render(scene, normal_path, 1024, 768)

    set_visible(station["normal_lead"], False)
    set_visible(station["defect_lead"], True)
    render(scene, defect_path, 1024, 768)
    mask_statistics = render_mask(scene, station, mask_path)

    set_visible(station["gantry"], True)
    scene.camera = station["overview_camera"]
    render(scene, overview_path, 1400, 900)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_file))

    files = [normal_path, defect_path, mask_path, overview_path]
    manifest = {
        "schema_version": "1.0",
        "generator": "Blender",
        "generator_version": GENERATOR_VERSION,
        "blender_version": bpy.app.version_string,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "source_type": "DEMO_SYNTHETIC",
        "product": "TO-220-style transistor",
        "defect": {
            "name": "bent_lead",
            "description": "Right lead is bent outward and has a visible surface gouge.",
            "normalized_bbox": [0.58, 0.53, 0.74, 0.94],
            "mask": mask_path.name,
            "mask_statistics": mask_statistics,
        },
        "camera": {
            "sample_projection": "orthographic",
            "sample_resolution": [1024, 768],
            "overview_resolution": [1400, 900],
        },
        "usage_boundary": "Synthetic demonstration data only; not factory evidence or production model validation.",
        "files": [{"name": path.name, "sha256": sha256(path), "bytes": path.stat().st_size} for path in files],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
