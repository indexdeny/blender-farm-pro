"""Phase 1 — what would cutting each hole be worth, and nothing else.

    python scripts/measure_hole_payoff.py                 # the whole group
    python scripts/measure_hole_payoff.py --folder 64_Kamagra

WHY THIS EXISTS. Contract 1.8 cuts a hole only where a person classified it
`window`, and ten of the group's 238 are. Measured over all 75 printed
components, a polyline with every hole cut scores 0.9536 against 0.8855 for the
outer ring alone, so the whole 6.8-point gap between them belongs to holes. The
question that gap raises is not "should the rule change" -- it should not, and
`404_Ritalin`'s 72 letterform holes are why -- but "is there anything among the
228 filled holes that a person would call a window, and is it worth a review".

That is two questions, and they must not be answered by the same artefact.
Whether a hole is a window is semantic and human; what cutting it would be worth
is mechanical. This script answers ONLY the mechanical one. It never proposes a
class, and it never writes to `print_truth.json` -- `tests/test_hole_payoff.py`
enforces both by static scan, because a script that ranks holes by payoff and
also offers a class is a machine for turning another manufacturer's lettering
into windows.

The output is read BEFORE any review, to decide whether the review is worth
doing at all. It is deliberately not joined to the labelling aid.

HOW THE FIGURE IS TAKEN. `truth_agreement` from `design_coverage.py`, which
needs no render: it scores the spec's region index against the hand-made ground
truth over the union of "the reference prints here" and "the spec draws here".

Cutting one hole changes pixels only inside that hole's ring, and what they
become is whatever the spec paints there with this part absent. So `behind` is
computed ONCE PER PART -- 75 rasterisations for the group -- and each of that
part's holes is then a masked substitution plus a numpy pass, rather than a
fresh `spec_index` per hole. Exact, because outside the ring nothing moves and
inside it the part no longer paints; a later field that overlaps the hole is
unaffected either way and keeps its own index in both maps.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.design_group import FOLDER_BY_STEM  # noqa: E402
from scripts.design_coverage import (  # noqa: E402
    SUBSTRATE, STEM_BY_FOLDER, read_spec, spec_index, truth_from_labels,
)
from scripts.fit_design_spec import (  # noqa: E402
    MIN_HOLE_FRAC, SIMPLIFY_TOLERANCE, _simplify_to_a_region, components,
    enclosed_background, load_truth, part_region, trace_outline,
)
from scripts.measure_reference_face import segment  # noqa: E402

TEMPLATES_DIR = PROJECT_ROOT / "Reference Templates"
OUT_PATH = PROJECT_ROOT / "00_PROJECT_STATE" / "hole_payoff.json"

#: The class contract 1.8 cuts. Read here only to tell "already cut" from
#: "would be cut if reclassified" -- never to suggest that anything become it.
CUT_CLASS = "window"

#: The class whose holes are the reference's own type. Excluded from the
#: headline potential, because the question this script exists to answer is
#: whether there is anything worth reviewing OUTSIDE what a person has already
#: called lettering. Reported separately rather than hidden.
LETTERING_CLASS = "lettering"

#: Buckets for the distribution, in points of `truth_agreement`.
BUCKETS = (0.1, 1.0)

FOLDERS = sorted(set(FOLDER_BY_STEM.values()), key=lambda n: int(n.split("_")[0]))


def _agreement(s_idx: np.ndarray, lt_idx: np.ndarray,
               lt_ref: np.ndarray, lt_scored: np.ndarray) -> float | None:
    """`truth_agreement`, exactly as design_coverage.coverage() computes it."""
    lt_spec = (s_idx != SUBSTRATE) & lt_scored
    union = lt_ref | lt_spec
    return float((s_idx == lt_idx)[union].mean()) if union.any() else None


def _ring_uv(hole: np.ndarray, w: int, h: int) -> list | None:
    """One hole traced and stored exactly as `trace_holes` would store it."""
    outline = trace_outline(hole)
    if len(outline) < 8:
        return None
    pts, _used = _simplify_to_a_region(outline, w, h, SIMPLIFY_TOLERANCE)
    if len(pts) < 3:
        return None
    return [[round(x / w, 4), round(y / h, 4)] for x, y in pts]


def measure(folder: Path) -> dict:
    stem = STEM_BY_FOLDER[folder.name]
    spec = read_spec(folder, "design_spec.json")
    flat, labels, named, meta, source = segment(folder)
    w, h = flat.width, flat.height
    lab = labels.reshape(h, w)

    truth = load_truth(folder)
    if truth is None:
        raise SystemExit(f"{folder.name}: print_truth.json is absent.")
    label_of = {c["key"]: c.get("class") for c in truth["components"]}
    hole_class = {c["key"]: c.get("class") for c in (truth.get("holes") or [])}
    min_region = int(float(truth["enumerate_min_frac"]) * w * h)
    min_hole = int(MIN_HOLE_FRAC * w * h)

    roles = [f["role"] for f in (spec.get("fields") or [])]
    field_of_role = {r: n for n, r in enumerate(roles)}
    lt_idx, lt_scored, lt_missing = truth_from_labels(
        folder, np.asarray(flat), lab, named, roles)
    lt_ref = (lt_idx != SUBSTRATE) & lt_scored

    s_idx = spec_index(spec, w, h)
    base = _agreement(s_idx, lt_idx, lt_ref, lt_scored)

    # The enumeration `fit()` runs, so `role#i` addresses the same surface here.
    order = [(role, named[role]["label"]) for role in sorted(named)
             if role != "substrate" and named.get(role) is not None]

    holes_out = []
    for role, j in order:
        fi = field_of_role.get(role)
        printed_seen = 0
        for i, part in enumerate(components(lab == j, min_region)):
            key = f"{role}#{i}"
            if label_of.get(key) != "print":
                continue
            pi = printed_seen
            printed_seen += 1
            if fi is None:
                continue                    # role emitted no field; nothing to cut into

            # What the spec paints inside this part's footprint with the part
            # absent. One rasterisation per part, reused by all of its holes.
            without = copy.deepcopy(spec)
            del without["fields"][fi]["parts"][pi]
            behind = spec_index(without, w, h)

            for jj, hole in enumerate(enclosed_background(part)):
                if hole.sum() < min_hole:
                    continue
                hkey = f"{key}/hole#{jj}"
                cls = hole_class.get(hkey)
                area_pct = round(100.0 * float(hole.sum()) / (w * h), 4)

                if cls == CUT_CLASS:
                    holes_out.append({"key": hkey, "sku": stem, "folder": folder.name,
                                      "class": cls, "area_pct": area_pct,
                                      "already_cut": True, "delta": 0.0})
                    continue

                ring = _ring_uv(hole, w, h)
                if ring is None:
                    holes_out.append({"key": hkey, "sku": stem, "folder": folder.name,
                                      "class": cls, "area_pct": area_pct,
                                      "already_cut": False, "delta": None,
                                      "note": "ring too small to represent"})
                    continue

                mask = part_region({"outline": ring, "holes": []}, w, h)
                if mask is None:
                    continue
                m = np.asarray(mask, dtype=bool)
                cut = np.where(m, behind, s_idx)
                agr = _agreement(cut, lt_idx, lt_ref, lt_scored)
                delta = (None if (agr is None or base is None)
                         else round(100.0 * (agr - base), 4))
                holes_out.append({"key": hkey, "sku": stem, "folder": folder.name,
                                  "class": cls, "area_pct": area_pct,
                                  "already_cut": False, "delta": delta})

    # A label whose hole no longer exists is KEPT and flagged `vanished` by
    # label_print, so the truth file carries more entries than the partition
    # has holes. Reported rather than left as a discrepancy for the next reader
    # to re-derive: `74_Viagra` alone carries three, speckle labelled against
    # the corners this branch corrected in 6d37b89.
    truth_holes = truth.get("holes") or []
    vanished = [hh["key"] for hh in truth_holes if hh.get("vanished")]

    return {"folder": folder.name, "sku": stem,
            "truth_agreement": None if base is None else round(base, 4),
            "truth_hole_entries": len(truth_holes),
            "vanished_labels": vanished,
            "holes": holes_out}


def summarise(rows: list) -> dict:
    holes = [hh for r in rows for hh in r["holes"]]
    measurable = [hh for hh in holes if hh.get("delta") is not None
                  and not hh["already_cut"]]
    non_lettering = [hh for hh in measurable if hh["class"] != LETTERING_CLASS]

    def buckets(hs):
        lo, hi = BUCKETS
        return {f"under_{lo}": sum(1 for x in hs if abs(x["delta"]) < lo),
                f"{lo}_to_{hi}": sum(1 for x in hs if lo <= abs(x["delta"]) < hi),
                f"over_{hi}": sum(1 for x in hs if abs(x["delta"]) >= hi)}

    by_class = {}
    for hh in holes:
        c = hh["class"] or "unclassified"
        d = by_class.setdefault(c, {"count": 0, "potential_pts": 0.0})
        d["count"] += 1
        if hh.get("delta") is not None and not hh["already_cut"]:
            d["potential_pts"] += hh["delta"]
    for d in by_class.values():
        d["potential_pts"] = round(d["potential_pts"], 3)

    vanished = [k for r in rows for k in r.get("vanished_labels", [])]
    entries = sum(r.get("truth_hole_entries", 0) for r in rows)

    return {
        "holes_total": len(holes),
        "truth_hole_entries": entries,
        "vanished_labels": vanished,
        "vanished_note": (
            f"{entries} hole entries across the truth files, {len(vanished)} of them "
            f"flagged `vanished` by label_print -- a label whose hole the partition no "
            f"longer has is kept and flagged rather than deleted. {len(holes)} holes "
            f"were enumerated here, which is the difference."),
        "already_cut": sum(1 for hh in holes if hh["already_cut"]),
        "measured": len(measurable),
        "unrepresentable_rings": sum(1 for hh in holes
                                     if hh.get("delta") is None and not hh["already_cut"]),
        "potential_all_pts": round(sum(x["delta"] for x in measurable), 3),
        "potential_excluding_lettering_pts": round(
            sum(x["delta"] for x in non_lettering), 3),
        "positive_potential_excluding_lettering_pts": round(
            sum(x["delta"] for x in non_lettering if x["delta"] > 0), 3),
        "distribution_all": buckets(measurable),
        "distribution_excluding_lettering": buckets(non_lettering),
        "by_class": by_class,
        "enumeration_floor_note": (
            f"Holes are enumerated by enclosed_background() above "
            f"MIN_HOLE_FRAC={MIN_HOLE_FRAC}, so the total here is holes above "
            f"that floor, not every hole in the segmentation."),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--folder", action="append",
                    help="one folder name; repeatable. Default: the whole group.")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    folders = args.folder or FOLDERS
    rows = []
    for name in folders:
        folder = TEMPLATES_DIR / name
        try:
            row = measure(folder)
        except SystemExit as exc:
            print(f"{name}: SKIPPED — {exc}", file=sys.stderr)
            continue
        rows.append(row)
        n = len(row["holes"])
        pot = sum(hh["delta"] for hh in row["holes"]
                  if hh.get("delta") is not None and not hh["already_cut"])
        print(f"{name:<24} holes {n:>4}   potential {pot:+7.3f} pts")

    out = {"schema": "hole_payoff/1",
           "metric": "truth_agreement, in points (100 x the fraction)",
           "summary": summarise(rows), "cartons": rows}
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    s = out["summary"]
    print(f"\n{s['holes_total']} holes, {s['already_cut']} already cut, "
          f"{s['measured']} measured")
    print(f"potential, all holes:            {s['potential_all_pts']:+.3f} pts")
    print(f"potential, excluding lettering:  {s['potential_excluding_lettering_pts']:+.3f} pts")
    print(f"  of which positive only:        {s['positive_potential_excluding_lettering_pts']:+.3f} pts")
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
