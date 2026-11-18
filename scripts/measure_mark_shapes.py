#!/usr/bin/env python
"""What an approved mark actually DRAWS: a blob, or a letterform?

This exists because the answer was got wrong once, in writing, and an owner
decided partly on it. `00_PROJECT_STATE/MARKS_EVIDENCE.md` measured every
approved hole as solid -- `islands = 0`, `solid_frac = 1.000` -- and that was
read as "the wordmark is not carried and would not appear in the render". Both
halves of that reading are false:

- **A glyph touching the boundary is not an island.** It is a NOTCH, and the
  Moore-neighbour trace walks around it, so it survives into the outline.
  `74_Viagra`'s Pfizer oval emits as an oval with the "fi" ligature cut out.
- **A silhouette of a wordmark IS the wordmark.** A filled outline of Lilly's
  script reads "Lilly"; nothing about being one colour makes it less the mark.

So this measures the emitted polygon rather than the mask it came from, and it
measures the one property that separates the two cases: **solidity**, the ring's
own area over its convex hull's. A blob is near 1.0; a letterform is far below,
because a script or a notched oval encloses a fraction of the hull it spans.

    python scripts/measure_mark_shapes.py            # every emitted mark
    python scripts/measure_mark_shapes.py --draw     # write the shapes to look at

It reports and gates nothing. Which marks may be drawn is a person's decision,
recorded in `MARKS_DECISION.md`; this only makes sure that decision is taken
against what will actually appear.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.design_group import FOLDER_BY_STEM, TEMPLATES_DIR  # noqa: E402

REPORT = PROJECT_ROOT / "00_PROJECT_STATE" / "mark_shapes.json"
DRAW_DIR = PROJECT_ROOT / "02_processing" / "mark_shapes"

#: Below this the ring is carrying letterform geometry rather than a silhouette.
#: Taken from the measured distribution, which has a clear gap: eleven marks sit
#: at 0.907-1.000 and the rest at 0.190-0.825, with nothing between 0.825 and
#: 0.907. Not a gate -- a threshold that refused a mark would be this script
#: deciding what only the owner may.
BLOB_MIN = 0.85


def _hull(points):
    """Monotone chain. Written out because this module imports no CV library."""
    pts = sorted(set((float(x), float(y)) for x, y in points))
    if len(pts) < 3:
        return pts

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2:
                (x1, y1), (x2, y2) = out[-2], out[-1]
                if (x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1) <= 0:
                    out.pop()
                else:
                    break
            out.append(p)
        return out

    return half(pts)[:-1] + half(pts[::-1])[:-1]


def _area(poly) -> float:
    """Shoelace, unsigned."""
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def solidity(outline) -> float:
    """Ring area over its convex hull's. 1.0 is convex; a script is far below."""
    hull = _hull(outline)
    h = _area(hull)
    return (_area(outline) / h) if h else 1.0


def measure() -> list:
    rows = []
    for stem, folder in sorted(FOLDER_BY_STEM.items()):
        path = TEMPLATES_DIR / folder / "design_spec.json"
        if not path.exists():
            continue
        spec = json.loads(path.read_text(encoding="utf-8"))
        for mark in spec.get("marks") or []:
            s = solidity(mark["outline"])
            rows.append({
                "sku": stem,
                "folder": folder,
                "key": mark["key"],
                "source": mark["source"],
                "area_pct": mark.get("area_pct"),
                "vertices": len(mark["outline"]),
                "solidity": round(s, 3),
                "reads_as": "blob" if s >= BLOB_MIN else "letterform",
            })
    return rows


def draw(rows) -> None:
    """One PNG per mark, at its own scale, so the shape can be LOOKED at."""
    from PIL import Image, ImageDraw
    DRAW_DIR.mkdir(parents=True, exist_ok=True)
    for row in rows:
        spec = json.loads((TEMPLATES_DIR / row["folder"] / "design_spec.json")
                          .read_text(encoding="utf-8"))
        mark = next(m for m in spec["marks"] if m["key"] == row["key"])
        us = [p[0] for p in mark["outline"]]
        vs = [p[1] for p in mark["outline"]]
        u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
        w = 360
        h = max(40, int(round(w * (v1 - v0) / max(1e-6, u1 - u0))))
        img = Image.new("L", (w, h), 0)
        ImageDraw.Draw(img).polygon(
            [((u - u0) / (u1 - u0) * (w - 1), (v - v0) / (v1 - v0) * (h - 1))
             for u, v in mark["outline"]], fill=255)
        name = f'{row["sku"]}_{row["key"].replace("/", "-").replace("#", "")}.png'
        img.save(DRAW_DIR / name)
    print(f"[mark_shapes] {len(rows)} shape(s) in {DRAW_DIR}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draw", action="store_true",
                    help="write each emitted mark as a PNG to look at")
    args = ap.parse_args()

    rows = measure()
    print("%9s %-20s %-10s %6s %8s  %s" % (
        "sku", "key", "source", "verts", "solidity", "reads as"))
    for r in sorted(rows, key=lambda r: r["solidity"]):
        print("%9s %-20s %-10s %6d %8.3f  %s" % (
            r["sku"], r["key"], r["source"], r["vertices"],
            r["solidity"], r["reads_as"]))
    letters = [r for r in rows if r["reads_as"] == "letterform"]
    print(f"\n{len(letters)} of {len(rows)} emitted marks carry letterform "
          f"geometry (solidity < {BLOB_MIN}); the rest are convex blobs.")
    if args.draw:
        draw(rows)
    REPORT.write_text(json.dumps(
        {"threshold": BLOB_MIN, "n_marks": len(rows),
         "n_letterform": len(letters), "rows": rows}, indent=1), encoding="utf-8")
    print(REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
