"""Independent image/geometry QA. Only this rebuild module reads photographs."""

from __future__ import annotations
import json
import hashlib
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from src.carton_spec import srgb_lab, verify_generated, workspace_root


def delta_e00(lab1, lab2):
    """CIEDE2000, unit weighting; scalar implementation of the standard."""
    l1, a1, b1 = map(float, lab1)
    l2, a2, b2 = map(float, lab2)
    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    mean_c = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(mean_c**7 / (mean_c**7 + 25**7)))
    ap1 = (1 + g) * a1
    ap2 = (1 + g) * a2
    cp1 = math.hypot(ap1, b1)
    cp2 = math.hypot(ap2, b2)
    hp1 = math.degrees(math.atan2(b1, ap1)) % 360
    hp2 = math.degrees(math.atan2(b2, ap2)) % 360
    dl = l2 - l1
    dc = cp2 - cp1
    dh = hp2 - hp1
    if cp1 * cp2 == 0:
        dh = 0
    elif dh > 180:
        dh -= 360
    elif dh < -180:
        dh += 360
    d_h = 2 * math.sqrt(cp1 * cp2) * math.sin(math.radians(dh / 2))
    ml = (l1 + l2) / 2
    mc = (cp1 + cp2) / 2
    if cp1 * cp2 == 0:
        mh = hp1 + hp2
    elif abs(hp1 - hp2) <= 180:
        mh = (hp1 + hp2) / 2
    elif hp1 + hp2 < 360:
        mh = (hp1 + hp2 + 360) / 2
    else:
        mh = (hp1 + hp2 - 360) / 2
    t = (
        1
        - 0.17 * math.cos(math.radians(mh - 30))
        + 0.24 * math.cos(math.radians(2 * mh))
        + 0.32 * math.cos(math.radians(3 * mh + 6))
        - 0.20 * math.cos(math.radians(4 * mh - 63))
    )
    sl = 1 + 0.015 * (ml - 50) ** 2 / math.sqrt(20 + (ml - 50) ** 2)
    sc = 1 + 0.045 * mc
    sh = 1 + 0.015 * mc * t
    rt = (
        -2
        * math.sqrt(mc**7 / (mc**7 + 25**7))
        * math.sin(math.radians(60 * math.exp(-(((mh - 275) / 25) ** 2))))
    )
    return math.sqrt(
        (dl / sl) ** 2 + (dc / sc) ** 2 + (d_h / sh) ** 2 + rt * (dc / sc) * (d_h / sh)
    )


def measure_reference(path, patches=None):
    """Fixed clean front-face control patches, never exported as artwork."""
    pixels = np.asarray(Image.open(path).convert("RGB"))
    patches = (
        patches
        if patches is not None
        else {"navy": [315, 470, 30, 90], "paper": [670, 450, 75, 60]}
    )
    result = {}
    for name, (x, y, w, h) in patches.items():
        rgb = np.median(pixels[y : y + h, x : x + w, :].reshape(-1, 3), axis=0)
        result[name] = {
            "rgb": rgb.tolist(),
            "lab": srgb_lab(rgb / 255),
            "patch_px": [x, y, w, h],
            "source": "measured",
        }
    return result


