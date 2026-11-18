"""Recover printed regions swallowed by the base substrate cluster."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


SATURATION_DELTA = 0.06
MIN_AREA_FRAC = 0.001
MIN_AXIS_SPAN = 0.015
MORPH_RADIUS_FRAC = 0.0035


@dataclass(frozen=True)
class RecoveredRegion:
    """One deterministic non-substrate region recovered from substrate pixels."""

    role: str
    mask: np.ndarray
    colour: np.ndarray

    def __post_init__(self):
        mask = np.asarray(self.mask, dtype=bool).copy()
        colour = np.asarray(self.colour, dtype=float).copy()
        mask.setflags(write=False)
        colour.setflags(write=False)
        object.__setattr__(self, "mask", mask)
        object.__setattr__(self, "colour", colour)


def _saturation(rgb: np.ndarray) -> np.ndarray:
    hi = rgb.max(axis=-1)
    lo = rgb.min(axis=-1)
    return np.where(hi > 0, (hi - lo) / np.maximum(hi, 1e-6), 0.0)


def _shift(mask: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """Translate without wraparound, keeping an out-of-frame pixel false."""
    out = np.zeros_like(mask)
    sy0, sy1 = max(0, -dy), mask.shape[0] - max(0, dy)
    sx0, sx1 = max(0, -dx), mask.shape[1] - max(0, dx)
    dy0, dy1 = max(0, dy), mask.shape[0] - max(0, -dy)
    dx0, dx1 = max(0, dx), mask.shape[1] - max(0, -dx)
    out[dy0:dy1, dx0:dx1] = mask[sy0:sy1, sx0:sx1]
    return out


def _dilate8(mask: np.ndarray, radius: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(radius):
        previous = out
        out = previous.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    out |= _shift(previous, dy, dx)
    return out


def _erode8(mask: np.ndarray, radius: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(radius):
        previous = out
        out = previous.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    shifted = _shift(previous, dy, dx)
                    # Closing must not erode genuine print merely because it
                    # reaches the rectified face edge.
                    if dy > 0:
                        shifted[:dy, :] = True
                    elif dy < 0:
                        shifted[dy:, :] = True
                    if dx > 0:
                        shifted[:, :dx] = True
                    elif dx < 0:
                        shifted[:, dx:] = True
                    out &= shifted
    return out


def _components8(mask: np.ndarray) -> list[np.ndarray]:
    """Return 8-connected components without a per-pixel Python flood fill."""
    h, w = mask.shape
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: int, right: int) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[max(left, right)] = min(left, right)

    rows: list[list[tuple[int, int, int]]] = []
    next_id = 0
    for y in range(h):
        edges = np.flatnonzero(np.diff(np.r_[False, mask[y], False]))
        runs = []
        for x0, x1 in zip(edges[::2], edges[1::2]):
            parent[next_id] = next_id
            runs.append((int(x0), int(x1), next_id))
            next_id += 1
        if y:
            for x0, x1, node in runs:
                for px0, px1, previous in rows[-1]:
                    if px0 <= x1 and x0 <= px1:
                        union(node, previous)
        rows.append(runs)

    components: dict[int, np.ndarray] = {}
    for y, runs in enumerate(rows):
        for x0, x1, node in runs:
            root = find(node)
            component = components.get(root)
            if component is None:
                component = components[root] = np.zeros((h, w), dtype=bool)
            component[y, x0:x1] = True
    return list(components.values())


def recover_substrate_regions(rgb: np.ndarray, substrate_mask: np.ndarray,
                              substrate_colour: np.ndarray,
                              same_surface_max: float) -> list[RecoveredRegion]:
    """Recover chromatic, connected print from pixels the base k=4 named board.

    The candidate test, morphology and component pass are restricted to
    ``substrate_mask``. A component must differ from both the substrate colour
    and its local outside boundary, so a neutral lighting gradient remains board.
    """
    rgb = np.asarray(rgb, dtype=float)
    substrate_mask = np.asarray(substrate_mask, dtype=bool)
    substrate_colour = np.asarray(substrate_colour, dtype=float)
    if rgb.ndim != 3 or rgb.shape[-1] != 3 or substrate_mask.shape != rgb.shape[:2]:
        raise ValueError("rgb must be HxWx3 and substrate_mask must match HxW")

    h, w = substrate_mask.shape
    distance = np.linalg.norm(rgb - substrate_colour, axis=-1)
    candidate = substrate_mask & (distance >= same_surface_max)
    radius = max(1, round(min(w, h) * MORPH_RADIUS_FRAC))
    # Opening, not closing. On 74_Viagra the light-blue band touches thin
    # highlights running over the dark panel at the top and bottom. Closing
    # joins those branches into a component spanning 34.8% of the face width;
    # opening removes the thin bridges and leaves the measured 7.4%-wide band.
    candidate = _dilate8(_erode8(candidate, radius), radius) & substrate_mask
    saturation = _saturation(rgb)
    kept: list[tuple[np.ndarray, np.ndarray, float, float]] = []

    for mask in _components8(candidate):
        area = int(mask.sum())
        if area / float(mask.size) < MIN_AREA_FRAC:
            continue
        ys, xs = np.nonzero(mask)
        if max((xs.max() - xs.min() + 1) / w,
               (ys.max() - ys.min() + 1) / h) < MIN_AXIS_SPAN:
            continue
        colour = np.median(rgb[mask], axis=0)
        if float(np.linalg.norm(colour - substrate_colour)) < same_surface_max:
            continue
        boundary = _dilate8(mask, 1) & substrate_mask & ~mask
        if not boundary.any():
            continue
        if abs(float(np.median(saturation[mask]))
               - float(np.median(saturation[boundary]))) < SATURATION_DELTA:
            continue
        kept.append((mask, colour, float(ys.mean()), float(xs.mean())))

    kept.sort(key=lambda item: (-int(item[0].sum()), item[2], item[3]))
    return [RecoveredRegion(f"recovered_{n:02d}", mask, colour)
            for n, (mask, colour, _v, _u) in enumerate(kept, start=1)]


def recovered_records(flat_rgb: np.ndarray, labels_2d: np.ndarray,
                      named: dict, same_surface_max: float) -> list[dict]:
    """Adapt recovered substrate regions to the producer's component stream."""
    rgb = np.asarray(flat_rgb, dtype=float)
    if rgb.ndim != 3 or rgb.shape[-1] != 3:
        raise ValueError("flat_rgb must be HxWx3")
    if rgb.max(initial=0.0) > 1.0:
        rgb = rgb / 255.0

    labels = np.asarray(labels_2d)
    if labels.shape != rgb.shape[:2]:
        raise ValueError("labels_2d must match flat_rgb")
    substrate = named.get("substrate")
    if not isinstance(substrate, dict) or "label" not in substrate or "colour" not in substrate:
        raise ValueError("named must carry substrate label and colour")
    colour = np.asarray(substrate["colour"], dtype=float)
    if colour.max(initial=0.0) > 1.0:
        colour = colour / 255.0

    recovered = recover_substrate_regions(
        rgb, labels == int(substrate["label"]), colour, same_surface_max)
    return [
        {
            "role": region.role,
            "fill": "#" + "".join(f"{int(round(c * 255)):02X}" for c in region.colour),
            "mask": region.mask,
            "colour": region.colour,
        }
        for region in recovered
    ]
