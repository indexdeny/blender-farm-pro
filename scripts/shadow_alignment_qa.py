"""Independent measurements for carton contact shadow and straight artwork.

This module owns derived QA only.  It does not build manifests, segment source
photography, or import Blender.  Inputs are explicit outlines/images/masks, so
the same ruler can reject a stale spec before a render and verify the projected
result after one.
"""
import argparse
from collections import deque
from dataclasses import asdict, dataclass
import hashlib
import json
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


BATCH_ARTIFACT_SUFFIXES = (
    ".png", ".scene.json", ".object.png", ".shadow.png",
)


def numeric_reference_stems(folder_names) -> list[str]:
    """Return `-min` stems in numeric order from numeric reference folders."""
    numbers = []
    for name in folder_names:
        match = re.match(r"^(\d+)_", str(name))
        if match:
            numbers.append(int(match.group(1)))
    return [f"{number}-min" for number in sorted(numbers)]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json_atomic(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    temporary.replace(path)


def _completed_record_is_current(out_dir: Path, stem: str,
                                 driver_hash: str,
                                 manifest_hash: str) -> bool:
    measurement = Path(out_dir) / f"{stem}.measurements.json"
    if not measurement.is_file():
        return False
    try:
        record = json.loads(measurement.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if (record.get("status") != "complete"
            or record.get("stem") != stem
            or record.get("driver_sha256") != driver_hash
            or record.get("manifest_sha256") != manifest_hash):
        return False
    hashes = record.get("artifact_sha256") or {}
    for suffix in BATCH_ARTIFACT_SUFFIXES:
        path = Path(out_dir) / f"{stem}{suffix}"
        if not path.is_file() or hashes.get(suffix) != sha256_file(path):
            return False
    return True


def run_resumable_batch(stems, out_dir: Path, driver_hash: str,
                        manifest_hashes: dict[str, str], render_one) -> dict:
    """Run isolated per-SKU work and promote only complete artifact sets.

    `render_one(stem, staging_dir)` writes the four required artifacts into its
    private directory and returns the measurement body. Existing completed
    files are untouched until every replacement exists and its gates pass.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    partial_root = out_dir / ".partial"
    partial_root.mkdir(exist_ok=True)
    report = {
        "driver_sha256": driver_hash,
        "ordered_stems": list(stems),
        "completed": [],
        "skipped": [],
        "failed": [],
    }

    for stem in stems:
        manifest_hash = manifest_hashes[stem]
        if _completed_record_is_current(
                out_dir, stem, driver_hash, manifest_hash):
            report["skipped"].append(stem)
            _write_json_atomic(out_dir / "report.json", report)
            continue

        staging = partial_root / stem
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            record = dict(render_one(stem, staging))
            if not (record.get("gates") or {}).get("all_pass", False):
                raise RuntimeError("candidate did not pass every batch gate")
            hashes = {}
            for suffix in BATCH_ARTIFACT_SUFFIXES:
                path = staging / f"{stem}{suffix}"
                if not path.is_file():
                    raise RuntimeError(f"renderer omitted {path.name}")
                hashes[suffix] = sha256_file(path)
            record.update({
                "status": "complete",
                "stem": stem,
                "driver_sha256": driver_hash,
                "manifest_sha256": manifest_hash,
                "artifact_sha256": hashes,
            })
            measurement = staging / f"{stem}.measurements.json"
            _write_json_atomic(measurement, record)
            for suffix in BATCH_ARTIFACT_SUFFIXES:
                (staging / f"{stem}{suffix}").replace(
                    out_dir / f"{stem}{suffix}")
            measurement.replace(out_dir / measurement.name)
            report["completed"].append(stem)
        except Exception as exc:  # caller receives exact failed stem and cause
            report["failed"].append({"stem": stem, "error": str(exc)})
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        _write_json_atomic(out_dir / "report.json", report)

    report["counts"] = {
        "completed": len(report["completed"]),
        "skipped": len(report["skipped"]),
        "failed": len(report["failed"]),
    }
    _write_json_atomic(out_dir / "report.json", report)
    return report


@dataclass(frozen=True)
class LineFit:
    """Orthogonal least-squares line fit in a two-dimensional frame."""

    max_residual: float
    direction: tuple[float, float]
    origin: tuple[float, float]


def fit_line(points) -> LineFit:
    """Fit one 2D line and report its maximum orthogonal residual."""
    array = np.asarray(points, dtype=float)
    if array.ndim != 2 or array.shape[1] != 2 or len(array) < 2:
        raise ValueError("a line fit requires at least two 2D points")
    if not np.isfinite(array).all():
        raise ValueError("line-fit points must be finite")

    origin = array.mean(axis=0)
    _u, _s, vh = np.linalg.svd(array - origin, full_matrices=False)
    direction = vh[0]
    # Resolve the SVD sign ambiguity so serialized measurements are stable.
    dominant = int(np.argmax(np.abs(direction)))
    if direction[dominant] < 0.0:
        direction = -direction
    normal = np.array((-direction[1], direction[0]))
    residuals = np.abs((array - origin) @ normal)
    return LineFit(
        max_residual=float(residuals.max(initial=0.0)),
        direction=(float(direction[0]), float(direction[1])),
        origin=(float(origin[0]), float(origin[1])),
    )


def _cyclic_paths(length, start, end):
    forward = []
    index = start
    while True:
        forward.append(index)
        if index == end:
            break
        index = (index + 1) % length

    backward = []
    index = start
    while True:
        backward.append(index)
        if index == end:
            break
        index = (index - 1) % length
    return forward, backward


def _edge_path(points, start, end, side):
    paths = _cyclic_paths(len(points), start, end)
    key = lambda path: float(np.mean(points[path, 0]))
    return min(paths, key=key) if side == "left" else max(paths, key=key)


def _extreme_pair(points, axis, find_min):
    values = points[:, axis]
    extreme = float(values.min() if find_min else values.max())
    span = float(np.ptp(values))
    tolerance = max(1e-9, span * 1e-6)
    indices = np.flatnonzero(np.abs(values - extreme) <= tolerance)
    if len(indices) < 2:
        order = np.argsort(values if find_min else -values)
        indices = order[:2]
    ordered = sorted((int(i) for i in indices), key=lambda i: points[i, 0])
    return ordered[0], ordered[-1]


def band_metrics(outline) -> dict:
    """Measure the two long boundaries and endpoint width of a narrow band.

    The outline must be a cyclic polygon in surface UV.  Top and bottom pairs
    are derived from the polygon extrema; the left/right boundary paths are
    selected by their mean U rather than by vertex count or a SKU-specific
    role.  Perspective is deliberately absent here: this is an object-space
    ruler.
    """
    points = np.asarray(outline, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 4:
        raise ValueError("a band outline requires at least four 2D points")
    if not np.isfinite(points).all():
        raise ValueError("band outline points must be finite")

    top_left, top_right = _extreme_pair(points, 1, True)
    bottom_left, bottom_right = _extreme_pair(points, 1, False)
    left_indices = _edge_path(points, top_left, bottom_left, "left")
    right_indices = _edge_path(points, top_right, bottom_right, "right")
    left_fit = fit_line(points[left_indices])
    right_fit = fit_line(points[right_indices])
    top_width = abs(float(points[top_right, 0] - points[top_left, 0]))
    bottom_width = abs(float(points[bottom_right, 0] - points[bottom_left, 0]))
    return {
        "left_max_residual": left_fit.max_residual,
        "right_max_residual": right_fit.max_residual,
        "top_width": top_width,
        "bottom_width": bottom_width,
        "width_drift": abs(top_width - bottom_width),
        "left_fit": asdict(left_fit),
        "right_fit": asdict(right_fit),
        "left_vertex_count": len(left_indices),
        "right_vertex_count": len(right_indices),
    }


def _luminance(rgb):
    array = np.asarray(rgb, dtype=float)
    if array.ndim != 3 or array.shape[2] < 3:
        raise ValueError("an RGB image must have shape HxWx3")
    return (0.2126 * array[:, :, 0]
            + 0.7152 * array[:, :, 1]
            + 0.0722 * array[:, :, 2])


def bbox_from_mask(mask):
    """Return an exclusive pixel bbox, independent of any nearby shadow."""
    array = np.asarray(mask, dtype=bool)
    if array.ndim != 2 or not array.any():
        raise ValueError("bbox requires a non-empty two-dimensional mask")
    ys, xs = np.nonzero(array)
    return (int(xs.min()), int(ys.min()),
            int(xs.max() + 1), int(ys.max() + 1))


def shadow_mask(on_rgb, off_rgb, object_mask, min_deficit=2.0):
    """Pixels darkened by the receiver, explicitly excluding the carton."""
    on = _luminance(on_rgb)
    off = _luminance(off_rgb)
    carton = np.asarray(object_mask, dtype=bool)
    if on.shape != off.shape or on.shape != carton.shape:
        raise ValueError("ON, OFF and object mask dimensions must match")
    # The first antialiased ring blends carton and receiver.  Calling that ring
    # "shadow" imports dark carton ink into the minimum-luminance metric (140 on
    # the real Viagra frame) even though the receiver itself never drops below
    # 233.  One-pixel exclusion retains contact at distance 2, within the gate,
    # and is independent of carton colour.
    excluded = _dilate_once(carton)
    return ((off - on) > float(min_deficit)) & ~excluded


def _dilate_once(mask):
    padded = np.pad(np.asarray(mask, dtype=bool), 1, mode="constant")
    return np.logical_or.reduce([
        padded[0:-2, 0:-2], padded[0:-2, 1:-1], padded[0:-2, 2:],
        padded[1:-1, 0:-2], padded[1:-1, 1:-1], padded[1:-1, 2:],
        padded[2:, 0:-2], padded[2:, 1:-1], padded[2:, 2:],
    ])


def _erode(mask, iterations=2):
    out = np.asarray(mask, dtype=bool).copy()
    for _ in range(iterations):
        out = ~_dilate_once(~out)
        out[[0, -1], :] = False
        out[:, [0, -1]] = False
    return out


def _contact_distance(object_mask, shadow, limit=8):
    if not shadow.any():
        return None
    grown = np.asarray(object_mask, dtype=bool)
    for distance in range(1, limit + 1):
        grown = _dilate_once(grown)
        if np.logical_and(grown, shadow).any():
            return distance
    return limit + 1


def _lower_edge_coverage(object_mask, shadow, depth=128):
    carton = np.asarray(object_mask, dtype=bool)
    xs = np.flatnonzero(carton.any(axis=0))
    if len(xs) == 0 or not shadow.any():
        return 0.0
    covered = 0
    height, width = carton.shape
    for x in xs:
        bottom = int(np.flatnonzero(carton[:, x])[-1])
        y0, y1 = bottom + 1, min(height, bottom + depth + 1)
        x0, x1 = max(0, x - 2), min(width, x + 3)
        if y0 < y1 and shadow[y0:y1, x0:x1].any():
            covered += 1
    return covered / len(xs)


def _falloff_crossing(values, level):
    for index in range(1, len(values)):
        before, after = float(values[index - 1]), float(values[index])
        if before > level >= after:
            if before == after:
                return float(index)
            return (index - 1) + (before - level) / (before - after)
    return None


def _penumbra_width(deficit, object_mask, depth=128):
    """Median 90%->10% falloff below the carton's projected lower edge."""
    carton = np.asarray(object_mask, dtype=bool)
    widths = []
    height = carton.shape[0]
    for x in np.flatnonzero(carton.any(axis=0)):
        bottom = int(np.flatnonzero(carton[:, x])[-1])
        # Skip the one-pixel antialias exclusion used by shadow_mask.
        profile = deficit[bottom + 2:min(height, bottom + depth + 2), x]
        if len(profile) < 3:
            continue
        peak_at = int(np.argmax(profile))
        tail = np.maximum(profile[peak_at:], 0.0)
        peak = float(tail[0])
        if peak <= 0.0:
            continue
        at_90 = _falloff_crossing(tail, 0.9 * peak)
        at_10 = _falloff_crossing(tail, 0.1 * peak)
        if at_90 is not None and at_10 is not None and at_10 >= at_90:
            widths.append(at_10 - at_90)
    return float(np.median(widths)) if widths else None


def shadow_metrics(on_rgb, off_rgb, object_mask, min_deficit=2.0):
    """Measure attached shadow separately from carton geometry.

    ON/OFF are matched renders.  The object mask is an independent render pass;
    it is never inferred by widening a luminance threshold to include shadow.
    """
    on_luma = _luminance(on_rgb)
    off_luma = _luminance(off_rgb)
    carton = np.asarray(object_mask, dtype=bool)
    shadow = shadow_mask(on_rgb, off_rgb, carton, min_deficit)
    area = int(shadow.sum())
    carton_area = int(carton.sum())
    deficit = off_luma - on_luma
    eroded = _erode(carton, 2)
    carton_delta = np.abs(deficit[eroded]) if eroded.any() else np.array([])

    patch = max(4, int(round(min(on_luma.shape) * 0.0625)))
    corners = [on_luma[:patch, :patch], on_luma[:patch, -patch:],
               on_luma[-patch:, :patch], on_luma[-patch:, -patch:]]
    corner_medians = [float(np.median(item)) for item in corners]
    return {
        "object_bbox_px": bbox_from_mask(carton),
        "object_area_px": carton_area,
        "shadow_area_px": area,
        "shadow_area_pct": (100.0 * area / carton_area
                            if carton_area else 0.0),
        "contact_distance_px": _contact_distance(carton, shadow),
        "mean_luminance_deficit": (float(deficit[shadow].mean())
                                   if area else 0.0),
        "minimum_shadow_luminance": (float(on_luma[shadow].min())
                                     if area else None),
        "penumbra_width_px": _penumbra_width(deficit, carton),
        "lower_edge_coverage": _lower_edge_coverage(carton, shadow),
        "corner_medians": corner_medians,
        "corner_median_spread": max(corner_medians) - min(corner_medians),
        "carton_mean_abs_delta": (float(carton_delta.mean())
                                  if len(carton_delta) else 0.0),
        "carton_p99_abs_delta": (float(np.percentile(carton_delta, 99))
                                  if len(carton_delta) else 0.0),
    }


def mask_component_metrics(mask) -> dict:
    """Measure 4-connected foreground without requiring SciPy or OpenCV."""
    foreground = np.asarray(mask, dtype=bool)
    remaining = set(map(tuple, np.argwhere(foreground)))
    sizes = []
    while remaining:
        seed = remaining.pop()
        queue = deque([seed])
        size = 1
        while queue:
            y, x = queue.popleft()
            for neighbour in ((y - 1, x), (y + 1, x),
                              (y, x - 1), (y, x + 1)):
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    queue.append(neighbour)
                    size += 1
        sizes.append(size)
    total = int(foreground.sum())
    largest = max(sizes, default=0)
    return {
        "component_count": len(sizes),
        "foreground_px": total,
        "largest_component_px": largest,
        "largest_component_fraction": largest / total if total else 0.0,
    }


def evaluate_candidate_gates(metrics: dict, object_mask,
                             saved_shadow_mask, candidate_seconds: float,
                             baseline_seconds: float) -> dict:
    """Apply the approved binary gates to one common-rig candidate."""
    carton = np.asarray(object_mask, dtype=bool)
    saved_shadow = np.asarray(saved_shadow_mask, dtype=bool)
    height, width = carton.shape
    x0, y0, x1, y1 = metrics["object_bbox_px"]
    components = mask_component_metrics(saved_shadow)
    delta = ((candidate_seconds / baseline_seconds) - 1.0
             if baseline_seconds > 0.0 else float("inf"))
    checks = {
        "contact_le_2px": metrics["contact_distance_px"] is not None
        and metrics["contact_distance_px"] <= 2,
        "shadow_area_1_to_20pct": 1.0 <= metrics["shadow_area_pct"] <= 20.0,
        "mean_deficit_3_to_20":
            3.0 <= metrics["mean_luminance_deficit"] <= 20.0,
        "minimum_luminance_ge_210":
            metrics["minimum_shadow_luminance"] is not None
            and metrics["minimum_shadow_luminance"] >= 210.0,
        "penumbra_6_to_82px": metrics["penumbra_width_px"] is not None
            and 6.0 <= metrics["penumbra_width_px"] <= 82.0,
        "lower_edge_coverage_ge_60pct":
            metrics["lower_edge_coverage"] >= 0.60,
        "corners_ge_250": min(metrics["corner_medians"]) >= 250.0,
        "corner_spread_le_2": metrics["corner_median_spread"] <= 2.0,
        "carton_mean_delta_le_1": metrics["carton_mean_abs_delta"] <= 1.0,
        "carton_p99_delta_le_3": metrics["carton_p99_abs_delta"] <= 3.0,
        "object_inside_frame": x0 > 0 and y0 > 0 and x1 < width and y1 < height,
        "masks_disjoint": not np.logical_and(carton, saved_shadow).any(),
        "shadow_main_component_ge_95pct":
            components["largest_component_fraction"] >= 0.95,
        "render_delta_le_25pct": delta <= 0.25,
    }
    return {
        "all_pass": all(checks.values()),
        "checks": checks,
        "render_time_delta": delta,
        "saved_shadow_components": components,
    }


def _run_checked(command: list[str], timeout: int) -> tuple[float, str]:
    started = time.perf_counter()
    process = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout)
    elapsed = time.perf_counter() - started
    output = process.stdout + process.stderr
    if process.returncode:
        raise RuntimeError(
            f"command failed with exit {process.returncode}: "
            f"{' '.join(command)}\n{output[-4000:]}")
    return elapsed, output


def _load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def _load_mask(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L")) > 1


def measure_candidate_artifacts(on_path: Path, off_path: Path,
                                object_path: Path, shadow_path: Path,
                                candidate_seconds: float,
                                baseline_seconds: float) -> dict:
    on = _load_rgb(on_path)
    off = _load_rgb(off_path)
    object_mask = _load_mask(object_path)
    saved_shadow = _load_mask(shadow_path)
    if (on.shape != off.shape
            or on.shape[:2] != object_mask.shape
            or object_mask.shape != saved_shadow.shape):
        raise RuntimeError("beauty, baseline and masks have different dimensions")
    metrics = shadow_metrics(on, off, object_mask)
    gates = evaluate_candidate_gates(
        metrics, object_mask, saved_shadow,
        candidate_seconds, baseline_seconds)
    return {
        "resolution": [int(on.shape[1]), int(on.shape[0])],
        "candidate_seconds": candidate_seconds,
        "baseline_seconds": baseline_seconds,
        "metrics": metrics,
        "gates": gates,
    }


def discover_reference_scope(template_root: Path,
                             project_root: Path) -> list[str]:
    """Return exactly the approved 28 design SKU plus generic 107-min."""
    from src.design_group import TEMPLATE_SAMPLE

    folders = sorted(
        (path.name for path in Path(template_root).iterdir()
         if path.is_dir() and re.match(r"^\d+_", path.name)),
        key=lambda name: int(name.split("_", 1)[0]))
    stems = numeric_reference_stems(folders)
    active = set(TEMPLATE_SAMPLE.values())
    if len(folders) != 29 or len(active) != 28 or set(stems) - active != {"107-min"}:
        raise RuntimeError(
            "reference batch boundary changed: expected 29 numeric folders, "
            "28 TEMPLATE_SAMPLE stems and only 107-min outside that sample")
    for stem in stems:
        passport = project_root / "04_passports/passports_json" / f"{stem}.json"
        manifest = project_root / "04_passports/render_manifests" / f"{stem}.json"
        if not passport.is_file() or not manifest.is_file():
            raise RuntimeError(f"{stem}: passport or canonical manifest is absent")
    return stems


def render_reference_candidate(stem: str, staging: Path, *,
                               project_root: Path, blender_exe: Path,
                               driver: Path, samples: int, resolution: int,
                               timeout: int) -> dict:
    """Render matched ON/OFF processes, dump the scene and measure one SKU."""
    manifest = project_root / "04_passports/render_manifests" / f"{stem}.json"
    on_path = staging / f"{stem}.png"
    off_path = staging / f"{stem}.shadow-off.png"
    scene_path = staging / f"{stem}.scene.json"
    object_path = staging / f"{stem}.object.png"
    shadow_path = staging / f"{stem}.shadow.png"
    common = [
        str(blender_exe), "--background", "--factory-startup",
        "--python", str(driver), "--", "--job", str(manifest),
        "--engine-type", "CYCLES", "--samples", str(samples),
        "--res-x", str(resolution), "--res-y", str(resolution),
        "--device", "CPU",
    ]
    on_command = common + [
        "--out", str(on_path), "--object-mask", str(object_path),
        "--shadow-mask", str(shadow_path),
    ]
    off_command = common + ["--out", str(off_path), "--shadow-off"]
    dump_command = common + ["--dump-scene", str(scene_path)]
    candidate_seconds, on_log = _run_checked(on_command, timeout)
    baseline_seconds, off_log = _run_checked(off_command, timeout)
    _dump_seconds, dump_log = _run_checked(dump_command, timeout)
    record = measure_candidate_artifacts(
        on_path, off_path, object_path, shadow_path,
        candidate_seconds, baseline_seconds)
    record.update({
        "engine": "CYCLES",
        "samples": samples,
        "device": "CPU",
        "commands": {
            "candidate": on_command,
            "baseline": off_command,
            "scene_dump": dump_command,
        },
        "log_tails": {
            "candidate": on_log[-1200:],
            "baseline": off_log[-1200:],
            "scene_dump": dump_log[-1200:],
        },
    })
    return record


def build_contact_sheet(out_dir: Path, stems, destination: Path) -> None:
    """Build a deterministic, labelled diagnostic sheet in numeric order."""
    tile = 300
    label_h = 28
    columns = 5
    rows = (len(stems) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile, rows * (tile + label_h)), "white")
    font_path = Path(__file__).resolve().parents[1] / "05_assets/blender/fonts/DejaVuSans.ttf"
    font = ImageFont.truetype(str(font_path), 18)
    draw = ImageDraw.Draw(sheet)
    for index, stem in enumerate(stems):
        image = Image.open(Path(out_dir) / f"{stem}.png").convert("RGB")
        image.thumbnail((tile, tile), Image.Resampling.LANCZOS)
        col, row = index % columns, index // columns
        x = col * tile + (tile - image.width) // 2
        y = row * (tile + label_h) + (tile - image.height) // 2
        sheet.paste(image, (x, y))
        draw.text((col * tile + 8, row * (tile + label_h) + tile + 3),
                  stem, fill="black", font=font)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)