def homography(quad, width, height):
    source = [(0, 0), (width, 0), (width, height), (0, height)]
    a = []
    b = []
    for (x, y), (u, v) in zip(source, quad):
        a.extend(
            [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        )
        b.extend([u, v])
    h = np.append(np.linalg.solve(np.asarray(a), np.asarray(b)), 1).reshape(3, 3)
    return h


def map_points(h, points):
    p = np.column_stack([np.asarray(points), np.ones(len(points))]) @ h.T
    return p[:, :2] / p[:, 2:]


def sample_panel_patch(image, quad, size, rect):
    h = homography(quad, *size)
    x, y, w, height = rect
    xx, yy = np.meshgrid(np.linspace(x, x + w, 30), np.linspace(y, y + height, 30))
    points = map_points(h, np.column_stack([xx.ravel(), yy.ravel()]))
    indices = np.rint(points).astype(int)
    valid = (
        (indices[:, 0] >= 0)
        & (indices[:, 0] < image.shape[1])
        & (indices[:, 1] >= 0)
        & (indices[:, 1] < image.shape[0])
    )
    if valid.mean() < 0.99:
        raise ValueError("Colour control patch is outside the image")
    values = image[indices[valid, 1], indices[valid, 0], :3]
    return np.median(values, axis=0)


def convex_hull(points):
    points = sorted(set(tuple(p) for p in points))

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def half(items):
        out: list[tuple[float, float]] = []
        for p in items:
            while len(out) >= 2 and cross(out[-2], out[-1], p) <= 0:
                out.pop()
            out.append(p)
        return out

    return half(points)[:-1] + half(list(reversed(points)))[:-1]


def analytic_silhouette(spec, view):
    d = spec["dimensions_mm"]
    w, h, depth = d["width"], d["height"], d["depth"]
    world = np.array(
        [
            [x / 1000, y / 1000, z / 1000, 1]
            for x in [-w / 2, w / 2]
            for y in [-depth / 2, depth / 2]
            for z in [0, h]
        ]
    )
    camera = world @ np.linalg.inv(np.asarray(view["matrix_world"])).T
    res = view["resolution"]
    f = view["lens_mm"] / view["sensor_mm"] * res
    points = np.column_stack(
        [
            res / 2 + f * camera[:, 0] / (-camera[:, 2]),
            res / 2 - f * camera[:, 1] / (-camera[:, 2]),
        ]
    )
    unclipped = bool(np.all((points >= 0) & (points < res)))
    mask = Image.new("L", (res, res), 0)
    ImageDraw.Draw(mask).polygon(convex_hull(points), fill=255)
    return np.asarray(mask) > 127, unclipped


def layout_metrics(spec, artwork, root=None):
    root = Path(
        root or (workspace_root() / artwork["maps"]["base_color"]["path"]).parent
    )
    ppm = artwork["dpi"] / 25.4
    rows = []
    for e in spec["elements"]:
        record = next(r for r in artwork["elements"] if r["id"] == e["id"])
        mask = np.asarray(Image.open(root / record["mask"]).convert("L")) > 127
        yy, xx = np.nonzero(mask)
        if not len(xx):
            raise ValueError(f"Empty required element {e['id']}")
        region = artwork["atlas"]["regions"][e["panel"]]
        origin = record["atlas_origin_px"]
        center = [
            (origin[0] + (xx.min() + xx.max() + 1) / 2) / ppm - region[0],
            (origin[1] + (yy.min() + yy.max() + 1) / 2) / ppm - region[1],
        ]
        box = e["bbox_mm"]
        target = [box[0] + box[2] / 2, box[1] + box[3] / 2]
        error = math.dist(center, target)
        rows.append(
            dict(
                id=e["id"],
                center_mm=center,
                target_center_mm=target,
                error_mm=error,
                pass_=error <= 1.5,
            )
        )
    return rows


def inspect_scene(spec, evidence):
    from src.carton_dieline import (
        build_dieline,
        braille_points,
        emboss_segments,
        panel_point,
    )

    measured = [b - a for a, b in evidence["bounds_mm"]]
    target = [spec["dimensions_mm"][k] for k in ("width", "depth", "height")]
    errors = [abs(a - b) / b for a, b in zip(measured, target)]
    objects = evidence["objects"]
    panels = [o for o in objects if o["kind"] == "panel"]
    issues = []
    declarations = spec.get("effects", {})
    for kind in ("foil", "braille", "emboss"):
        declaration = declarations.get(kind)
        if declaration and declaration["status"] == "absent" and any(
            obj["kind"] == kind for obj in objects
        ):
            issues.append(f"Declared absent {kind} geometry is present")
    if any(v > 0.02 for v in errors):
        issues.append("Dimensions exceed 2 percent")
    if len(panels) != 6 or any(not p.get("bevel_mm") for p in panels):
        issues.append("Six bevelled panels missing")
    dieline = build_dieline(spec)
    panel_defs = {p["name"]: p for p in dieline["panels"]}
    if {o["name"] for o in panels} != set(panel_defs):
        issues.append("Required panel names missing")
    if {o["name"] for o in objects if o["kind"] == "flap"} != {
        p["name"] for p in dieline["flaps"]
    }:
        issues.append("Required structural flaps/glue seam missing")
    required_relief = {}
    for element in spec["elements"]:
        kind = element["kind"]
        if kind not in {"braille", "emboss", "foil"}:
            continue
        panel = panel_defs[element["panel"]]
        if kind == "braille":
            points = braille_points(element)
            height = element["dot_height_mm"]
        elif kind == "emboss":
            points = [(x, y) for x, y, _, _ in emboss_segments(element)]
            height = element["height_mm"]
        else:
            x, y, w, h = element["bbox_mm"]
            points = [(x + w / 2, y + h / 2)]
            height = spec["geometry"]["foil_thickness_mm"]
        for index, (x, y) in enumerate(points):
            name = element["id"] if kind == "foil" else f"{element['id']}_{index:03}"
            required_relief[name] = (
                kind,
                panel_point(panel, x, y, height / 2),
                height,
                panel["normal"],
            )
    actual_relief = {
        o["name"]: o for o in objects if o["kind"] in {"braille", "emboss", "foil"}
    }
    if set(actual_relief) != set(required_relief):
        issues.append("Required Braille/emboss/foil geometry missing or duplicated")
    for name, (kind, center, height, normal) in required_relief.items():
        if name not in actual_relief:
            continue
        o = actual_relief[name]
        bounds = o["bounds_mm"]
        actual_center = [(a + b) / 2 for a, b in bounds]
        axis = next(i for i, n in enumerate(normal) if n)
        actual_height = bounds[axis][1] - bounds[axis][0]
        if (
            o["kind"] != kind
            or math.dist(actual_center, center) > 0.02
            or abs(actual_height - height) > 0.002
        ):
            issues.append(name + ": physical relief location/height differs from spec")
    for o in objects:
        if any(abs(v - 1) > 1e-7 for v in o["scale"]):
            issues.append(o["name"] + ": unapplied scale")
        if o["signed_volume_mm3"] <= 0:
            issues.append(o["name"] + ": inward/inconsistent normals")
        if o["nontriangles"]:
            issues.append(o["name"] + ": nontriangular geometry")
        if o["hide_render"]:
            issues.append(o["name"] + ": hidden from render")
        if o.get("bad_edge_winding", 0) or o.get("nonmanifold_edges", 0):
            issues.append(o["name"] + ": nonmanifold/inconsistent mesh edges")
    return dict(
        measured_xyz_mm=measured,
        target_xyz_mm=target,
        relative_errors=errors,
        issues=issues,
        pass_=not issues,
        braille_count=sum(o["kind"] == "braille" for o in objects),
        emboss_count=sum(o["kind"] == "emboss" for o in objects),
    )


def validate_render_snapshot(evidence):
    if not evidence["render_runs"]:
        return
    snapshot = evidence.get("render_snapshot", {})
    path = Path(snapshot.get("path", ""))
    if (
        not path.resolve().is_relative_to((workspace_root() / "renders").resolve())
        or not path.is_file()
        or hashlib.sha256(path.read_bytes()).hexdigest() != snapshot.get("sha256")
        or any(
            run.get("scene_snapshot_sha256") != snapshot["sha256"]
            for run in evidence["render_runs"]
        )
    ):
        raise ValueError("Views must use one unchanged frozen physical scene")


def evaluate(spec, artwork, evidence, targets=None):
    digest = hashlib.sha256(
        json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if (
        artwork.get("spec_sha256") != digest
        or evidence.get("artwork_spec_sha256") != digest
    ):
        raise ValueError("Spec, generated artwork and scene belong to different builds")
    verify_generated(artwork)
    validate_render_snapshot(evidence)
    targets = targets or spec["validation"]["reference_colors"]
    result = {
        "geometry": inspect_scene(spec, evidence),
        "layout": layout_metrics(spec, artwork),
        "views": {},
        "provenance": {"pass_": True},
    }
    root = workspace_root()
    allowed = (root / "assets/generated").resolve()
    expected = {r["sha256"] for r in artwork["maps"].values()}
    if (
        len(evidence["images"]) != len(artwork["maps"])
        or {r["sha256"] for r in evidence["images"]} != expected
    ):
        raise ValueError("Scene must contain exactly the current generated image set")
    for image in evidence["images"]:
        if (
            not Path(image["path"]).resolve().is_relative_to(allowed)
            or image["sha256"] not in expected
            or image.get("packed_sha256") != image["sha256"]
        ):
            raise ValueError("Scene image violates generated-map provenance")
    result["pbr"] = {
        "linked": evidence["shader_inputs"],
        "pass_": all(x["linked"] for x in evidence["shader_inputs"].values()),
    }
    if set(evidence["shader_inputs"]) != {
        "Base Color",
        "Metallic",
        "Roughness",
        "Normal",
        "Coat Weight",
        "Anisotropic",
    }:
        result["pbr"]["pass_"] = False
    for run in evidence["render_runs"]:
        for key in ("path", "mask_path"):
            if (
                not Path(run[key])
                .resolve()
                .is_relative_to((root / "renders").resolve())
            ):
                raise ValueError("Rendered evidence must be inside renders")
        if hashlib.sha256(Path(run["path"]).read_bytes()).hexdigest() != run["sha256"]:
            raise ValueError("Rendered PNG no longer matches its scene evidence")
        name = run["view"]
        view = evidence["views"][name]
        image = np.asarray(Image.open(run["path"]).convert("RGB"))
        actual = np.asarray(Image.open(run["mask_path"]).convert("L")) > 127
        expected_mask, unclipped = analytic_silhouette(spec, view)
        iou = float(np.sum(actual & expected_mask) / np.sum(actual | expected_mask))
        row = {
            "silhouette_iou": iou,
            "unclipped": unclipped,
            "silhouette_pass": iou >= 0.97 and unclipped,
            "seconds": run["seconds"],
            "performance_pass": run["seconds"] <= 300,
            "colors": {},
        }
        front = view["panels"]["front"]
        if front["visible"]:
            for patch, rect in spec["validation"]["control_regions_mm"].items():
                rgb = sample_panel_patch(
                    image, front["quad_px"], front["size_mm"], rect
                )
                lab = srgb_lab(rgb / 255)
                error = delta_e00(lab, targets[patch]["lab"])
                row["colors"][patch] = {
                    "rgb": rgb.tolist(),
                    "lab": lab,
                    "delta_e00": error,
                    "pass_": error <= 5,
                }
        # Actual rendered background immediately outside the object vs distant floor.
        dilated = (
            np.asarray(
                Image.fromarray(np.uint8(actual) * 255).filter(
                    ImageFilter.MaxFilter(31)
                )
            )
            > 127
        )
        near = dilated & ~actual
        luma = image.mean(axis=2)
        row["contact_shadow_contrast"] = (
            float(np.percentile(luma[~dilated], 90) - np.percentile(luma[near], 10))
            if near.any()
            else None
        )
        result["views"][name] = row
    return result


def material_metrics(spec, artwork, root=None):
    """Measure actual map pixels in declared paper, ink and foil zones."""
    root = Path(root or workspace_root())
    ppm = artwork["dpi"] / 25.4
    maps = {
        name: np.asarray(
            Image.open(root / record["path"]).convert(
                "RGB" if name == "normal" else "L"
            )
        )
        for name, record in artwork["maps"].items()
        if name != "base_color"
    }
    region = artwork["atlas"]["regions"]["front"]
    x, y, w, h = spec["validation"]["control_regions_mm"]["paper"]
    x0, y0 = round((region[0] + x) * ppm), round((region[1] + y) * ppm)
    paper = maps["roughness"][y0 : y0 + round(h * ppm), x0 : x0 + round(w * ppm)]
    normal = maps["normal"][y0 : y0 + round(h * ppm), x0 : x0 + round(w * ppm), :2]
    foil = maps["metallic"] > 127
    nonfoil = ~foil
    metallic_nonzero_pixels = int(np.count_nonzero(maps["metallic"]))
    foil_present = any(e["kind"] == "foil" for e in spec["elements"])
    foil_values = maps["metallic"][foil]
    foil_roughness = maps["roughness"][foil]
    paper_roughness_mean = float(paper.mean() / 255)
    paper_roughness_std = float(paper.std() / 255)
    paper_normal_xy_std = float(normal.std())
    foil_pixels = int(foil.sum())
    metallic_foil_mean = float(foil_values.mean() / 255) if foil_values.size else 0.0
    metallic_paper_mean = float(maps["metallic"][nonfoil].mean() / 255)
    roughness_foil_mean = (
        float(foil_roughness.mean() / 255) if foil_roughness.size else 0.0
    )
    absence_verified = not foil_present and metallic_nonzero_pixels == 0
    metrics = {
        "paper_roughness_mean": paper_roughness_mean,
        "paper_roughness_std": paper_roughness_std,
        "paper_normal_xy_std": paper_normal_xy_std,
        "foil_pixels": foil_pixels,
        "metallic_nonzero_pixels": metallic_nonzero_pixels,
        "metallic_foil_mean": metallic_foil_mean,
        "metallic_paper_mean": metallic_paper_mean,
        "roughness_foil_mean": roughness_foil_mean,
        "roughness_levels": int(np.unique(maps["roughness"]).size),
        "effect_status": "present" if foil_present else "absent",
        "absence_verified": absence_verified,
    }
    common_pass = bool(
        paper_roughness_std > 0
        and paper_normal_xy_std > 0
        and metallic_paper_mean < 0.01
    )
    metrics["pass_"] = bool(
        common_pass
        and (
            foil_pixels > 0
            and metallic_foil_mean > 0.99
            and roughness_foil_mean < paper_roughness_mean
            if foil_present
            else absence_verified
        )
    )
    return metrics


def relief_contrast(spec, evidence, run):
    """Local highlight-to-shadow range around the real Braille cap centres."""
    from src.carton_dieline import braille_points

    element = next((e for e in spec["elements"] if e["kind"] == "braille"), None)
    if element is None:
        declaration = spec.get("effects", {}).get("braille", {})
        return {
            "status": "not_applicable", "present": False, "dot_count": 0,
            "median_local_contrast_8bit": 0.0, "minimum_local_contrast_8bit": 0.0,
            "production_status": declaration.get("production_status", "unknown"),
            "note": "Authored absence verified by zero declared Braille geometry.",
        }
    view = evidence["views"][run["view"]]
    panel = view["panels"]["front"]
    h = homography(panel["quad_px"], *panel["size_mm"])
    centers = map_points(h, braille_points(element))
    image = np.asarray(Image.open(run["path"]).convert("RGB")).mean(axis=2)
    contrasts = []
    for cx, cy in centers:
        x, y = round(cx), round(cy)
        patch = image[max(0, y - 6) : y + 7, max(0, x - 6) : x + 7]
        contrasts.append(float(np.percentile(patch, 90) - np.percentile(patch, 10)))
    return {
        "dot_count": len(contrasts),
        "median_local_contrast_8bit": float(np.median(contrasts)),
        "minimum_local_contrast_8bit": min(contrasts),
        "note": "Image evidence only; mesh dimensions/manifoldness checked independently.",
    }


def export_review(spec, artwork, evidence, output, before_path=None):
    """Save repeatable measurements and unretouched 100-percent detail crops."""
    output = Path(output)
    root = workspace_root()
    if not output.resolve().is_relative_to((root / "reports").resolve()):
        raise ValueError("Review output must be inside reports")
    output.mkdir(parents=True, exist_ok=True)
    if spec.get("layout_profile") in {"cialis_professional", "cialis_super_active", "kamagra"} and before_path is None:
        raise ValueError("New physical profiles require an explicit before image")
    metrics = evaluate(spec, artwork, evidence)
    metrics["material_maps"] = material_metrics(spec, artwork)
    metrics["runtime_render"] = evidence["runtime_render"]
    metrics["assembly_seconds"] = evidence["assembly_seconds"]
    metrics["artwork_seconds"] = artwork["generation_seconds"]
    metrics["layout_max_error_mm"] = max(r["error_mm"] for r in metrics["layout"])
    metrics["visibility"] = {
        name: {panel: details["visible"] for panel, details in view["panels"].items()}
        for name, view in evidence["views"].items()
    }
    for run in evidence["render_runs"]:
        view = evidence["views"][run["view"]]
        frame = Image.open(run["path"]).convert("RGB")
        mask = np.asarray(Image.open(run["mask_path"]).convert("L")) > 127
        analytic, _ = analytic_silhouette(spec, view)
        overlay = np.asarray(frame).copy()
        overlay[mask & ~analytic] = [255, 0, 0]
        overlay[analytic & ~mask] = [0, 255, 255]
        Image.fromarray(overlay).save(output / f"{run['view']}-silhouette-overlay.png")
        if run["view"] == "hero":
            metrics["braille_render"] = relief_contrast(spec, evidence, run)
            identifiers = [e["id"] for e in spec["elements"] if e["panel"] == "front"]
            for identifier in identifiers:
                if identifier not in view["elements"]:
                    continue
                q = np.asarray(view["elements"][identifier]["quad_px"])
                lo = np.floor(q.min(axis=0) - 12).astype(int)
                hi = np.ceil(q.max(axis=0) + 12).astype(int)
                frame.crop(
                    (
                        max(0, lo[0]),
                        max(0, lo[1]),
                        min(frame.width, hi[0]),
                        min(frame.height, hi[1]),
                    )
                ).save(output / f"{identifier}-100percent.png")
            before = Image.open(
                before_path or root / "renders/baseline_before.png"
            ).convert("RGB")
            if before.size != frame.size:
                raise ValueError("Before image dimensions must match the rendered frame")
            diff = np.abs(
                np.asarray(frame, dtype=np.int16) - np.asarray(before, dtype=np.int16)
            ).astype(np.uint8)
            Image.fromarray(diff).save(output / "before-after-absolute-difference.png")
            comparison = Image.new("RGB", (frame.width * 2, frame.height))
            comparison.paste(before, (0, 0))
            comparison.paste(frame, (frame.width, 0))
            comparison.save(output / "before-after.png")
            metrics["before_after_mae_8bit"] = float(diff.mean())
    metrics["numeric_gates_pass"] = bool(
        metrics["geometry"]["pass_"]
        and metrics["pbr"]["pass_"]
        and all(r["pass_"] for r in metrics["layout"])
        and metrics["material_maps"]["pass_"]
        and len(metrics["views"]) == 4
        and all(
            v["silhouette_pass"]
            and v["performance_pass"]
            and all(c["pass_"] for c in v["colors"].values())
            for v in metrics["views"].values()
        )
        and metrics["assembly_seconds"] + metrics["artwork_seconds"] <= 60
    )
    def require_finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Non-finite runtime metric")
        if isinstance(value, dict):
            for item in value.values():
                require_finite(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                require_finite(item)

    require_finite(metrics)
    (output / "metrics.json").write_text(
        json.dumps(metrics, indent=2, allow_nan=False), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    import argparse
    from src.carton_spec import load_spec

    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--before", type=Path)
    args = parser.parse_args()
    root = workspace_root()
    if not args.scene.resolve().is_relative_to(root.resolve()):
        raise ValueError("Scene evidence must be inside workspace")
    evidence = json.loads(args.scene.read_text("utf-8"))
    spec = load_spec(args.spec)
    artwork = json.loads(
        (root / "assets/generated" / spec["sku"] / "artwork-manifest.json").read_text(
            "utf-8"
        )
    )
    result = export_review(spec, artwork, evidence, args.output, args.before)
    print(
        json.dumps(
            {
                "numeric_gates_pass": result["numeric_gates_pass"],
                "views": result["views"],
                "layout_max_error_mm": result["layout_max_error_mm"],
            },
            indent=2,
        )
    )
    raise SystemExit(0 if result["numeric_gates_pass"] else 1)
