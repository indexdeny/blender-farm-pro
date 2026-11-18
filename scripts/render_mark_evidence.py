"""Phase 1 — show a person what every `mark` actually is, at a size they can judge.

    python scripts/render_mark_evidence.py
    python scripts/render_mark_evidence.py --folder 74_Viagra

WHY THIS EXISTS. `mark` holes are worth +9.937 points of group `truth_agreement`
-- 91% of everything reachable outside `lettering` -- and cutting one while
drawing nothing into it is forbidden, because it shows board through our field
in the shape of another company's logo. The only coherent form is to cut the
hole AS PART OF drawing the mark, and whether to do that is the owner's decision
rather than a measurement's.

Nobody has looked at what these 27 components and 8 holes contain. The truth
file's own note on `74_Viagra` calls its hole "a logo container, printed white on
the band" -- a white oval, that is, a SHAPE, with whatever sits inside it
classified separately as type. If most of the set is containers then the decision
is about filling regions; if it is artwork then it is about reproducing marks.
Those are different questions and the owner should be answering the real one.

So this script crops each one out of the rectified face at magnification and
writes a contact sheet. It states nothing and decides nothing: it produces
pictures, and a person writes down what they see.

READ-ONLY with respect to the labelling. `tests/test_mark_evidence.py` pins that
by static scan, the same instrument that keeps `measure_hole_payoff.py` honest.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.design_group import FOLDER_BY_STEM  # noqa: E402
from scripts.fit_design_spec import (  # noqa: E402
    MIN_HOLE_FRAC, components, enclosed_background, load_truth,
)
from scripts.measure_reference_face import segment  # noqa: E402

TEMPLATES_DIR = PROJECT_ROOT / "Reference Templates"
OUT_DIR = PROJECT_ROOT / "02_processing" / "marks_evidence"

MARK = "mark"
#: Long edge of each crop, in pixels. Big enough that a 0.1%-of-face component
#: is legible; the face itself is only 1100 wide.
CROP_LONG_EDGE = 520
#: Context kept around the component's own bounding box, as a share of it.
PAD_FRAC = 0.45
#: The tint laid over the classified pixels in the second panel.
TINT = (255, 40, 90)
TINT_ALPHA = 0.42

FOLDERS = sorted(set(FOLDER_BY_STEM.values()), key=lambda n: int(n.split("_")[0]))


def structure(mask: np.ndarray) -> dict:
    """Does this region have graphics INSIDE it, or is it one solid shape?

    The question the decision turns on. A mark whose mask is solid can only ever
    be drawn as a filled region -- the tracer cuts an outer ring and keeps no
    islands, so a wordmark inside it is not reproducible from this data even in
    principle. A mask with islands is carrying internal structure.

    `islands` counts enclosed regions; `solid_frac` is the mask's own area over
    its area with holes filled, so 1.0 means nothing is enclosed.
    """
    from scipy.ndimage import binary_fill_holes, label as ndlabel
    filled = binary_fill_holes(mask)
    area, full = int(mask.sum()), int(filled.sum())
    return {"islands": int(ndlabel(filled & ~mask)[1]),
            "solid_frac": round(area / full, 4) if full else 0.0,
            "area_px": area}


def _crop(face: Image.Image, mask: np.ndarray) -> tuple[Image.Image, Image.Image] | None:
    """The mask's neighbourhood, plain and tinted, both enlarged the same way."""
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return None
    h, w = mask.shape
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    pad = int(round(PAD_FRAC * max(y1 - y0, x1 - x0))) + 4
    y0, y1 = max(0, y0 - pad), min(h, y1 + pad)
    x0, x1 = max(0, x0 - pad), min(w, x1 + pad)

    plain = face.crop((x0, y0, x1, y1))
    over = np.asarray(plain, dtype=float).copy()
    sub = mask[y0:y1, x0:x1]
    over[sub] = over[sub] * (1 - TINT_ALPHA) + np.array(TINT, dtype=float) * TINT_ALPHA
    tinted = Image.fromarray(over.round().clip(0, 255).astype("uint8"), "RGB")

    scale = CROP_LONG_EDGE / max(plain.width, plain.height)
    size = (max(1, int(plain.width * scale)), max(1, int(plain.height * scale)))
    resample = Image.NEAREST if scale >= 1 else Image.LANCZOS
    return plain.resize(size, resample), tinted.resize(size, resample)


