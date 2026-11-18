"""What colour IS a design part, when its own edge is a mixture of two paints?

    python scripts/measure_part_colour.py                 # the bench and the group
    python scripts/measure_part_colour.py --bench-only

WHY THIS EXISTS. `fit()` gives a field its cluster's colour, and 31 of the
group's 75 printed parts sit further from their own colour than
`SAME_SURFACE_MAX`. Painting each part its own colour was built, measured and
rolled back (`00_PROJECT_STATE/PART_FILL.md`): taking that colour as the MEDIAN
of the part's pixels works on large parts and fails on small ones, because a
part's boundary is an antialiased mixture of it and whatever is next to it, and
on a sliver the mixture is most of the part.

Eroding the mask first is this project's own idiom -- `ERODE_PX = 11` on a
calibration patch, 19 on the substrate, 3 inside a type block -- and every one of
those is applied to a LARGE region. None was ever asked to work on a part
covering 0.16% of a face. Measured: erosion takes `404_Ritalin`'s 0.42% part
from 0.182 to 0.059, leaves `60_Cialis_Professional`'s genuinely-different
`highlight#1` at 0.290, and moves `64_Kamagra`'s parts the WRONG way -- and
Kamagra is the one carton the whole change helped.

So the estimator has to exclude the rim by knowing what a rim IS, not by a
radius. This file holds the candidates and, more importantly, the bench that
decides between them: composites of a KNOWN colour against a KNOWN neighbour at
the sizes that actually occur, so accuracy is measured against the right answer
rather than against agreement with the cluster -- which is the thing already
shown to be wrong.

NOTHING HERE CHANGES WHAT IS PAINTED. No spec, manifest, render or
`print_truth.json` is written. The contract stays at 1.8.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.design_group import FOLDER_BY_STEM  # noqa: E402
from scripts.fit_design_spec import components, load_truth  # noqa: E402
from scripts.measure_reference_face import _hex, segment  # noqa: E402

TEMPLATES_DIR = PROJECT_ROOT / "Reference Templates"
OUT_PATH = PROJECT_ROOT / "00_PROJECT_STATE" / "part_colour.json"

#: The rectification's own ramp width, in pixels of the 1100-wide face. Not
#: chosen: `CLAUDE.md` records the glyph-rim exclusion saturating at r=2 and
#: going no further at r=3, "which is all it is -- the face is rectified to
#: 1100px from a 2048 render". The bench composites at that width.
RIM_PX = 2.0

#: Mean-shift kernel for `modal_peak`, and the reason it is below
#: `SAME_SURFACE_MAX = 0.08`: two paints closer than that are one surface by this
#: project's own reckoning, so a kernel wider than it would walk across the gap
#: the estimator exists to respect.
MODE_RADIUS = 0.06
MODE_ITERS = 40

#: How far off the segment between two paints a pixel may sit and still be
#: called a mixture of them. A rim pixel is a convex combination by construction;
#: this is the room left for sensor noise and JPEG.
MIX_TOL = 0.05
#: Only the strict interior of the segment is a mixture. A pixel at t=0 IS the
#: part and must never be rejected.
MIX_MARGIN = 0.12

FOLDERS = sorted(set(FOLDER_BY_STEM.values()), key=lambda n: int(n.split("_")[0]))


# ── the candidates ───────────────────────────────────────────────────────────
# Every one takes (mask, raw, neighbours) and returns one RGB in 0..1, so the
# bench can run them without knowing which is which. `neighbours` is the other
# paints present; estimators that do not need it ignore it.

def median_full(mask, raw, neighbours=()):
    """The baseline: the median of every pixel in the mask, rim included.

    What `fit()` would have done. Kept as a candidate because a bench that does
    not include the thing being replaced cannot show an improvement.
    """
    return np.median(raw[mask], axis=0)


def _erode(mask, r):
    """r-pixel erosion, 4-neighbour, in numpy so this file needs no new import."""
    out = mask.copy()
    for _ in range(int(r)):
        e = out.copy()
        e[1:, :] &= out[:-1, :]
        e[:-1, :] &= out[1:, :]
        e[:, 1:] &= out[:, :-1]
        e[:, :-1] &= out[:, 1:]
        out = e
    return out


def _thickness(mask):
    """2*area/perimeter -- the part's own width, the figure `fit()` already uses.

    `_simplify_to_a_region`'s comment reaches for the same quantity when it needs
    to know how thick a part is. A disc of radius r returns r; a strip of width w
    returns w/2.
    """
    area = float(mask.sum())
    if area <= 0:
        return 0.0
    edge = mask & ~_erode(mask, 1)
    per = float(edge.sum())
    return (2.0 * area / per) if per else 0.0


def median_eroded_adaptive(mask, raw, neighbours=()):
    """Erode by a share of the part's OWN thickness, then take the median.

    The scale-aware version of the idiom that failed. A fixed radius cannot serve
    a 39% field and a 0.16% sliver; this asks each part how thick it is and takes
    the same FRACTION off every one. Backs off rather than emptying the mask,
    because an estimator that returns nothing is worse than one that returns the
    baseline.
    """
    r = max(1, int(round(0.35 * _thickness(mask))))
    while r >= 1:
        core = _erode(mask, r)
        if core.sum() >= 16:
            return np.median(raw[core], axis=0)
        r -= 1
    return median_full(mask, raw)


def modal_peak(mask, raw, neighbours=()):
    """Mean-shift from the median: the densest colour, not the middle one.

    Scale-free by construction. A rim spreads its pixels ALONG the segment
    between two paints, thinly; the interior piles them at one colour. The median
    is dragged by however many rim pixels there are, a mode is not -- it only
    needs the interior to be the densest single place, which holds whether the
    part is 39% of the face or 0.16% of it.

    Flat kernel and a fixed start, so it is deterministic: no seeding, no
    randomness, same answer every run.
    """
    px = raw[mask]
    if len(px) == 0:
        return np.zeros(3)
    c = np.median(px, axis=0)
    for _ in range(MODE_ITERS):
        near = px[np.linalg.norm(px - c, axis=1) <= MODE_RADIUS]
        if len(near) == 0:
            return c
        nxt = near.mean(axis=0)
        if float(np.linalg.norm(nxt - c)) < 1e-4:
            return nxt
        c = nxt
    return c


def unmixed(mask, raw, neighbours=()):
    """Reject the pixels that ARE mixtures, then take the median of the rest.

    The one that knows where the rim is by what a rim is rather than by where it
    sits. A boundary pixel is a convex combination of this part's paint and a
    neighbour's, so it lies ON the segment between them -- which is the same
    geometry `palette_on_line` already reports for whole palette entries, applied
    per pixel.

    A provisional colour is needed to define the segment, and the median serves:
    it is wrong in the direction of the neighbour, which only makes the segment
    it defines shorter, never wrong in kind. Pixels near the segment's ENDS are
    kept -- t=0 is the part itself.
    """
    px = raw[mask]
    if len(px) == 0:
        return np.zeros(3)
    c0 = np.median(px, axis=0)
    keep = np.ones(len(px), bool)
    for n in neighbours:
        d = np.asarray(n, dtype=float) - c0
        L2 = float(d @ d)
        if L2 < 1e-9:
            continue
        t = ((px - c0) @ d) / L2
        proj = c0 + t[:, None] * d
        off = np.linalg.norm(px - proj, axis=1)
        keep &= ~((off <= MIX_TOL) & (t > MIX_MARGIN) & (t < 1.0 + MIX_MARGIN))
    if keep.sum() < 16:
        return c0
    return np.median(px[keep], axis=0)


CANDIDATES = {
    "median_full": median_full,
    "median_eroded_adaptive": median_eroded_adaptive,
    "modal_peak": modal_peak,
    "unmixed": unmixed,
}


# ── the bench ────────────────────────────────────────────────────────────────

def _shape(kind, size=400):
    """A boolean shape at one of the sizes that actually occur in the group."""
    m = np.zeros((size, size), bool)
    if kind == "field":            # ~39% of the canvas, like 404_Ritalin's
        m[20:270, 20:270] = True
    elif kind == "strip":          # a thin rule, the case a constant erosion eats
        m[180:186, 40:360] = True
    elif kind == "blob":           # ~0.16%, like 60_Cialis_Professional's
        yy, xx = np.mgrid[0:size, 0:size]
        m[(yy - 200) ** 2 + (xx - 200) ** 2 <= 9 ** 2] = True
    else:
        raise ValueError(kind)
    return m


def bench_case(kind, part_rgb, neigh_rgb, size=400):
    """Composite a known part on a known neighbour, blur the seam, re-cluster.

    Faithful to what the pipeline actually hands an estimator: the mask does not
    come from the truth, it comes from assigning each blurred pixel to the nearer
    paint -- which is what k-means does, and which is why the mask carries rim
    pixels on BOTH sides of the true boundary.
    """
    truth = _shape(kind, size)
    img = np.where(truth[..., None], np.asarray(part_rgb, float),
                   np.asarray(neigh_rgb, float))
    blurred = np.asarray(
        Image.fromarray((img * 255).round().clip(0, 255).astype("uint8"), "RGB")
        .filter(ImageFilter.GaussianBlur(radius=RIM_PX / 2.0)),
        dtype=float) / 255.0
    dp = np.linalg.norm(blurred - np.asarray(part_rgb, float), axis=-1)
    dn = np.linalg.norm(blurred - np.asarray(neigh_rgb, float), axis=-1)
    return (dp < dn), blurred


def run_bench():
    """Every candidate against every case, scored on distance to the KNOWN answer."""
    part = (0.18, 0.20, 0.21)      # a charcoal, like 152_Artvigil's S-curve
    cases = []
    for kind in ("field", "strip", "blob"):
        for label, neigh in (("lighter-far", (0.88, 0.33, 0.02)),   # orange
                             ("darker-far", (0.02, 0.18, 0.15)),    # dark teal
                             ("lighter-near", (0.26, 0.28, 0.29)),  # a near grey
                             ("darker-near", (0.11, 0.13, 0.14))):
            mask, raw = bench_case(kind, part, neigh)
            row = {"case": f"{kind}/{label}",
                   "mask_px": int(mask.sum()),
                   "mask_pct": round(100.0 * mask.sum() / mask.size, 3),
                   "truth": _hex(part), "neighbour": _hex(neigh), "by": {}}
            for name, fn in CANDIDATES.items():
                got = fn(mask, raw, [neigh])
                row["by"][name] = {
                    "hex": _hex(got),
                    "err": round(float(np.linalg.norm(got - np.asarray(part))), 4)}
            cases.append(row)
    return cases


# ── the group, for the do-no-harm check ──────────────────────────────────────

def run_group(folders=None):
    """Every printed part of the group, through every candidate.

    No truth here -- that is the point of the bench. What this gives is the
    do-no-harm check: the parts whose median already equals their cluster's
    colour to 0.000 are large and uncontaminated, and an estimator that moves
    them is wrong whatever the bench said.
    """
    out = []
    for name in (folders or FOLDERS):
        folder = TEMPLATES_DIR / name
        try:
            flat, labels, named, meta, source = segment(folder)
        except SystemExit:
            continue
        w, h = flat.width, flat.height
        lab = labels.reshape(h, w)
        raw = np.asarray(flat).astype(float) / 255.0
        truth = load_truth(folder)
        if truth is None:
            continue
        label_of = {c["key"]: c.get("class") for c in truth["components"]}
        min_region = int(float(truth["enumerate_min_frac"]) * w * h)
        roles = [(r, named[r]) for r in sorted(named)
                 if r != "substrate" and named.get(r) is not None]
        others = {r: [np.asarray(g["colour"], float)
                      for rr, g in roles if rr != r]
                  + [np.asarray(named["substrate"]["colour"], float)]
                  for r, _g in roles}
        for role, group in roles:
            cluster = np.asarray(group["colour"], float)
            for i, part in enumerate(components(lab == group["label"], min_region)):
                if label_of.get(f"{role}#{i}") != "print":
                    continue
                row = {"folder": name, "key": f"{role}#{i}",
                       "area_pct": round(100.0 * float(part.sum()) / (w * h), 3),
                       "cluster": _hex(cluster), "by": {}}
                for cname, fn in CANDIDATES.items():
                    got = fn(part, raw, others[role])
                    row["by"][cname] = {
                        "hex": _hex(got),
                        "from_cluster": round(
                            float(np.linalg.norm(got - cluster)), 4)}
                out.append(row)
        print(f"{name:<24}done", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bench-only", action="store_true")
    ap.add_argument("--folder", action="append")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    bench = run_bench()
    print(f"{'case':<24}{'px':>7}" + "".join(f"{n:>24}" for n in CANDIDATES))
    print("-" * (31 + 24 * len(CANDIDATES)))
    for r in bench:
        cells = []
        for n in CANDIDATES:
            cell = r["by"][n]["hex"] + " " + format(r["by"][n]["err"], ".4f")
            cells.append(format(cell, ">24"))
        print(format(r["case"], "<24") + format(r["mask_px"], ">7") + "".join(cells))
    print("\nmean error over the bench, by candidate:")
    for n in CANDIDATES:
        errs = [r["by"][n]["err"] for r in bench]
        print(f"  {n:<24}{sum(errs) / len(errs):.4f}   worst {max(errs):.4f}")

    group = [] if args.bench_only else run_group(args.folder)
    Path(args.out).write_text(json.dumps(
        {"schema": "part_colour/1", "rim_px": RIM_PX,
         "bench": bench, "group": group}, indent=2), encoding="utf-8")
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
