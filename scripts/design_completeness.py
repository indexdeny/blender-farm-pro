"""Fail when a connected chromatic reference region is absent from a design raster."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.mark_geometry import drawable_mark_parts


MIN_AREA_FRAC = 0.001
MIN_AXIS_SPAN = 0.015
CHROMA_DELTA_MIN = 0.08
EXCLUDED_CLASSES = frozenset({"object", "type", "unrepresentable", "mark", "blend"})


@dataclass(frozen=True)
class ResidualRegion:
    area_frac: float
    bbox_uv: tuple[float, float, float, float]
    median_rgb: tuple[int, int, int]
    chroma_delta: float


def _rgb01(image: np.ndarray) -> np.ndarray:
    rgb = np.asarray(image, dtype=float)
    if rgb.ndim != 3 or rgb.shape[-1] != 3:
        raise ValueError("image must be HxWx3")
    if rgb.max(initial=0.0) > 1.0:
        rgb = rgb / 255.0
    if rgb.min(initial=0.0) < 0.0 or rgb.max(initial=0.0) > 1.0:
        raise ValueError("RGB values must be in [0,1] or [0,255]")
    return rgb


def _components8(mask: np.ndarray) -> list[np.ndarray]:
    """Label 8-connected run components without producer dependencies."""
    height, width = mask.shape
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    rows: list[list[tuple[int, int, int]]] = []
    next_id = 0
    for y in range(height):
        edges = np.flatnonzero(np.diff(np.r_[False, mask[y], False]))
        runs = []
        for x0, x1 in zip(edges[::2], edges[1::2]):
            parent[next_id] = next_id
            runs.append((int(x0), int(x1), next_id))
            next_id += 1
        if y:
            for x0, x1, node in runs:
                for previous_x0, previous_x1, previous in rows[-1]:
                    if previous_x0 <= x1 and x0 <= previous_x1:
                        union(node, previous)
        rows.append(runs)

    groups: dict[int, np.ndarray] = {}
    for y, runs in enumerate(rows):
        for x0, x1, node in runs:
            root = find(node)
            component = groups.setdefault(root, np.zeros((height, width), dtype=bool))
            component[y, x0:x1] = True
    return list(groups.values())


def design_exclusion_mask(truth: dict, design: dict,
                          width: int, height: int) -> np.ndarray:
    """Rasterize explicit owner/type exclusions without producer masks."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    excluded = np.zeros((height, width), dtype=bool)

    def add_box(u0: float, v0: float, u1: float, v1: float) -> None:
        values = tuple(float(value) for value in (u0, v0, u1, v1))
        if any(value < 0.0 or value > 1.0 for value in values):
            raise ValueError(f"bbox outside [0,1]: {values}")
        x0 = max(0, int(np.floor(values[0] * width)))
        y0 = max(0, int(np.floor(values[1] * height)))
        x1 = min(width, int(np.ceil(values[2] * width)))
        y1 = min(height, int(np.ceil(values[3] * height)))
        if x1 > x0 and y1 > y0:
            excluded[y0:y1, x0:x1] = True

    for component in truth.get("components") or []:
        if component.get("vanished") or component.get("class") not in EXCLUDED_CLASSES:
            continue
        bbox = component.get("bbox_uv") or []
        if len(bbox) != 4:
            raise ValueError(f"{component.get('key')}: excluded component has no bbox_uv")
        add_box(bbox[0], bbox[1], bbox[2], bbox[3])

    for role, row in (design.get("type_rows") or {}).items():
        try:
            add_box(row["u0"], row["v0"], row["u1"], row["v1"])
        except KeyError as exc:
            raise ValueError(f"type row {role!r} has no {exc.args[0]}") from exc
    return excluded


