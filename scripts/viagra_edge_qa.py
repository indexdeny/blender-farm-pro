"""Independent diagnostic ruler; never imports the producer or changes inputs.

freeze-roi must run on the saved baseline before candidate evaluation. PNG
measurements use a fixed baseline ROI and the candidate spec's projected chord,
not a fitted image line. A beauty image cannot identify material ownership:
highlights are explicitly NOT classified as geometrically exposed substrate.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


UV_TOLERANCE = 1e-6


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def part_outline(spec, role):
    fields = [f for f in spec["fields"] if f["role"] == role and f.get("surface", "front") == "front"]
    if len(fields) != 1:
        raise ValueError(f"expected one front field {role}")
    points = np.asarray(fields[0]["parts"][0]["outline"], dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 4 or not np.isfinite(points).all():
        raise ValueError("invalid outline")
    return points


def section(outline, v):
    hits = []
    for a, b in zip(outline, np.roll(outline, -1, axis=0)):
        if min(a[1], b[1])-1e-12 <= v <= max(a[1], b[1])+1e-12:
            if abs(a[1]-b[1]) < 1e-12:
                hits.extend([float(a[0]), float(b[0])])
            else:
                hits.append(float(a[0]+(b[0]-a[0])*(v-a[1])/(b[1]-a[1])))
    if not hits:
        raise ValueError("outline does not cover requested scanline")
    return min(hits), max(hits)


def edge_points(outline, side, lo=None, hi=None):
    lo = float(outline[:, 1].min()) if lo is None else lo
    hi = float(outline[:, 1].max()) if hi is None else hi
    vs = sorted(set([lo, hi] + [float(v) for v in outline[:, 1] if lo <= v <= hi]))
    return np.array([[section(outline, v)[side], v] for v in vs])


def multiple_interval_slices(outline):
    """Flag slices whose envelope alone cannot prove coverage."""
    knots = sorted(set(outline[:, 1]))
    ambiguous = []
    for lo, hi in zip(knots, knots[1:]):
        v = (lo+hi)/2
        crossings = sum(min(a[1], b[1]) < v < max(a[1], b[1])
                        for a, b in zip(outline, np.roll(outline, -1, axis=0)))
        if crossings != 2:
            ambiguous.append({"v": float(v), "crossings": int(crossings)})
    return ambiguous


def chord_metrics(points):
    start, end = points[0], points[-1]
    delta = end-start
    normal = np.array([-delta[1], delta[0]]) / np.linalg.norm(delta)
    residual = np.abs((points-start) @ normal)
    return {"max_chord_residual_uv": float(residual.max()), "chord_uv": [start.tolist(), end.tolist()],
            "vertex_count": len(points), "points_uv": points.tolist()}


def geometry_metrics(spec):
    navy, cyan = part_outline(spec, "brand"), part_outline(spec, "recovered_01")
    ambiguous = {"navy": multiple_interval_slices(navy), "cyan": multiple_interval_slices(cyan)}
    lo = max(float(navy[:, 1].min()), float(cyan[:, 1].min()))
    hi = min(float(navy[:, 1].max()), float(cyan[:, 1].max()))
    if hi <= lo:
        raise ValueError("no common seam extent")
    # Every simple envelope breakpoint is a polygon vertex. Multivalued slices
    # are explicitly reported and cannot earn a geometric PASS.
    knots = sorted(set([lo, hi] + [float(v) for v in np.r_[navy[:, 1], cyan[:, 1]] if lo < v < hi]))
    samples = sorted(knots + [(a+b)/2 for a, b in zip(knots, knots[1:])])
    gap = [section(cyan, v)[0]-section(navy, v)[1] for v in samples]
    edges = {"navy_right": chord_metrics(edge_points(navy, 1)),
             "cyan_left": chord_metrics(edge_points(cyan, 0)),
             "cyan_right": chord_metrics(edge_points(cyan, 1)),
             "navy_left": chord_metrics(edge_points(navy, 0))}
    maximum = float(max(abs(x) for x in gap))
    extent_disagreement = max(abs(float(navy[:, 1].min()-cyan[:, 1].min())),
                              abs(float(navy[:, 1].max()-cyan[:, 1].max())))
    straight = all(e["max_chord_residual_uv"] <= UV_TOLERANCE for e in edges.values())
    return {"pass": bool(maximum <= UV_TOLERANCE and straight and extent_disagreement <= UV_TOLERANCE and not any(ambiguous.values())), "tolerance_uv": UV_TOLERANCE,
            "multiple_interval_slices": ambiguous,
            "v_extent_disagreement_uv": extent_disagreement,
            "common_v_extent": [lo, hi], "max_boundary_disagreement_uv": maximum,
            "max_positive_gap_uv": max(0., max(gap)), "max_overlap_uv": max(0., -min(gap)),
            "gap_at_vertices_and_midpoints": [[v, g] for v, g in zip(samples, gap)], "edges": edges,
            "scope": "front outer-boundary envelopes only; holes, occlusion and mesh material ownership are separate"}


def homography(corners):
    matrix, rhs = [], []
    for (u, v), (x, y) in zip([[0, 0], [1, 0], [1, 1], [0, 1]], corners):
        matrix.extend([[u, v, 1, 0, 0, 0, -u*x, -v*x], [0, 0, 0, u, v, 1, -u*y, -v*y]])
        rhs.extend([x, y])
    return np.r_[np.linalg.solve(matrix, rhs), 1].reshape(3, 3)


def project(h, points):
    p = np.c_[points, np.ones(len(points))] @ h.T
    return p[:, :2] / p[:, 2:]


def sample_rgb(array, points):
    x, y = points[:, 0], points[:, 1]
    if np.any(x < 0) or np.any(y < 0) or np.any(x >= array.shape[1]-1) or np.any(y >= array.shape[0]-1):
        raise ValueError("sampling outside image")
    xi, yi = x.astype(int), y.astype(int)
    dx, dy = (x-xi)[:, None], (y-yi)[:, None]
    return (array[yi, xi]*(1-dx)*(1-dy)+array[yi, xi+1]*dx*(1-dy)
            +array[yi+1, xi]*(1-dx)*dy+array[yi+1, xi+1]*dx*dy)


def locate_edge(offsets, rgb):
    """Local two-colour midpoint; multiple crossings/light spikes => unknown."""
    left = np.median(rgb[offsets <= -8], axis=0)
    right = np.median(rgb[offsets >= 8], axis=0)
    delta = right-left
    contrast = float(np.linalg.norm(delta))
    if contrast < 15:
        return {"status": "unknown", "reason": "insufficient local colour contrast", "contrast_rgb": contrast}
    fraction = (rgb-left) @ delta / (delta @ delta)
    crossings = np.flatnonzero((fraction[:-1] < .5) & (fraction[1:] >= .5))
    if len(crossings) != 1 or float(fraction.min()) < -.3 or float(fraction.max()) > 1.3:
        return {"status": "unknown", "reason": "ambiguous colour profile; possible light, texture or multiple boundaries",
                "crossings": len(crossings), "contrast_rgb": contrast}
    i = int(crossings[0])
    offset = float(offsets[i]+(.5-fraction[i])*(offsets[i+1]-offsets[i])/(fraction[i+1]-fraction[i]))
    return {"status": "measured", "offset_px": offset, "contrast_rgb": contrast}


def freeze_roi(spec_path, png_path, view_path, output):
    if Path(output).exists():
        raise ValueError("frozen ROI already exists; never overwrite it for a candidate")
    view = read_json(view_path)
    h = homography(view["front_face_px"])
    # Chosen from baseline: the entire long stripe plus 20px lateral margin;
    # planar v=.03..97, top/bottom caps kept as separate diagnostic regions.
    regions = {"plane": [.03, .97], "top_bevel": [0, .03], "bottom_bevel": [.97, 1]}
    rois = {}
    for name, (lo, hi) in regions.items():
        quad = project(h, [[.16, lo], [.30, lo], [.30, hi], [.16, hi]])
        box = [int(np.floor(quad[:, 0].min()-20)), int(np.floor(quad[:, 1].min()-20)),
               int(np.ceil(quad[:, 0].max()+20)), int(np.ceil(quad[:, 1].max()+20))]
        rois[name] = {"v_extent": [lo, hi], "bbox_px": box, "quad_px": quad.tolist()}
    for name, bounds in {"navy_left": [0, .0, .045, 1], "top_left_corner": [0, 0, .30, .07]}.items():
        a, b, c, d = bounds
        quad = project(h, [[a, b], [c, b], [c, d], [a, d]])
        rois[name] = {"bbox_px": [int(quad[:, 0].min()-12), int(quad[:, 1].min()-12),
                                              int(quad[:, 0].max()+12), int(quad[:, 1].max()+12)], "quad_px": quad.tolist()}
    frozen = {"diagnostic_only": True, "baseline_sha256": {str(p): digest(p) for p in [spec_path, png_path, view_path]},
              "resolution": view["resolution"], "front_face_px": view["front_face_px"], "rois": rois,
              "pixel_rule": {"p95_max_px": 1, "max_px": 2, "profile_half_width_px": 12, "sample_step_px": .25},
              "definition": "ROI fixed from baseline before candidate; caps and navy-left bevel excluded from planar threshold"}
    write_json(output, frozen)
    return frozen


def evaluate(spec_path, png_path, view_path, roi_path, output_dir):
    spec, view, frozen = read_json(spec_path), read_json(view_path), read_json(roi_path)
    image = Image.open(png_path).convert("RGB")
    if list(image.size) != [2048, 2048] or view["resolution"] != [2048, 2048]:
        raise ValueError("acceptance PNG and projection must both be 2048x2048")
    if not np.allclose(view["front_face_px"], frozen["front_face_px"], atol=1e-6, rtol=0):
        raise ValueError("camera/shape projection changed relative to frozen ROI")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    geom = geometry_metrics(spec)
    h, rgb = homography(view["front_face_px"]), np.asarray(image, dtype=float)
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    pixel = {}
    offsets = np.arange(-12, 12.01, .25)
    for name in ["navy_right", "cyan_left", "cyan_right"]:
        ends = np.asarray(geom["edges"][name]["chord_uv"])
        lo, hi = frozen["rois"]["plane"]["v_extent"]
        vs = np.linspace(lo, hi, 800)
        us = ends[0, 0]+(ends[1, 0]-ends[0, 0])*(vs-ends[0, 1])/(ends[1, 1]-ends[0, 1])
        centres = project(h, np.c_[us, vs])
        direction = centres[-1]-centres[0]
        normal = np.array([direction[1], -direction[0]])/np.linalg.norm(direction)
        observations, invalid = [], []
        for centre, v in zip(centres, vs):
            points = centre+offsets[:, None]*normal
            box = frozen["rois"]["plane"]["bbox_px"]
            if np.any(points < box[:2]) or np.any(points > box[2:]):
                invalid.append({"v": float(v), "reason": "profile outside frozen ROI"})
                continue
            measured = locate_edge(offsets, sample_rgb(rgb, points))
            if measured["status"] != "measured":
                invalid.append({"v": float(v), **measured})
                continue
            p = centre+normal*measured["offset_px"]
            observations.append({"v": float(v), "xy_px": p.tolist(), **measured})
            draw.ellipse([p[0]-1, p[1]-1, p[0]+1, p[1]+1], fill=(255, 0, 255))
        draw.line([tuple(centres[0]), tuple(centres[-1])], fill=(255, 255, 0), width=1)
        errors = np.abs([x["offset_px"] for x in observations])
        p95 = float(np.percentile(errors, 95)) if len(errors) else None
        maximum = float(max(errors)) if len(errors) else None
        status = "unknown" if invalid else ("pass" if p95 <= 1 and maximum <= 2 else "fail")
        pixel[name] = {"status": status, "p95_px": p95, "max_px": maximum, "valid_samples": len(observations),
                       "invalid_samples": len(invalid), "invalid": invalid, "observations": observations}
    for name, roi in frozen["rois"].items():
        box = roi["bbox_px"]
        image.crop(box).save(out / f"{name}.png")
        draw.rectangle(box, outline=(255, 100, 0), width=2)
    annotated.save(out / "annotated.png")
    for name, roi in frozen["rois"].items():
        annotated.crop(roi["bbox_px"]).save(out / f"{name}.annotated.png")
    report = {"geometry": geom, "png_plane": pixel,
              "overall_status": "fail" if not geom["pass"] or any(x["status"] == "fail" for x in pixel.values()) else "unknown",
              "input_sha256": {str(p): digest(p) for p in [spec_path, png_path, view_path, roi_path]},
              "bevels": {"status": "unknown", "reason": "separate fixed crops emitted; view sidecar has no top/bevel mesh projection"},
              "substrate_ownership": {"status": "unknown", "reason": "beauty RGB cannot separate highlight from exposed substrate; spec envelope gap is separate evidence"},
              "projection_limit": "homography uses actual scene carton corners, but not normal-offset printed spline vertices",
              "measurement": "absolute distance to projected final-spec endpoint chord; no image-line refit; invalid samples prohibit PASS"}
    write_json(out / "metrics.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze-roi", "measure"])
    for name in ["spec", "png", "view", "roi"]:
        parser.add_argument("--"+name, required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.action == "freeze-roi":
        freeze_roi(args.spec, args.png, args.view, args.roi)
        return 0
    if args.out is None:
        parser.error("measure requires --out")
    result = evaluate(args.spec, args.png, args.view, args.roi, args.out)
    print(json.dumps({"geometry_pass": result["geometry"]["pass"], "overall_status": result["overall_status"],
                      "png_plane": {k: {q: v[q] for q in ["status", "p95_px", "max_px", "invalid_samples"]}
                                    for k, v in result["png_plane"].items()}}, indent=2))
    return 1 if result["overall_status"] == "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
