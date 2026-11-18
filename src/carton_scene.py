"""Physical scene assembly, scene evidence and deterministic render execution."""

import hashlib
import json
import os
import time
from pathlib import Path

from src.carton_dieline import build_dieline, panel_point
from src.carton_materials import build_material
from src.carton_mesh import make_geometry
from src.carton_stage import build_stage, setup_mask_output, stable_png_bytes


def scene_evidence(api, spec, objects, dieline, artwork):
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view

    scene = api.context.scene
    res = scene.render.resolution_x
    evidence = {
        "dimensions_spec_mm": spec["dimensions_mm"],
        "objects": [],
        "views": {},
        "images": [],
        "blender_version": api.app.version_string,
        "render": spec["render"],
        "artwork_spec_sha256": artwork["spec_sha256"],
    }
    evidence["runtime_render"] = {
        "engine": scene.render.engine,
        "device": scene.cycles.device,
        "samples": scene.cycles.samples,
        "seed": scene.cycles.seed,
        "animated_seed": scene.cycles.use_animated_seed,
        "adaptive_sampling": scene.cycles.use_adaptive_sampling,
        "denoiser": scene.cycles.denoiser if scene.cycles.use_denoising else "NONE",
        "denoising_device": "GPU" if scene.cycles.denoising_use_gpu else "CPU",
        "denoising_threads": int(os.environ["OIDN_NUM_THREADS"]),
        "threads": scene.render.threads if scene.render.threads_mode == "FIXED" else 0,
        "view_transform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "exposure": scene.view_settings.exposure,
        "gamma": scene.view_settings.gamma,
        "resolution": scene.render.resolution_x,
        "png_depth": scene.render.image_settings.color_depth,
        "max_bounces": scene.cycles.max_bounces,
        "transparent_bounces": scene.cycles.transparent_max_bounces,
        "filter_width": scene.render.filter_size,
        "png_compression": scene.render.image_settings.compression,
    }
    all_vertices = []
    for obj in objects:
        vertices = [obj.matrix_world @ v.co for v in obj.data.vertices]
        all_vertices.extend(vertices)
        volume = 0.0
        for polygon in obj.data.polygons:
            if len(polygon.vertices) == 3:
                a, b, c = [vertices[i] for i in polygon.vertices]
                volume += a.dot(b.cross(c)) / 6
        bounds = [
            [min(v[i] for v in vertices) * 1000, max(v[i] for v in vertices) * 1000]
            for i in range(3)
        ]
        edges: dict[tuple[int, int], list[int]] = {}
        for face in obj.data.polygons:
            ids = list(face.vertices)
            for a, b in zip(ids, ids[1:] + ids[:1]):
                key = tuple(sorted((a, b)))
                edges.setdefault(key, []).append(1 if a < b else -1)
        evidence["objects"].append(
            dict(
                name=obj.name,
                kind=obj["physical_kind"],
                scale=list(obj.scale),
                bounds_mm=bounds,
                vertices=len(vertices),
                triangles=len(obj.data.polygons),
                mesh_sha256=hashlib.sha256(
                    json.dumps(
                        [
                            [list(v.co) for v in obj.data.vertices],
                            [list(p.vertices) for p in obj.data.polygons],
                        ]
                    ).encode()
                ).hexdigest(),
                uv_sha256=hashlib.sha256(
                    json.dumps(
                        [
                            (
                                layer.name,
                                layer.active_render,
                                [list(v.uv) for v in layer.data],
                            )
                            for layer in obj.data.uv_layers
                        ]
                    ).encode()
                ).hexdigest(),
                nontriangles=sum(len(p.vertices) != 3 for p in obj.data.polygons),
                signed_volume_mm3=volume * 1e9,
                bevel_mm=obj.get("bevel_mm"),
                panel=obj.get("panel"),
                dot_height_mm=obj.get("dot_height_mm"),
                dot_diameter_mm=obj.get("dot_diameter_mm"),
                hide_render=obj.hide_render,
                nonmanifold_edges=sum(len(v) != 2 for v in edges.values()),
                bad_edge_winding=sum(sum(v) != 0 for v in edges.values()),
                crease_depth_mm=obj.get("crease_depth_mm"),
                material_names=[m.name for m in obj.data.materials],
            )
        )
    evidence["bounds_mm"] = [
        [min(v[i] for v in all_vertices) * 1000, max(v[i] for v in all_vertices) * 1000]
        for i in range(3)
    ]
    material = objects[0].data.materials[0]
    shader = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    evidence["shader_inputs"] = {
        key: {
            "linked": shader.inputs[key].is_linked,
            "node": shader.inputs[key].links[0].from_node.name
            if shader.inputs[key].is_linked
            else None,
        }
        for key in (
            "Base Color",
            "Metallic",
            "Roughness",
            "Normal",
            "Coat Weight",
            "Anisotropic",
        )
    }
    for image in api.data.images:
        if image.source == "FILE":
            evidence["images"].append(
                dict(
                    name=image.name,
                    path=api.path.abspath(image.filepath),
                    sha256=image.get("artwork_sha256"),
                    colorspace=image.colorspace_settings.name,
                    packed=bool(image.packed_file),
                    packed_sha256=hashlib.sha256(image.packed_file.data).hexdigest()
                    if image.packed_file
                    else None,
                )
            )
    for definition in spec["stage"]["cameras"]:
        name = definition["name"]
        camera = api.data.objects["camera_" + name]
        view = {
            "matrix_world": [list(row) for row in camera.matrix_world],
            "lens_mm": camera.data.lens,
            "sensor_mm": camera.data.sensor_width,
            "resolution": res,
            "panels": {},
            "elements": {},
        }

        def projected(point):
            p = world_to_camera_view(scene, camera, Vector([x / 1000 for x in point]))
            return [p.x * res, (1 - p.y) * res, p.z]

        for panel in dieline["panels"]:
            w, h = panel["size"]
            normal = Vector(panel["normal"])
            center = Vector(panel_point(panel, w / 2, h / 2)) / 1000
            visible = normal.dot(camera.location - center) > 0
            view["panels"][panel["name"]] = {
                "quad_px": [
                    projected(panel_point(panel, u, v))[:2]
                    for u, v in [(0, 0), (w, 0), (w, h), (0, h)]
                ],
                "visible": visible,
                "size_mm": panel["size"],
            }
            for element in spec["elements"]:
                if element["panel"] == panel["name"]:
                    x, y, ew, eh = element["bbox_mm"]
                    view["elements"][element["id"]] = {
                        "quad_px": [
                            projected(panel_point(panel, u, v))[:2]
                            for u, v in [
                                (x, y),
                                (x + ew, y),
                                (x + ew, y + eh),
                                (x, y + eh),
                            ]
                        ],
                        "visible": visible,
                    }
        evidence["views"][name] = view
    return evidence


