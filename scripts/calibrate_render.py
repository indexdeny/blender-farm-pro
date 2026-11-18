"""Measure how this rig turns paint into pixels, by photographing a chart.

    python scripts/calibrate_render.py                # every design SKU
    python scripts/calibrate_render.py --sku 64-min --keep

A nearest-colour classifier compares our render against PRINT colours, and the
comparison is wrong in a way a gain off the substrate cannot reach: the render
applies a per-channel AFFINE to the paint, and its lift is the larger term at
the dark end. Kamagra's two greens are `#00463B` and `#002F26`, 0.122 apart, and
both render with a red channel near 0.14 against a spec that says 0.000 -- a lit
surface does not return black. The shared displacement is bigger than the gap it
has to preserve, so the darker green lands nearer the lighter one's paint and
89% of the field is classified as the wrong one. It was the group's worst field
by a factor of five.

The curve could be fitted across the design group's own regions -- it works, and
holding each carton out in turn classifies all thirty region medians correctly
against one for nearest-paint. It is still the move this project reverted once:
a transform fitted to the regions being judged can absorb a real build error as
calibration, and then the instrument agrees with whatever the renderer did.

So it is MEASURED instead. Each carton renders a second time with its design
replaced by a chart of known patches -- same geometry, same rig, same exposure,
no design present -- and the curve is read off that. It is the grey card the
anchor already uses, extended to the whole range, and nothing about the carton's
own artwork enters it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.deskew import flatten_face  # noqa: E402
from src.design_group import FOLDER_BY_STEM  # noqa: E402
from src.utils import load_config, resolve_path  # noqa: E402

_CFG = load_config()
_BL = _CFG["blender"]
MANIFEST_DIR = resolve_path(_CFG["paths"]["passports_manifests"])
SCRATCH = PROJECT_ROOT / "02_processing" / "calibration"
OUT = PROJECT_ROOT / "00_PROJECT_STATE" / "render_calibration.json"

# The chart. The neutral steps ARE the curve; the six colours at two levels each
# are the check on it -- what a per-channel model cannot carry. Deliberately NOT
# drawn from the palettes being classified: a chart made of the answers is the
# circularity this exists to avoid.
#
# The transfer measured this way is per-channel and independent of the other
# channels, which is what makes one curve enough: `#400000` renders as
# (0.251, 0.133, 0.133) -- its red lands where the ramp puts 0.251 and its two
# empty channels land where the ramp puts 0.
#
# 0xFF is in the ramp because the curve must not be extrapolated at the top:
# Xanax Pfizer's substrate is `#F9F6F4`, above every other step, and a clamp
# there would predict it as a quarter-level darker than it renders.
STEPS = (0x00, 0x20, 0x40, 0x70, 0xA8, 0xE0, 0xFF)
PATCHES = ([(v, v, v) for v in STEPS]
           + [(v, 0, 0) for v in (0x40, 0xC0)]
           + [(0, v, 0) for v in (0x40, 0xC0)]
           + [(0, 0, v) for v in (0x40, 0xC0)]
           + [(v, v, 0) for v in (0x40, 0xC0)]
           + [(0, v, v) for v in (0x40, 0xC0)]
           + [(v, 0, v) for v in (0x40, 0xC0)])
COLS, MARGIN = 4, 0.04
# Read this far inside each patch. The patches are drawn as extruded curves like
# any design field, so their edges carry the same lit fringe a field's do.
ERODE_PX = 11


def _grid(n: int, cols: int = COLS):
    rows = (n + cols - 1) // cols
    w, h = (1 - 2 * MARGIN) / cols, (1 - 2 * MARGIN) / rows
    for i in range(n):
        u0 = MARGIN + (i % cols) * w
        v0 = MARGIN + (i // cols) * h
        # Inset so neighbouring patches never share an edge: two abutting fills
        # would put each one's fringe inside the other.
        du, dv = 0.12 * w, 0.12 * h
        yield [[u0 + du, v0 + dv], [u0 + w - du, v0 + dv],
               [u0 + w - du, v0 + h - dv], [u0 + du, v0 + h - dv]]


def chart_manifest(stem: str) -> tuple[dict, list]:
    job = json.loads((MANIFEST_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    design = job.get("design")
    if not design:
        raise SystemExit(f"{stem}: no design block; nothing to calibrate against")
    fills = [f"#{r:02X}{g:02X}{b:02X}" for r, g, b in PATCHES]
    # The chart is a design like any other and must speak the current contract:
    # `z` since 1.7 and `holes` since 1.8, both required and both refused by the
    # driver with SystemExit rather than defaulted. The patches never overlap, so
    # the order is free and the holes are empty -- but writing them is not
    # ceremony, it is the difference between a chart that renders and one that
    # stops the run. It stopped this one: the fields carried no `z` from 1.7
    # until here, and nothing said so because the chart is only built inside a
    # Blender render. `tests/test_calibrate_render.py` now validates the job
    # against the schema, which costs nothing and would have caught it.
    design["fields"] = [
        {"role": f"patch_{i}", "fill": fill, "coverage_pct": 1.0, "z": i,
         # Contract 1.9: the PART carries the colour and the driver paints that,
         # with no fallback to the field's. A chart is a design block like any
         # other, and it is the one the whole transfer curve is read off -- so it
         # states each patch's colour where the renderer now looks for it.
         # `mark_holes` since 1.10, for the same reason `holes` is required: a
         # part that does not say which of its holes are marks is a part whose
         # marks are unknown, and the pairing rule cannot be checked on it.
         "parts": [{"kind": "field", "area_pct": 1.0, "smoothness": 0.0,
                    "fill": fill, "outline": outline, "holes": [],
                    "mark_holes": []}]}
        for i, (fill, outline) in enumerate(zip(fills, _grid(len(PATCHES))))]
    # Contract 1.10. A chart reproduces nobody's trademark, so the honest value
    # is an explicit empty list rather than an absent key -- the driver refuses
    # the absent one, and rightly: it cannot tell "no marks approved" from "the
    # marks were never decided".
    design["marks"] = []
    # No type on the chart: a label crossing a patch is ink, not paint, and the
    # driver reverses it against whatever it lands on -- which here is a patch.
    design["type_rows"] = {}
    design["reference_aux_text"] = []
    for k in job.get("label_content", {}):
        job["label_content"][k] = ""
    return job, fills


def _hex_rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])


def measure(stem: str, keep: bool = False) -> dict:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    job, fills = chart_manifest(stem)
    job_path = SCRATCH / f"{stem}.chart.json"
    png = SCRATCH / f"{stem}.chart.png"
    job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")
    for stale in (png, png.with_suffix(".view.json")):
        if stale.exists():
            stale.unlink()
    proc = subprocess.run(
        [str(_BL["executable"]), "--background", "--factory-startup",
         "--python", str(resolve_path(_BL["driver_script"])), "--",
         "--job", str(job_path), "--out", str(png),
         "--engine-type", _BL.get("engine_type", "CYCLES"),
         "--samples", str(_BL.get("samples", 16)),
         "--res-x", str(_BL.get("resolution", [2048, 2048])[0]),
         "--res-y", str(_BL.get("resolution", [2048, 2048])[1])],
        capture_output=True, text=True, timeout=900)
    if not png.exists():
        raise SystemExit(f"{stem}: chart did not render\n{proc.stderr[-1500:]}")

    view = json.loads(png.with_suffix(".view.json").read_text(encoding="utf-8"))
    aspect = float(job["carton"]["height_mm"]) / float(job["carton"]["width_mm"])
    face = np.asarray(flatten_face(png, view["front_face_px"], out_width=1100,
                                   aspect=aspect).convert("RGB")).astype(float) / 255.0
    h, w = face.shape[:2]

    paint, seen = [], []
    for fill, outline in zip(fills, _grid(len(PATCHES))):
        mask = Image.new("L", (w, h), 0)
        from PIL import ImageDraw
        ImageDraw.Draw(mask).polygon([(u * w, v * h) for u, v in outline], fill=255)
        core = np.asarray(mask.filter(ImageFilter.MinFilter(ERODE_PX))) > 0
        if core.sum() < 200:
            continue
        paint.append(_hex_rgb(fill))
        seen.append(np.median(face[core], 0))
    if len(paint) < 6:
        raise SystemExit(f"{stem}: only {len(paint)} patches readable")

    # The ramp is the curve. Its rendered value is the mean of the three
    # channels, which on a neutral patch is three readings of the same point.
    ramp = sorted((float(p[0]), float(s.mean()))
                  for p, s in zip(paint, seen)
                  if p[0] == p[1] == p[2])
    if len(ramp) < 4:
        raise SystemExit(f"{stem}: {len(ramp)} neutral steps readable, need 4")
    xs = np.array([p for p, _ in ramp])
    ys = np.array([q for _, q in ramp])
    if np.any(np.diff(ys) <= 0):
        # Non-monotone means the chart was misread, not that the rig inverts:
        # interpolating through it would map two paints to one appearance.
        raise SystemExit(f"{stem}: ramp is not monotone: {ramp}")
    res = np.linalg.norm(seen - np.interp(paint, xs, ys), axis=1)
    colour = [r for r, p in zip(res, paint) if not p[0] == p[1] == p[2]]
    if not keep:
        for f in (job_path, png, png.with_suffix(".view.json")):
            if f.exists():
                f.unlink()
    return {"sku": stem, "patches": len(paint),
            "ramp": [[round(p, 4), round(q, 4)] for p, q in ramp],
            # What one curve per channel cannot carry: colour bleeding between
            # them off the board. Pure red reads 0.651 where red-and-green reads
            # 0.678 at the same paint level.
            "colour_residual_median": round(float(np.median(colour)), 4),
            "colour_residual_worst": round(float(max(colour)), 4)}


def driver_fingerprint() -> str:
    """What the calibration is only valid for.

    `render_fresh` refuses to compare against a stale PNG on the grounds that
    "which driver drew it" is not a detail. A calibration is a render too, and a
    stale one is worse than none: it would be applied silently to output a
    different driver produced. Covers the sampling settings as well, because
    they move the noise floor the patch medians are read through.
    """
    import hashlib
    h = hashlib.sha256(resolve_path(_BL["driver_script"]).read_bytes())
    h.update(repr([_BL.get("engine_type"), _BL.get("samples"),
                   _BL.get("resolution")]).encode())
    return h.hexdigest()[:16]


def load_curve(stem: str):
    """The measured transfer for one SKU, as (paint, appearance) knots.

    Fatal rather than falling back to an uncalibrated comparison: a classifier
    quietly running on the wrong model is exactly the failure this was built to
    remove, and it would show up as a plausible number.
    """
    if not OUT.exists():
        raise SystemExit(
            f"no {OUT.name}: run `python scripts/calibrate_render.py` first")
    data = json.loads(OUT.read_text(encoding="utf-8"))
    if data.get("driver") != driver_fingerprint():
        raise SystemExit(
            f"{OUT.name} was measured against a different driver or render "
            f"settings; re-run `python scripts/calibrate_render.py`")
    row = (data.get("rows") or {}).get(stem)
    if not row:
        raise SystemExit(f"{OUT.name} carries no calibration for {stem}")
    ramp = np.array(row["ramp"], dtype=float)
    return ramp[:, 0], ramp[:, 1]


def appearance(palette: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Each paint as this rig renders it.

    The classification is done in the RENDER's space, not the paint's: mapping
    the palette forward needs no inversion and cannot be mistaken for correcting
    the render, which is what would erase ColourError's answer.
    """
    return np.interp(palette, xs, ys)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sku", help="one SKU stem; default is every design SKU")
    p.add_argument("--keep", action="store_true",
                   help="leave the chart render on disk for inspection")
    args = p.parse_args()

    stems = [args.sku] if args.sku else sorted(
        FOLDER_BY_STEM, key=lambda s: int(s.split("-")[0]))
    rows = {}
    print(f"{'SKU':9s} {'n':>3s} {'black':>6s} {'white':>6s}   "
          f"{'colour resid':>12s} {'worst':>7s}")
    for stem in stems:
        r = measure(stem, args.keep)
        rows[stem] = r
        print(f"{stem:9s} {r['patches']:3d} {r['ramp'][0][1]:6.3f} "
              f"{r['ramp'][-1][1]:6.3f}   {r['colour_residual_median']:12.4f} "
              f"{r['colour_residual_worst']:7.4f}")

    if args.sku:
        # Same rule as design_qa: a probe does not rewrite the record, and
        # merging would leave rows from different revisions with nothing saying so.
        print(f"\n--sku is a probe; {OUT.name} is left alone.")
        return 0
    OUT.write_text(json.dumps({"driver": driver_fingerprint(), "rows": rows},
                              indent=2), encoding="utf-8")
    print(f"\n{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