def summarise_reference_batch(out_dir: Path, stems) -> dict:
    """Aggregate the exact artifact set and common-rig evidence."""
    out_dir = Path(out_dir)
    records = [json.loads(
        (out_dir / f"{stem}.measurements.json").read_text(encoding="utf-8"))
        for stem in stems]
    scenes = [json.loads(
        (out_dir / f"{stem}.scene.json").read_text(encoding="utf-8"))
        for stem in stems]
    suffixes = BATCH_ARTIFACT_SUFFIXES + (".measurements.json",)
    artifact_counts = {
        suffix: sum((out_dir / f"{stem}{suffix}").is_file()
                    for stem in stems)
        for suffix in suffixes
    }
    driver_hashes = sorted({record["driver_sha256"] for record in records})
    formula_keys = (
        "scope", "method", "receiver_scale", "receiver_offset_frac",
        "feather_start", "ao_distance_frac", "ao_samples",
        "shadow_floor_linear", "engine",
    )
    formulas = {
        tuple((key, scene["shadow_rig"].get(key)) for key in formula_keys)
        for scene in scenes
    }
    candidate_times = [float(record["candidate_seconds"])
                       for record in records]
    baseline_times = [float(record["baseline_seconds"])
                      for record in records]
    pair_deltas = [candidate / baseline - 1.0
                   for candidate, baseline in zip(candidate_times, baseline_times)]
    summary = {
        "record_count": len(records),
        "passed_record_count": sum(
            bool(record["gates"]["all_pass"]) for record in records),
        "artifact_counts": artifact_counts,
        "driver_fingerprint_count": len(driver_hashes),
        "driver_sha256": driver_hashes,
        "shadow_formula_count": len(formulas),
        "shadow_formulas": [dict(formula) for formula in sorted(formulas)],
        "candidate_median_seconds": statistics.median(candidate_times),
        "baseline_median_seconds": statistics.median(baseline_times),
        "median_render_time_delta": statistics.median(pair_deltas),
        "maximum_render_time_delta": max(pair_deltas),
    }
    expected = len(stems)
    summary["all_pass"] = (
        len(records) == expected
        and summary["passed_record_count"] == expected
        and all(count == expected for count in artifact_counts.values())
        and summary["driver_fingerprint_count"] == 1
        and summary["shadow_formula_count"] == 1
        and summary["median_render_time_delta"] <= 0.25
        and summary["maximum_render_time_delta"] <= 0.25
    )
    return summary


