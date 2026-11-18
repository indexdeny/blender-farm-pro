"""D-7 — does our carton set its type where the real carton sets it?

    python scripts/type_qa.py                  # every design SKU
    python scripts/type_qa.py --sku 156-min --preview

D-6 measures colour and fields and says plainly that it does not measure type:
every figure there excludes dark pixels, because the spec carries fields and the
label is drawn from the manifest. This is the missing axis. It renders the same
SKU, rectifies it with the corners the driver publishes, and reads back where the
label rows actually landed — then compares that against the boxes D-2b measured
off the photograph.

WHAT IS COMPARABLE AND WHAT IS NOT. The two cartons carry DIFFERENT WORDS by
design: the Ritalin folder photographs a pack reading "Motiron", ours prints
Ritalin, and copying the reference's words onto our carton is the exact failure
the text-as-geometry rule exists to prevent. So a row's WIDTH is not evidence of
anything — a longer word makes a longer box — and neither is box IoU, which is
mostly width. What survives the difference in strings:

  dv_cap_top  where the row's CAPITALS start down the face
  du_anchor   where the row sits across it, read at the end alignment pins
  cap_ratio   how big the type is, ours over the reference's

Both sides are read with the SAME instrument — Tesseract word boxes on a
rectified face, the reader D-2b used on the photographs — so the reader's own
bias sits on both sides of the subtraction rather than on ours alone. A figure
from `--dump-scene` would be exact for our render and would then be differenced
against an OCR box, putting the whole of the reader's error into our column.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from src.deskew import flatten_face  # noqa: E402
from src.design_group import FOLDER_BY_STEM, load_design  # noqa: E402
from src.utils import load_config, resolve_path  # noqa: E402
from scripts.catalogue_sweep import is_stale  # noqa: E402
from scripts.design_qa import OUT_WIDTH, render_fresh  # noqa: E402
from scripts.measure_type_rows import (  # noqa: E402
    _lines, _similar, _words, assign_roles, ink_profile, ink_within, usable)

_CFG = load_config()
MANIFEST_DIR = resolve_path(_CFG["paths"]["passports_manifests"])
PREVIEW_DIR = PROJECT_ROOT / "02_processing" / "reference_measurement"

ROLES = ("brand_name_display", "active_ingredient_display",
         "dosage_display", "unit_count_display")

# Two readings of a row that overlap by more than this are the same row, found
# twice. The upright and inverted passes return identical boxes wherever the ink
# is dark on a light board, which is most rows on most cartons.
SAME_ROW_IOU = 0.5

# How closely the reader must return the string we printed before its BOX is
# treated as a measurement of that string. Identifying a row needs far less --
# `assign_roles` matches at 0.5, and it is right to, since a half-read word is
# still unambiguously which row it is. Measuring needs more, because a box is
# only where the row is if it contains the row and nothing else. `156-min` is
# the case that sets this: the fitter left the reference's own traced wordmark
# in the spec as a colour field, the driver duly built it, and the reader merged
# that shape with our brand into one row reading "XAXa" -- 0.50 against "Xanax",
# a box 0.27 of the face wide of where our brand actually stands. Our brand is
# in the right place; the row is unreadable, which is a different thing and has
# to be reported as one.
READ_MIN = 0.75


def _box_iou(a, b) -> float:
    x0 = max(a["u0"], b["u0"]); x1 = min(a["u1"], b["u1"])
    y0 = max(a["v0"], b["v0"]); y1 = min(a["v1"], b["v1"])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    area_a = (a["u1"] - a["u0"]) * (a["v1"] - a["v0"])
    area_b = (b["u1"] - b["u0"]) * (b["v1"] - b["v0"])
    return inter / max(1e-9, area_a + area_b - inter)


def _alnum_len(text: str) -> int:
    return sum(c.isalnum() for c in text)


def read_rows(face: Image.Image) -> list[dict]:
    """Every row on this face, read upright and reversed out.

    The driver reverses the label out of a dark colour block where the design
    has one — `_reverse_ink()` — and Tesseract binarises light-on-dark badly:
    Kamagra's ingredient sits in its teal field and is invisible to the upright
    pass while its brand, black on cream, reads fine. Inverting recovers it and
    returns the identical box for every row that already read, which is what
    makes merging the two passes safe rather than a second guess.
    """
    w, h = face.size
    merged: list[dict] = []
    for img in (face, ImageOps.invert(face.convert("RGB"))):
        for row in _lines(_words(img), w, h):
            if not usable(row):
                continue
            for i, seen in enumerate(merged):
                if _box_iou(row, seen) >= SAME_ROW_IOU:
                    if _alnum_len(row["text"]) > _alnum_len(seen["text"]):
                        merged[i] = row
                    break
            else:
                merged.append(row)
    return sorted(merged, key=lambda r: r["v0"])


def locate(face: Image.Image, printed: dict, design_parts=None) -> dict:
    """Our own rows, by role.

    Identified against the strings the manifest told the driver to print, which
    is a far easier match than the reference side had: there the reader was
    matching OCR against another manufacturer's wording, here it is matching
    against the exact string we drew. Rows that do not match a printed string
    are dropped rather than assigned by size, for the reason D-2b records — a
    box in the wrong place is worse than no box.
    """
    rows = [ink_within(face, r, design_parts or ()) for r in read_rows(face)]
    _roles, matched, boxes = assign_roles(rows, printed)
    return {role: boxes[role] for role in matched}


def _anchor(row: dict, align: str) -> float:
    return {"LEFT": row["u0"], "RIGHT": row["u1"],
            "CENTER": 0.5 * (row["u0"] + row["u1"])}[align]


def compare(spec_rows: dict, ours: dict, printed: dict) -> dict:
    """Row by row, against the boxes measured off the photograph.

    Only roles the REFERENCE carries are scored. A role it has no measurement
    for is drawn on the generic grid by design, and there is nothing to compare
    it against — counting it as a hit would score the grid against itself.

    A row whose reading does not come back as the string we printed is reported
    with its distances and left out of the aggregates: see READ_MIN.
    """
    per_role, dvs, dus = {}, [], []
    for role, ref in spec_rows.items():
        got = ours.get(role)
        if got is None:
            per_role[role] = None
            continue
        align = ref["align"]
        # Cap line against cap line, and cap height against cap height. What the
        # reader returns on either side is an INK box, whose top and height both
        # depend on the glyphs the string happens to carry -- and the two cartons
        # carry different words. Since contract 1.5 the reference's figures are
        # already converted; ours go through the same profile. Differencing the
        # ink boxes instead would report a descender as a size error and an
        # ascender as a placement one.
        ink_h, above_cap = ink_profile(role, printed.get(role) or "")
        our_cap = got["cap_frac"] / ink_h
        dv = (got["v0"] + above_cap * our_cap) - ref["cap_top_v"]
        du = _anchor(got, align) - _anchor(ref, align)
        read = _similar(got["text"], printed.get(role) or "")
        per_role[role] = {
            "dv_cap_top": round(dv, 4),
            "du_anchor": round(du, 4),
            "cap_ratio": round(our_cap / max(1e-6, ref["cap_frac"]), 3),
            "align": align,
            "read_as": got["text"],
            "read_score": round(read, 3),
            "scored": read >= READ_MIN,
        }
        if read >= READ_MIN:
            dvs.append(abs(dv))
            dus.append(abs(du))
    return {
        "rows_in_reference": len(spec_rows),
        "rows_located": sum(v is not None for v in per_role.values()),
        "rows_scored": len(dvs),
        "not_located": sorted(r for r, v in per_role.items() if v is None),
        "unreadable": sorted(r for r, v in per_role.items()
                             if v is not None and not v["scored"]),
        "worst_dv_cap": round(max(dvs), 4) if dvs else None,
        "worst_du_anchor": round(max(dus), 4) if dus else None,
        "mean_dv_cap": round(sum(dvs) / len(dvs), 4) if dvs else None,
        "by_role": per_role,
    }


def measure(stem: str, preview: bool = False, reuse: bool = False) -> dict:
    spec = load_design(stem)
    aspect = float(spec["face_aspect"])
    spec_rows = spec.get("type_rows") or {}

    # Reuse is allowed only where the PNG provably post-dates the driver that is
    # on disk now. The sweep's rule, borrowed rather than restated: a render
    # older than the driver cannot have come from it, so measuring it would
    # attribute today's numbers to yesterday's code.
    png = resolve_path(_CFG["blender"]["output_dir"]) / f"{stem}.png"
    usable_png = (png.exists() and png.with_suffix(".view.json").exists()
                  and not is_stale(png))
    if not (reuse and usable_png):
        png = render_fresh(stem)
    view = json.loads(png.with_suffix(".view.json").read_text(encoding="utf-8"))
    face = flatten_face(png, view["front_face_px"], out_width=OUT_WIDTH, aspect=aspect)

    manifest = json.loads((MANIFEST_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    printed = {r: (manifest.get("label_content") or {}).get(r) for r in ROLES}

    parts = [(f.get("fill"), p["outline"], p.get("holes") or [])
             for f in (spec.get("fields") or []) for p in (f.get("parts") or [])
             if len(p.get("outline") or []) >= 3]
    ours = locate(face, printed, parts)
    result = {"sku": stem, "folder": FOLDER_BY_STEM[stem],
              "rows_on_grid": sorted(r for r in ROLES if r not in spec_rows),
              **compare(spec_rows, ours, printed)}

    if preview:
        from PIL import ImageDraw
        w, h = face.size
        img = face.copy()
        d = ImageDraw.Draw(img)
        for role, ref in spec_rows.items():
            d.rectangle([ref["u0"] * w, ref["v0"] * h, ref["u1"] * w, ref["v1"] * h],
                        outline=(0, 190, 0), width=3)
        for role, got in ours.items():
            if role in spec_rows:
                d.rectangle([got["u0"] * w, got["v0"] * h, got["u1"] * w, got["v1"] * h],
                            outline=(255, 0, 255), width=3)
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        img.save(PREVIEW_DIR / f"{FOLDER_BY_STEM[stem]}.type.png")
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sku", help="one SKU stem; default is every design SKU")
    p.add_argument("--preview", action="store_true",
                   help="write the face with reference boxes green, ours magenta")
    p.add_argument("--reuse-render", action="store_true",
                   help="measure the PNG already on disk when it post-dates the "
                        "driver; renders anyway when it does not")
    args = p.parse_args()

    stems = [args.sku] if args.sku else sorted(
        FOLDER_BY_STEM, key=lambda s: int(s.split("-")[0]))

    rows, scored, in_ref = [], 0, 0
    print(f"{'SKU':9s} {'folder':32s} {'rows':>7s} {'worst dv':>9s} "
          f"{'mean dv':>8s} {'worst du':>9s}  not scored")
    for stem in stems:
        r = measure(stem, args.preview, args.reuse_render)
        rows.append(r)
        scored += r["rows_scored"]
        in_ref += r["rows_in_reference"]
        why = [f"{m.replace('_display', '')} (not found)" for m in r["not_located"]]
        why += [f"{m.replace('_display', '')} (unreadable)" for m in r["unreadable"]]
        if not r["rows_in_reference"]:
            why = ["(reference measured no rows)"]
        nan = float("nan")
        print(f"{stem:9s} {r['folder']:32s} "
              f"{r['rows_scored']:3d}/{r['rows_in_reference']:<3d} "
              f"{(r['worst_dv_cap'] if r['worst_dv_cap'] is not None else nan):9.4f} "
              f"{(r['mean_dv_cap'] if r['mean_dv_cap'] is not None else nan):8.4f} "
              f"{(r['worst_du_anchor'] if r['worst_du_anchor'] is not None else nan):9.4f}"
              f"  {', '.join(why)}")

    print(f"\ncoverage: {scored}/{in_ref} reference rows scored in our renders, "
          f"of {4 * len(rows)} rows printed")
    out = PROJECT_ROOT / "00_PROJECT_STATE" / "type_qa.json"
    out.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