def unexplained_regions(reference_rgb: np.ndarray, spec_rgb: np.ndarray,
                        excluded_mask: np.ndarray | None = None) -> list[ResidualRegion]:
    """Return sizeable chromatic residuals without consulting producer labels."""
    reference = _rgb01(reference_rgb)
    spec = _rgb01(spec_rgb)
    if reference.shape != spec.shape:
        raise ValueError("reference_rgb and spec_rgb must have the same shape")

    reference_chroma = reference - reference.mean(axis=-1, keepdims=True)
    spec_chroma = spec - spec.mean(axis=-1, keepdims=True)
    delta = np.linalg.norm(reference_chroma - spec_chroma, axis=-1)
    candidate = delta >= CHROMA_DELTA_MIN
    if excluded_mask is not None:
        excluded = np.asarray(excluded_mask, dtype=bool)
        if excluded.shape != candidate.shape:
            raise ValueError("excluded_mask must match the image dimensions")
        candidate &= ~excluded

    height, width = candidate.shape
    total = float(height * width)
    residuals = []
    for component in _components8(candidate):
        area = int(component.sum())
        if area / total < MIN_AREA_FRAC:
            continue
        ys, xs = np.nonzero(component)
        u_span = (int(xs.max()) - int(xs.min()) + 1) / width
        v_span = (int(ys.max()) - int(ys.min()) + 1) / height
        if max(u_span, v_span) < MIN_AXIS_SPAN:
            continue
        median = np.median(reference[component], axis=0)
        residuals.append(ResidualRegion(
            area_frac=area / total,
            bbox_uv=(float(xs.min()) / width, float(ys.min()) / height,
                     float(xs.max() + 1) / width, float(ys.max() + 1) / height),
            median_rgb=tuple(int(round(channel * 255)) for channel in median),
            chroma_delta=float(np.median(delta[component])),
        ))

    residuals.sort(key=lambda region: (-region.area_frac, region.bbox_uv))
    return residuals


def check_design(reference_rgb: np.ndarray, design: dict,
                 truth: dict) -> list[ResidualRegion]:
    """Rasterize a design and return independently detected residual regions."""
    reference = np.asarray(reference_rgb)
    if reference.ndim != 3 or reference.shape[-1] != 3:
        raise ValueError("reference_rgb must be HxWx3")
    height, width = reference.shape[:2]
    # Lazy import prevents a module cycle when fit_design_spec invokes the gate
    # after producing its candidate. Only the canonical rasterizer is shared;
    # no producer segmentation or component labels enter this module.
    from scripts.fit_design_spec import part_region, rasterise

    raster = np.asarray(rasterise(design, width, height).convert("RGB"))
    excluded = design_exclusion_mask(truth, design, width, height)
    declared = np.zeros((height, width), dtype=bool)
    for field in design.get("fields") or []:
        if field.get("surface", "front") != "front":
            continue
        for part in field.get("parts") or []:
            region = part_region(part, width, height)
            if region is not None:
                declared |= np.asarray(region, dtype=bool)
    for mark in design.get("marks") or []:
        for part in drawable_mark_parts(mark):
            region = part_region(part, width, height)
            if region is not None:
                declared |= np.asarray(region, dtype=bool)
    # Completeness asks whether geometry is absent. Colour disagreement inside
    # declared geometry belongs to design_qa and must not become a second colour
    # threshold here.
    excluded |= declared
    return unexplained_regions(reference, raster, excluded)


def main_for_sku(stem: str, spec_override: dict | None = None) -> int:
    """Run the independent gate for one canonical reference SKU."""
    from src.design_group import FOLDER_BY_STEM, TEMPLATES_DIR, load_design
    from scripts.measure_reference_face import rectified_face

    folder_name = FOLDER_BY_STEM.get(stem)
    if folder_name is None:
        print(json.dumps({
            "sku": stem, "complete": False,
            "error": "not in the reference design group",
        }))
        return 2
    folder = TEMPLATES_DIR / folder_name
    truth_path = folder / "print_truth.json"
    if not truth_path.exists():
        print(json.dumps({
            "sku": stem, "complete": False,
            "error": "print_truth.json absent",
        }))
        return 2

    flat, source, _corners = rectified_face(folder)
    design = spec_override if spec_override is not None else load_design(stem)
    if design is None:
        print(json.dumps({
            "sku": stem, "complete": False,
            "error": "design_spec.json absent",
        }))
        return 2
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    residuals = check_design(np.asarray(flat.convert("RGB")), design, truth)
    print(json.dumps({
        "sku": stem,
        "source_image": source,
        "complete": not residuals,
        "residuals": [asdict(region) for region in residuals],
    }, ensure_ascii=False, sort_keys=True))
    return 1 if residuals else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sku", required=True,
                        help="one canonical reference SKU stem, for example 74-min")
    args = parser.parse_args()
    return main_for_sku(args.sku)


if __name__ == "__main__":
    raise SystemExit(main())