def _sheet(pairs: list, title: str) -> Image.Image:
    """One row per entry: plain crop, tinted crop, and the key beside them."""
    gap, label_w = 10, 300
    row_h = max((p[1].height for p in pairs), default=1)
    cell_w = max((p[1].width for p in pairs), default=1)
    width = label_w + 2 * cell_w + 4 * gap
    height = 34 + len(pairs) * (row_h + gap) + gap
    sheet = Image.new("RGB", (width, height), (250, 250, 248))
    d = ImageDraw.Draw(sheet)
    d.text((gap, 10), title, fill=(20, 22, 20))
    y = 34
    for key, plain, tinted, note in pairs:
        sheet.paste(plain, (label_w + gap, y))
        sheet.paste(tinted, (label_w + 2 * gap + cell_w, y))
        d.text((gap, y + 4), key, fill=(20, 22, 20))
        d.text((gap, y + 20), note[:46], fill=(110, 120, 116))
        d.text((gap, y + 36), note[46:92], fill=(110, 120, 116))
        y += row_h + gap
    return sheet


def collect(folder: Path) -> list:
    """Every `mark` component and live `mark` hole of one folder, as crops."""
    truth = load_truth(folder)
    if truth is None:
        return []
    comp_class = {c["key"]: c.get("class") for c in truth["components"]}
    comp_reason = {c["key"]: c.get("reason", "") for c in truth["components"]}
    hole_rows = {h["key"]: h for h in (truth.get("holes") or [])}
    wanted_comp = {k for k, v in comp_class.items() if v == MARK}
    wanted_hole = {k for k, h in hole_rows.items()
                   if h.get("class") == MARK and not h.get("vanished")}
    if not wanted_comp and not wanted_hole:
        return []

    flat, labels, named, meta, source = segment(folder)
    w, h = flat.width, flat.height
    lab = labels.reshape(h, w)
    face = flat.convert("RGB")
    min_region = int(float(truth["enumerate_min_frac"]) * w * h)
    min_hole = int(MIN_HOLE_FRAC * w * h)
    order = [(role, named[role]["label"]) for role in sorted(named)
             if role != "substrate" and named.get(role) is not None]

    out = []
    for role, j in order:
        for i, part in enumerate(components(lab == j, min_region)):
            key = f"{role}#{i}"
            if key in wanted_comp:
                got = _crop(face, part)
                if got:
                    out.append((key, got[0], got[1], comp_reason.get(key, ""),
                                "component", float(part.sum()) / (w * h) * 100,
                                structure(part)))
            if comp_class.get(key) != "print":
                continue
            for jj, hole in enumerate(enclosed_background(part)):
                if hole.sum() < min_hole:
                    continue
                hkey = f"{key}/hole#{jj}"
                if hkey not in wanted_hole:
                    continue
                got = _crop(face, hole)
                if got:
                    out.append((hkey, got[0], got[1],
                                hole_rows[hkey].get("reason", ""), "hole",
                                float(hole.sum()) / (w * h) * 100,
                                structure(hole)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--folder", action="append")
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []

    for name in (args.folder or FOLDERS):
        folder = TEMPLATES_DIR / name
        if not (folder / "print_truth.json").exists():
            continue
        rows = collect(folder)
        if not rows:
            continue
        pairs = [(k, p, t, r) for k, p, t, r, _kind, _a, _st in rows]
        sheet = _sheet(pairs, f"{name} — {len(rows)} mark entries "
                              f"(left: as photographed, right: classified pixels tinted)")
        sheet_path = out_dir / f"{name}.png"
        sheet.save(sheet_path)
        for k, _p, _t, reason, kind, area, st in rows:
            index.append({"folder": name, "key": k, "kind": kind,
                          "area_pct": round(area, 4), "reason": reason,
                          "islands": st["islands"], "solid_frac": st["solid_frac"],
                          "area_px": st["area_px"], "sheet": sheet_path.name})
        print(f"{name:<24}{len(rows):>3} entries -> {sheet_path.name}")

    (out_dir / "index.json").write_text(
        json.dumps({"schema": "mark_evidence/1", "entries": index}, indent=2,
                   ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(index)} entries across "
          f"{len({e['folder'] for e in index})} folders -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