def build_comparison_sheet(before_path: Path, after_path: Path,
                           destination: Path, object_bbox) -> None:
    """Show unchanged source pixels in four measured crops and full frames."""
    before = Image.open(before_path).convert("RGB")
    after = Image.open(after_path).convert("RGB")
    x0, y0, x1, y1 = object_bbox
    width, height = x1 - x0, y1 - y0
    crops = [
        ("верхний левый сгиб", (x0, y0, x0 + int(.38 * width),
                                y0 + int(.34 * height))),
        ("зона Pfizer", (x0, y0 + int(.10 * height), x0 + int(.40 * width),
                         y0 + int(.48 * height))),
        ("голубая полоса", (x0 + int(.12 * width), y0,
                            x0 + int(.32 * width), y1)),
        ("контактная тень", (x0, y0 + int(.72 * height), x1,
                             min(after.height, y1 + int(.12 * height)))),
    ]
    font_path = Path(__file__).resolve().parents[1] / "05_assets/blender/fonts/DejaVuSans.ttf"
    title_font = ImageFont.truetype(str(font_path), 24)
    label_font = ImageFont.truetype(str(font_path), 18)
    sheet = Image.new("RGB", (1600, 1500), "white")
    draw = ImageDraw.Draw(sheet)
    for column, (label, image) in enumerate((("ДО", before), ("ПОСЛЕ", after))):
        full = image.copy()
        full.thumbnail((760, 700), Image.Resampling.LANCZOS)
        x = 20 + column * 790 + (760 - full.width) // 2
        sheet.paste(full, (x, 50))
        draw.text((20 + column * 790, 12), label, fill="black", font=title_font)
    crop_w, crop_h = 380, 315
    for index, (label, box) in enumerate(crops):
        col = index % 4
        for version, image in enumerate((before, after)):
            crop = image.crop(box)
            crop.thumbnail((crop_w, crop_h), Image.Resampling.LANCZOS)
            x = col * 400 + (crop_w - crop.width) // 2 + 10
            y = 790 + version * 340 + (crop_h - crop.height) // 2
            sheet.paste(crop, (x, y))
            draw.rectangle((col * 400 + 9, 789 + version * 340,
                            col * 400 + 391, 1106 + version * 340),
                           outline=(180, 180, 180), width=1)
        draw.text((col * 400 + 12, 760), label, fill="black", font=label_font)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)


