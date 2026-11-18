"""Did the partition move, and does the hand-made labelling still fit it?

    python scripts/probe_partition_shift.py --lightness
    python scripts/probe_partition_shift.py --space
    python scripts/probe_partition_shift.py --lightness --json-out shift.json

Writes nothing. Run this BEFORE applying any change to
`scripts/measure_reference_face.py`, because the thing at risk is not a figure —
it is 661 components and 239 holes that a person classified by hand.

WHY THIS EXISTS AT ALL. `print_truth.json` keys a class to `role#i`, where `i` is
the index a component takes in `components()` after filtering by area and sorting
by descending area, and `role` is the name `segment()` gave its cluster. Both
halves of that key are outputs of the partition. Move the partition and the keys
address different surfaces — sometimes with the same count, the same names and
the same shapes, so nothing raises and the labels are silently wrong.

`fit()` does stop on a key it has never seen. It cannot stop on a key that still
exists and now means something else, and neither can `label_print --verify`,
which asks whether every component has a class rather than whether it is the
right one. This probe asks the question neither of them can.

WHAT IT COMPARES. Two partitions of the same rectified face — the one this
checkout produces now, and the one produced with the estimator or the colour
space swapped back to what it was. It reports, per folder:

  keys       gained / lost between the two enumerations
  roles      whether a role covers a materially different surface (colour, area)
  drift      how far a matched component's area and bbox moved

A gained or lost key invalidates the labelling outright. A role whose colour or
area jumps invalidates it just as thoroughly while leaving every key in place,
which is the case this file was written for.
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

import scripts.measure_reference_face as mrf  # noqa: E402
from scripts.fit_design_spec import components, load_truth  # noqa: E402
from src.design_group import TEMPLATE_SAMPLE, TEMPLATES_DIR  # noqa: E402

#: The estimator `_flatten_illumination` used before this migration: V of HSV.
#: Kept here rather than in the module under test, so the old behaviour is
#: reachable for comparison without being reachable by accident.
def _value_lightness(rgb: np.ndarray) -> np.ndarray:
    return rgb.max(-1)


#: The space `_kmeans` clustered in before this migration: the corrected sRGB
#: values themselves, unconverted.
def _identity_space(x: np.ndarray) -> np.ndarray:
    return x


#: Which module-level name each event swaps, and what it swaps in. The seam has
#: to exist in `measure_reference_face` for the probe to have anything to
#: compare -- both changes were rejected and reverted on 2026-08-24, so on this
#: checkout neither seam is present and the probe says so instead of throwing.
_SEAMS = {"lightness": ("_lightness", _value_lightness),
          "space": ("_cluster_space", _identity_space)}


def enumerate_partition(folder: Path) -> dict:
    """Every component `fit()` would see, keyed and described the way it is labelled.

    Uses `components()` and the truth file's own `enumerate_min_frac`, so this
    counts what the fitter counts rather than a second idea of it.
    """
    flat, labels, named, meta, _src = mrf.segment(folder)
    w, h = flat.width, flat.height
    lab = labels.reshape(h, w)
    truth = load_truth(folder)
    min_region = int(float(truth["enumerate_min_frac"]) * w * h)

    out = {}
    roles = {}
    for role in sorted(named):
        g = named.get(role)
        if g is None or role == "substrate":
            if g is not None:
                roles[role] = {"colour": [round(float(c), 4) for c in g["colour"]],
                               "share": round(g["n"] / (w * h), 4)}
            continue
        roles[role] = {"colour": [round(float(c), 4) for c in g["colour"]],
                       "share": round(g["n"] / (w * h), 4)}
        for i, part in enumerate(components(lab == g["label"], min_region)):
            ys, xs = np.nonzero(part)
            out[f"{role}#{i}"] = {
                "area_pct": round(100 * float(part.sum()) / (w * h), 3),
                "bbox_uv": [round(float(xs.min()) / w, 4), round(float(ys.min()) / h, 4),
                            round(float(xs.max()) / w, 4), round(float(ys.max()) / h, 4)],
            }
    return {"components": out, "roles": roles, "size": [w, h]}


def compare(folder: Path, swap: str) -> dict:
    """Enumerate twice — as the tree stands, and with *swap* reverted."""
    now = enumerate_partition(folder)

    seam, old = _SEAMS[swap]
    if not hasattr(mrf, seam):
        raise SystemExit(
            f"scripts/measure_reference_face.py has no `{seam}`, so there is "
            f"nothing to swap: the {swap} change is not applied to this "
            f"checkout. Both changes were measured on 2026-08-24 and REJECTED "
            f"-- see 00_PROJECT_STATE/TOOLING_MIGRATION.md section 4. Re-apply "
            f"the seam before re-running this probe.")
    saved = getattr(mrf, seam)
    setattr(mrf, seam, old)
    try:
        before = enumerate_partition(folder)
    finally:
        setattr(mrf, seam, saved)

    a, b = before["components"], now["components"]
    gained = sorted(set(b) - set(a))
    lost = sorted(set(a) - set(b))

    drift = []
    for key in sorted(set(a) & set(b)):
        da = abs(a[key]["area_pct"] - b[key]["area_pct"])
        db = max(abs(x - y) for x, y in zip(a[key]["bbox_uv"], b[key]["bbox_uv"]))
        drift.append((key, round(da, 3), round(db, 4)))

    role_moves = []
    for role in sorted(set(before["roles"]) | set(now["roles"])):
        ra, rb = before["roles"].get(role), now["roles"].get(role)
        if ra is None or rb is None:
            role_moves.append((role, "appeared" if ra is None else "vanished", None))
            continue
        dc = float(np.linalg.norm(np.array(ra["colour"]) - np.array(rb["colour"])))
        ds = abs(ra["share"] - rb["share"])
        if dc > 0.02 or ds > 0.01:
            role_moves.append((role, round(dc, 4), round(ds, 4)))

    return {"folder": folder.name, "gained": gained, "lost": lost,
            "role_moves": role_moves,
            "worst_area_drift": max((d[1] for d in drift), default=0.0),
            "worst_bbox_drift": max((d[2] for d in drift), default=0.0),
            "matched": len(drift)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lightness", action="store_true",
                   help="compare against the old V-of-HSV lightness estimator")
    p.add_argument("--space", action="store_true",
                   help="compare against clustering in the corrected sRGB values")
    p.add_argument("--folder", action="append", help="one folder; repeatable")
    p.add_argument("--json-out")
    args = p.parse_args()
    if args.lightness == args.space:
        p.error("pass exactly one of --lightness or --space: they are two "
                "measuring events and comparing both at once attributes nothing")
    swap = "lightness" if args.lightness else "space"

    names = args.folder or sorted(TEMPLATE_SAMPLE)
    rows, unstable = [], []
    print(f"{'folder':26s} {'matched':>7s} {'gained':>6s} {'lost':>5s} "
          f"{'d.area':>7s} {'d.bbox':>7s}  role moves")
    for name in names:
        row = compare(TEMPLATES_DIR / name, swap)
        rows.append(row)
        moved = ", ".join(f"{r[0]}({r[1]},{r[2]})" for r in row["role_moves"])
        if row["gained"] or row["lost"] or row["role_moves"]:
            unstable.append(name)
        print(f"{name:26s} {row['matched']:7d} {len(row['gained']):6d} "
              f"{len(row['lost']):5d} {row['worst_area_drift']:7.3f} "
              f"{row['worst_bbox_drift']:7.4f}  {moved}")

    print()
    if unstable:
        print(f"UNSTABLE on {len(unstable)} of {len(names)}: {', '.join(unstable)}")
        print("The labelling is keyed to this enumeration. A gained or lost key, "
              "or a role covering a different surface, means print_truth.json "
              "no longer describes what it was written against. That is a stop.")
    else:
        print(f"STABLE on all {len(names)}: every component key survives and no "
              f"role changed surface. The labelling still fits the partition.")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"swap": swap, "rows": rows},
                                                  indent=2), encoding="utf-8")
        print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
