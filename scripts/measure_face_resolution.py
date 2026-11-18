"""Phase 3 — how many real pixels each reference face has, and which are short.

    python scripts/measure_face_resolution.py
    python scripts/measure_face_resolution.py --folder 357_Adderall

WHY THIS EXISTS. `measure_reference_face.OUT_WIDTH` is 1100 for every folder,
whatever the photograph. The front face of `357_Adderall` measures 134x172
pixels in its source, so every outline traced from it is traced from a picture
enlarged 8.2 times, and `SIMPLIFY_TOLERANCE`, a thousandth of the rectified
width, works out at 0.13 of a source pixel there -- finer than the grid the
evidence is on.

That is a ceiling, not a defect, and nothing in the tree stated it. This script
states it. It DOES NOT drop a folder, change `OUT_WIDTH`, or gate anything in
the pipeline: `107_Tramadol` is already named in `UNMEASURABLE` because its
segmentation is speckle, and this is the same kind of statement about a
different limit. A folder below the threshold keeps its spec and keeps
rendering; what changes is that its resolution is on the record instead of
being a surprise the next time a figure moves.

WHERE THE FACE COMES FROM. `metadata.json`'s `front_face_px` -- the same four
corners `rectified_face()` warps from, so the size reported here is the size the
measurement actually had, not a property of the file on disk. A folder whose
photograph is absent (a clean clone has none: `Reference Templates/**/*.png` and
friends are gitignored) still reports its face size, because the corners are in
the metadata rather than in the picture.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.design_group import FOLDER_BY_STEM  # noqa: E402
from scripts.measure_reference_face import OUT_WIDTH  # noqa: E402

TEMPLATES_DIR = PROJECT_ROOT / "Reference Templates"
OUT_PATH = PROJECT_ROOT / "00_PROJECT_STATE" / "face_resolution.json"

#: Below this many source pixels across the printed face, a spec traced from the
#: photograph is describing an enlargement rather than the print.
#:
#: TAKEN FROM THE DISTRIBUTION, not chosen. Sorted by face width the 28 folders
#: of the design group run 134, 147, 260, 278, 302, 322, 387, 393, 398, 407,
#: 413, 425, 446, 459, 500, 548, 548, 587, 590, 628, 684, 719, 737, 760, 856,
#: 887, 1050, 1128. The one real gap in the low half is between 322 and 387 --
#: a 20% step, where every neighbouring step above it is under 8%. 350 sits in
#: that gap and names the six folders whose face is enlarged more than three
#: times. (`107_Tramadol` at 249 would fall here too; it is already out of the
#: sample by name, for its speckle rather than its size.)
MIN_FACE_PX = 350

FOLDERS = sorted(set(FOLDER_BY_STEM.values()), key=lambda n: int(n.split("_")[0]))


def face_size(corners) -> tuple[float, float]:
    """Mean edge lengths of the quad, in source pixels: (across, down).

    The mean of the two opposite edges rather than either one, because under
    perspective they differ and neither is the face.
    """
    (tl, tr, br, bl) = [(float(c[0]), float(c[1])) for c in corners]
    top = math.hypot(tr[0] - tl[0], tr[1] - tl[1])
    bottom = math.hypot(br[0] - bl[0], br[1] - bl[1])
    left = math.hypot(bl[0] - tl[0], bl[1] - tl[1])
    right = math.hypot(br[0] - tr[0], br[1] - tr[1])
    return (top + bottom) / 2.0, (left + right) / 2.0


def measure(folder: Path) -> dict:
    md = folder / "metadata.json"
    row = {"folder": folder.name, "sku": None, "source_image": None,
           "face_px": None, "face_w": None, "face_h": None,
           "upscale_to_out_width": None, "below_threshold": None}
    if not md.exists():
        row["note"] = "no metadata.json"
        return row
    meta = json.loads(md.read_text(encoding="utf-8"))
    row["sku"] = meta.get("sku_id")
    row["source_image"] = ((meta.get("front_face_measurement") or {}).get("source_image")
                           or (meta.get("reference_images") or [None])[0])
    corners = meta.get("front_face_px")
    if not corners or len(corners) != 4:
        row["note"] = "no front_face_px"
        return row
    w, h = face_size(corners)
    row["face_w"] = round(w, 1)
    row["face_h"] = round(h, 1)
    row["face_px"] = f"{round(w)}x{round(h)}"
    row["upscale_to_out_width"] = round(OUT_WIDTH / w, 2) if w else None
    row["below_threshold"] = bool(w < MIN_FACE_PX)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--folder", action="append",
                    help="one folder name; repeatable. Default: the whole group.")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    rows = [measure(TEMPLATES_DIR / n) for n in (args.folder or FOLDERS)]
    measured = [r for r in rows if r["face_w"]]
    short = [r for r in measured if r["below_threshold"]]

    print(f"{'folder':<24}{'face px':>12}{'upscale':>9}")
    print("-" * 46)
    for r in sorted(measured, key=lambda r: -r["upscale_to_out_width"]):
        mark = "  <- below threshold" if r["below_threshold"] else ""
        print(f"{r['folder']:<24}{r['face_px']:>12}{r['upscale_to_out_width']:>8.2f}x{mark}")
    for r in rows:
        if not r["face_w"]:
            print(f"{r['folder']:<24}{'--':>12}{'--':>9}   {r.get('note', '')}")

    out = {"schema": "face_resolution/1",
           "out_width": OUT_WIDTH,
           "min_face_px": MIN_FACE_PX,
           "folders_measured": len(measured),
           "folders_below_threshold": sorted(r["folder"] for r in short),
           "rows": rows}
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n{len(short)} of {len(measured)} folders below {MIN_FACE_PX}px: "
          f"{', '.join(sorted(r['folder'] for r in short)) or 'none'}")
    print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