def _batch_command(args) -> int:
    project_root = Path(__file__).resolve().parents[1]
    template_root = Path(args.root)
    if not template_root.is_absolute():
        template_root = project_root / template_root
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = project_root / out_dir
    stems = discover_reference_scope(template_root, project_root)

    from src.utils import load_config, resolve_path
    config = load_config()
    blender_exe = Path(config["blender"]["executable"])
    driver = resolve_path(config["blender"]["driver_script"])
    if not blender_exe.is_file() or not driver.is_file():
        raise RuntimeError("configured Blender executable or driver is absent")
    driver_hash = sha256_file(driver)
    manifests = {
        stem: sha256_file(project_root / "04_passports/render_manifests" /
                          f"{stem}.json")
        for stem in stems
    }

    def render_one(stem, staging):
        print(f"[shadow-batch] render {stem}", flush=True)
        return render_reference_candidate(
            stem, staging, project_root=project_root,
            blender_exe=blender_exe, driver=driver,
            samples=args.samples, resolution=args.resolution,
            timeout=args.timeout)

    report = run_resumable_batch(
        stems, out_dir, driver_hash, manifests, render_one)
    if not report["failed"]:
        report["aggregate"] = summarise_reference_batch(out_dir, stems)
        build_contact_sheet(out_dir, stems, out_dir / "contact-sheet.png")
        _write_json_atomic(out_dir / "report.json", report)
    print(json.dumps(report["counts"], ensure_ascii=False), flush=True)
    return 1 if report["failed"] or not report.get("aggregate", {}).get(
        "all_pass", False) else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    batch = subparsers.add_parser("batch")
    batch.add_argument("--root", required=True)
    batch.add_argument("--out", required=True)
    batch.add_argument("--samples", type=int, default=16)
    batch.add_argument("--resolution", type=int, default=2048)
    batch.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    if args.command == "batch":
        return _batch_command(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())
