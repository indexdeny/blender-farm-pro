#!/usr/bin/env python
"""Does the colour the fitter DECLARED for a part match the pixels it covers?

Contract 1.9 -- a part carries its own fill -- was built, measured and rolled
back, and `00_PROJECT_STATE/PART_FILL.md` records that the figure it was judged
by could not conclude: `render~ref` classifies both sides against a palette made
of the very paints being changed, so its before and after were two instruments
rather than two renders.

`region_colour_gap` was added beside it to ask the same question without a
vocabulary, and it does take its regions from geometry. But it compares OUR
RENDER against the photograph in raw values, and measured on 2026-08-25 that
carries three terms of which only one is paint:

- the **exposure** difference between render and photograph. `230_Slimex`'s
  headline 0.3652 is 0.0187 of colour and the rest a neutral 1.29x; every
  substrate gap in the group above 0.26 is a level difference.
- the **rig's black lift**, a measured constant of 0.133-0.141. `64_Kamagra`'s
  0.128 chromatic residual is red at 0.131 against a spec that says 0.000.
- the **fit error**, which is the only part contract 1.9 can change.

Levelling it away does not work either, because a gain cannot represent a lift:
referred to its own substrate, `357-min`'s second field goes 0.0096 -> 0.4951.

So this takes the render out of the comparison altogether. A field's `fill` is
`np.median(raw_px[cluster])` off the rectified photograph
(`measure_reference_face.segment`), so the declared paint and the photograph are
the same measurement in the same space -- nothing to level, no curve, no lift,
and no render to take. What is left is exactly the quantity 1.9 changes: **the
fill is the CLUSTER's median while the region it paints is one PART.**

Two things this does that `measure_part_colour.py` does not, and they are why
both exist. That script benches ESTIMATORS against a known colour, to choose
one; this scores what SHIPS -- `part_region`, i.e. the traced outline minus its
holes, in paint order, so a part lying under a later one is measured on the
remainder that actually reaches the packshot.

**Its own floor is measured, and it is exactly zero.** The substrate's fill is
`np.median(raw_px[substrate_cluster])`, so measuring that same cluster back has
to return it, and on all 28 cartons it returns it to four decimals. There is no
resampling term either: every spec carries exactly the rectification's own
aspect, so this reads the photograph's own pixels. A gap is therefore the fit's,
with nothing of the instrument's in it.

Getting there took removing something. The first version compared against the
face with its illumination divided out, which put the plane's own error into the
headline: a part that IS its own cluster has to read zero, and `64-min`'s
`brand#0` -- 32.6% of the face -- read 0.0039 raw against 0.0950 levelled, and
`59-min`'s `highlight#0` 0.0068 against 0.2052. The plane is fitted over
"wherever the spec draws no field", which on those two cartons is the board plus
everything the labelling declined to represent. The levelled reading stays in
the report as `gap_levelled`, beside the headline and never in place of it, so
the illumination term is visible rather than assumed away.

    python scripts/measure_fit_colour.py            # the group, writes the report
    python scripts/measure_fit_colour.py --sku 157-min   # one carton, writes nothing
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.design_group import FOLDER_BY_STEM, TEMPLATES_DIR, load_design  # noqa: E402
from scripts.design_coverage import SUBSTRATE, spec_index  # noqa: E402
from scripts.fit_design_spec import part_region  # noqa: E402
from scripts.measure_reference_face import (  # noqa: E402
    SAME_SURFACE_MAX, _hex, rectified_face, segment,
)
# The illumination model has ONE implementation and it lives with the figure it
# was fitted for. A second copy is the defect this project has already paid for
# at `part_region`, `narrow_to_string` and `product_code`; importing the
# render-side module for one function is the cheaper of the two mistakes.
from scripts.design_qa import (  # noqa: E402
    _hex_rgb, _substrate_core, _substrate_residual, flatten_on_substrate,
)

REPORT = PROJECT_ROOT / "00_PROJECT_STATE" / "fit_colour.json"

#: Below this a median says more about the boundary than about the paint. The
#: same floor `design_qa.region_colour_gap` uses, for the same reason.
MIN_PART_PX = 50


def _required_fill(part: dict, field: dict, n: int, m: int) -> str:
    """Contract 1.9's fill, with no fallback to the field's.

    An earlier version of this read `part.get("fill", field["fill"])`, which is
    the silent substitution the contract exists to stop: a part with no colour
    would then have scored as a part that agrees with its field, and this
    instrument would have reported the very error it was built to find as
    absent.
    """
    if "fill" not in part:
        raise SystemExit(
            f"design field {field.get('role')!r} (index {n}) part {m} carries no "
            f"`fill`. That is contract 1.9 and it is required; re-run "
            f"scripts/fit_design_spec.py for this folder rather than reading it "
            f"as a part painted its field's colour.")
    return part["fill"]



def part_index(spec: dict, w: int, h: int):
    """Which PART the spec paints at each pixel, in paint order; -1 where none.

    `spec_index` collapses a field's parts into one index, because every figure
    built on it asks about fields. Contract 1.9 is a statement about PARTS, so
    they are kept apart here. Later parts overwrite earlier ones -- the order
    `rasterise()` fills in and the order `design.fields[].z` was added to make
    explicit -- so a part under a later one is measured on what remains visible,
    which is what reaches the carton.
    """
    idx = np.full((h, w), -1, dtype=int)
    entries = []
    for n, field in enumerate(spec.get("fields") or []):
        for m, part in enumerate(field.get("parts") or []):
            region = part_region(part, w, h)
            if region is None:
                continue
            idx[np.asarray(region)] = len(entries)
            entries.append({
                "field": n,
                "role": field.get("role"),
                "part": m,
                # Both, and that is the whole before-and-after in one report.
                # Under 1.8 -- and under 1.9's neutral Stage A -- they are equal
                # and the two columns agree. Once the producer is switched,
                # `gap` says whether the part's OWN declared colour is right
                # (it should go to nothing) while `gap_field` holds still and
                # keeps saying how wrong the field's colour was for this part.
                "fill": _required_fill(part, field, n, m),
                "field_fill": field["fill"],
                "kind": part.get("kind"),
                "area_pct": part.get("area_pct"),
            })
    return idx, entries


def score_part(raw: np.ndarray, flat: np.ndarray, sel: np.ndarray,
               entry: dict, size) -> dict:
    """One part scored: what was declared, what the photograph holds there.

    Split out of `measure` so the branch below can be tested without a folder,
    a photograph or a segmentation. It is the branch that matters: a part with
    nothing visible must report `None`, never 0.0 -- a figure that was never
    taken printing as a figure that came out zero is a failure this project has
    already shipped twice, once for `render_vs_reference` and once for
    `worst fld`.
    """
    px = int(sel.sum())
    row = dict(entry, px=px, visible_pct=round(100.0 * px / (size[0] * size[1]), 3))
    if px < MIN_PART_PX:
        # Wholly overpainted by a later part, or too small to median honestly.
        row.update(seen=None, gap=None, gap_field=None, gap_levelled=None,
                   spread=None)
        return row

    want = _hex_rgb(entry["fill"])
    vals = raw[sel]
    seen = np.median(vals, axis=0)
    # Whether the part is ONE colour at all. A fill is a claim that it is, and
    # where the spread is of the gap's own order the claim is empty however the
    # colour was estimated -- which separates "the fitter chose wrong", a thing
    # contract 1.9 can fix, from "there is no single right answer here", which
    # it cannot. `157-min`'s `type#1` is the case: gap 0.11, spread 0.24.
    spread = float(np.linalg.norm(np.median(np.abs(vals - seen), axis=0) * 1.4826))
    # The levelled reading, reported BESIDE the headline and never in place of
    # it, so the illumination term is measured rather than assumed away. It was
    # the headline first and lost the job on evidence: a part that IS its own
    # cluster has to read zero, and raw does while levelled does not --
    # `64-min`'s `brand#0` is 32.6% of the face at 0.0039 raw against 0.0950
    # levelled, `59-min`'s `highlight#0` 0.0068 against 0.2052. The plane is
    # fitted over "wherever the spec draws no field", which on those cartons is
    # the board plus everything the labelling declined to represent.
    lit = np.median(flat[sel], axis=0)
    row.update(seen=_hex(seen),
               gap=round(float(np.linalg.norm(want - seen)), 4),
               gap_field=round(float(np.linalg.norm(
                   _hex_rgb(entry["field_fill"]) - seen)), 4),
               gap_levelled=round(float(np.linalg.norm(want - lit)), 4),
               spread=round(spread, 4))
    return row


def _floor(folder: Path, spec: dict):
    """This construction's OWN error, on the one region whose answer is known.

    `spec["substrate"]` is `np.median(raw_px[substrate_cluster])`, taken by
    `segment()`, so measuring that same cluster back has to return it. Whatever
    is left over is this instrument's and not the carton's, and a field's gap is
    only worth reading against it.

    The first version took the median over `spec_index == SUBSTRATE`, which is
    "wherever the spec draws no field" -- the board PLUS every letterform,
    object and photograph the labelling declined to represent. That is not a
    floor, it is the same contamination the figure exists to avoid, and it read
    larger than the findings on several cartons.
    """
    flat_img, labels, named, _meta, _source = segment(folder)
    raw = np.asarray(flat_img.convert("RGB")).astype(float) / 255.0
    group = named.get("substrate")
    if group is None:
        return None, None
    # `segment` returns labels FLAT; every caller reshapes. Done here too rather
    # than reading around it, so the mask lines up with the image pixel for pixel.
    mask = np.isin(labels.reshape(flat_img.height, flat_img.width), group["labels"])
    if int(mask.sum()) < MIN_PART_PX:
        return None, None
    core = _substrate_core(np.where(mask, 0, 1))
    lit = flatten_on_substrate(raw, core if core.sum() >= 500 else mask)
    want = _hex_rgb(spec["substrate"])
    return (round(float(np.linalg.norm(want - np.median(lit[mask], axis=0))), 4),
            round(float(np.linalg.norm(want - np.median(raw[mask], axis=0))), 4))


def measure(stem: str) -> dict:
    spec = load_design(stem)
    folder = TEMPLATES_DIR / FOLDER_BY_STEM[stem]

    # The photograph, rectified. Not cached and deliberately so: `design_qa`
    # stopped reading `02_processing/reference_measurement/` because a rename
    # orphaned two previews and a midnight corner change left one six hours
    # stale, and both failures printed as figures rather than as errors.
    #
    # At the rectification's OWN size, and not resized to the spec's aspect the
    # way `design_qa` resizes it. There the resize exists to meet our render's
    # face; here there is no render, and resampling would put an unmeasured term
    # inside the headline. It changes nothing measurable either way -- every one
    # of the 28 specs carries exactly the rectification's own aspect, so the
    # resize was a no-op on all of them.
    ref = rectified_face(folder)[0]
    size = (ref.width, ref.height)
    raw = np.asarray(ref.convert("RGB")).astype(float) / 255.0

    geo = spec_index(spec, *size)
    # `_substrate_core` reads a CLASSIFIED map, where the substrate is palette 0;
    # `spec_index` marks it 255. Recoded rather than re-eroded, so the erosion
    # keeps its single owner.
    core = _substrate_core(np.where(geo == SUBSTRATE, 0, 1))

    # Flattened, so every region is read at the face's MEAN illumination -- which
    # is the illumination a median over a face-wide cluster already carries. The
    # fill itself is raw and needs no correction; what needs correcting is that a
    # small part sits at one place on the gradient and its cluster does not.
    flat = flatten_on_substrate(raw, core)

    floor, floor_raw = _floor(folder, spec)
    # NOT this figure's uncertainty, and named so it cannot be read as one: it
    # is the colour scatter inside everything the spec leaves as board, so it
    # rises with how much printed design the labelling wrote off rather than
    # with how well anything was measured. `346-min` and `230-min`, which draw
    # no field at all, sit at the top of it.
    scatter = round(_substrate_residual(flat, core), 4)

    pidx, entries = part_index(spec, *size)
    parts = [score_part(raw, flat, pidx == i, e, size) for i, e in enumerate(entries)]

    live = [p["gap"] for p in parts if p["gap"] is not None]
    return {
        "sku": stem,
        "folder": FOLDER_BY_STEM[stem],
        "substrate_floor": floor_raw,
        "substrate_floor_levelled": floor,
        "unpainted_scatter": scatter,
        "n_parts": len(parts),
        "n_measured": len(live),
        "worst": round(max(live), 4) if live else None,
        "mean": round(float(np.mean(live)), 4) if live else None,
        "over_threshold": sum(1 for g in live if g >= SAME_SURFACE_MAX),
        "parts": parts,
    }


def _table(rows: list) -> str:
    out = ["%9s %7s %7s %6s %6s %5s %5s  %s" % (
        "sku", "floor", "unpnt", "worst", "mean", "parts", "over", "worst part")]
    for r in sorted(rows, key=lambda r: -(r["worst"] or -1)):
        worst = max((p for p in r["parts"] if p["gap"] is not None),
                    key=lambda p: p["gap"], default=None)
        who = ("%s#%d %s->%s" % (worst["role"], worst["part"],
                                 worst["fill"], worst["seen"])) if worst else "--"
        out.append("%9s %7s %7s %6s %6s %5d %5d  %s" % (
            r["sku"],
            "--" if r["substrate_floor"] is None else "%.4f" % r["substrate_floor"],
            "%.4f" % r["unpainted_scatter"],
            "--" if r["worst"] is None else "%.4f" % r["worst"],
            "--" if r["mean"] is None else "%.4f" % r["mean"],
            r["n_measured"], r["over_threshold"], who))
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sku", help="one carton; prints, writes nothing")
    args = ap.parse_args()

    if args.sku:
        # Never writes. A single-SKU run that rewrote the report with one row is
        # a defect this project has already fixed once, in `design_qa`.
        r = measure(args.sku)
        print(_table([r]))
        for p in sorted((p for p in r["parts"] if p["gap"] is not None),
                        key=lambda p: -p["gap"]):
            print("   %-12s px=%-8d %6.3f%%  %s -> %s   gap=%.4f  lvl=%.4f  "
                  "spread=%.4f" % (
                      f'{p["role"]}#{p["part"]}', p["px"], p["visible_pct"],
                      p["fill"], p["seen"], p["gap"], p["gap_levelled"],
                      p["spread"]))
        return 0

    rows = [measure(stem) for stem in sorted(FOLDER_BY_STEM)]
    print(_table(rows))
    live = [g for r in rows for g in (p["gap"] for p in r["parts"]) if g is not None]
    floors = [r["substrate_floor"] for r in rows if r["substrate_floor"] is not None]
    summary = {
        "n_cartons": len(rows),
        "n_parts": len(live),
        "over_threshold": sum(1 for g in live if g >= SAME_SURFACE_MAX),
        "threshold": SAME_SURFACE_MAX,
        "mean_gap": round(float(np.mean(live)), 4) if live else None,
        "worst_gap": round(max(live), 4) if live else None,
        "substrate_floor_mean": round(float(np.mean(floors)), 4) if floors else None,
        "substrate_floor_worst": round(max(floors), 4) if floors else None,
    }
    print("\n%d of %d parts at or beyond %.2f; floor mean %.4f worst %.4f" % (
        summary["over_threshold"], summary["n_parts"], SAME_SURFACE_MAX,
        summary["substrate_floor_mean"], summary["substrate_floor_worst"]))
    REPORT.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1),
                      encoding="utf-8")
    print(REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