def run_physical(api, job, out_path, dump_path=None, blend_path=None, view_names=None):
    start = time.perf_counter()
    physical = job["physical_baseline"]
    spec = physical["spec"]
    artwork = physical["artwork"]
    api.context.preferences.filepaths.file_preview_type = "NONE"
    api.context.preferences.filepaths.save_version = 0
    if job.get("design") or spec["mode"] != "physical_baseline":
        raise ValueError("Physical render refuses legacy design/projection")
    api.ops.object.select_all(action="SELECT")
    api.ops.object.delete(use_global=False)
    dieline = build_dieline(spec)
    material = build_material(api, spec, artwork)
    objects = make_geometry(api, spec, dieline, artwork, material)
    scene = build_stage(api, spec)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    mask_directory = out.parent / "masks"
    mask_directory.mkdir(exist_ok=True)
    mask_output = setup_mask_output(api, scene, mask_directory, "physical")
    for image in api.data.images:
        if image.source == "FILE":
            image.pack()
    api.context.view_layer.update()
    evidence = scene_evidence(api, spec, objects, dieline, artwork)
    evidence["assembly_seconds"] = time.perf_counter() - start
    evidence["render_runs"] = []
    evidence_path = Path(dump_path) if dump_path else out.with_suffix(".scene.json")

    def write_evidence():
        evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    write_evidence()
    if blend_path:
        api.ops.wm.save_as_mainfile(filepath=str(Path(blend_path).resolve()))
    if dump_path:
        return
    if not spec["render"]["reset_between_views"]:
        raise ValueError("Physical frames require an isolated scene snapshot")
    snapshot_path = out.with_suffix(".stage.blend").resolve()
    mask_output_name = mask_output.name
    api.ops.wm.save_as_mainfile(filepath=str(snapshot_path))
    snapshot_sha256 = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    evidence["render_snapshot"] = {
        "path": str(snapshot_path),
        "sha256": snapshot_sha256,
    }
    write_evidence()
    names = view_names or [c["name"] for c in spec["stage"]["cameras"]]
    for name in names:
        if name not in evidence["views"]:
            raise ValueError(f"Unknown camera {name}")
        if hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != snapshot_sha256:
            raise ValueError("Frozen scene changed between camera renders")
        # Reset renderer/depsgraph state without changing the physical scene.
        # All shots load the exact same packed scene; only camera/output changes.
        api.ops.wm.open_mainfile(filepath=str(snapshot_path))
        scene = api.context.scene
        mask_output = scene.compositing_node_group.nodes[mask_output_name]
        scene.camera = api.data.objects["camera_" + name]
        api.context.view_layer.update()
        target = out if len(names) == 1 else out.parent / f"{spec['sku']}-{name}.png"
        mask_stem = target.stem + "_mask"
        mask_output.file_name = mask_stem
        scene.render.filepath = str(target.resolve())
        before = set(mask_directory.glob(mask_stem + "*.png"))
        for old in before:
            # Non-recursive cleanup of this run's diagnostic outputs only.
            if not old.resolve().is_relative_to(mask_directory.resolve()):
                raise ValueError("Unsafe diagnostic path")
            old.unlink()
        render_start = time.perf_counter()
        api.ops.render.render(write_still=True)
        original_png = target.read_bytes()
        if spec["render"]["png_metadata_policy"] != "color_only":
            raise ValueError("Unknown PNG metadata policy")
        target.write_bytes(stable_png_bytes(original_png))
        elapsed = time.perf_counter() - render_start
        found = sorted(mask_directory.glob(mask_stem + "*.png"))
        if len(found) != 1:
            raise ValueError(f"Expected one true render mask, found {found}")
        result = dict(
            view=name,
            scene_snapshot_sha256=snapshot_sha256,
            path=str(target.resolve()),
            seconds=elapsed,
            sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            raw_png_sha256=hashlib.sha256(original_png).hexdigest(),
            png_metadata_policy=spec["render"]["png_metadata_policy"],
            mask_path=str(found[0].resolve()),
        )
        evidence["render_runs"].append(result)
        write_evidence()
        print("[physical_baseline] " + json.dumps(result))
    scene.camera = api.data.objects["camera_hero"]
    scene.render.filepath = str((out.parent / f"{spec['sku']}-hero.png").resolve())
    mask_output.file_name = f"{spec['sku']}-hero_mask"
    if blend_path:
        api.ops.wm.save_as_mainfile(filepath=str(Path(blend_path).resolve()))
