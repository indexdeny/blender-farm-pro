"""D-2b — measure where a reference carton sets its type.

    python scripts/measure_type_rows.py --all
    python scripts/measure_type_rows.py --folder 30_T1_Ritalin --preview

Adds a `type_rows` block to each `design_spec.json`: per role, the row's box in
face coordinates, its cap height as a fraction of the face, and its alignment.
The renderer already draws the four strings from the manifest -- what it has
never had is where the real carton puts them, so every design SKU still laid out
on the generic grid fitted to nine AI renders.

WHAT IS MEASURED AND WHAT IS NOT. The strings are NOT taken from the reference.
They are the catalogue's, and they differ: the Ritalin folder photographs a
carton reading "Motiron 10 mg methylphenidathydrochlorid" where the SKU is
Ritalin/Methylphenidate. Copying the reference's words onto our carton would
print another product's name -- the failure the text-as-geometry rule exists to
prevent. Only the GEOMETRY is measured; the words stay the manifest's.

Rows are read with Tesseract's own word boxes rather than a threshold of our
own. Hand-rolled ink masks were tried first and caught the design instead: at an
absolute cut the Cialis olive fields are darker than the threshold, and at a
local-contrast cut the curved field boundaries are the highest-contrast edges on
the face. Tesseract binarises per region and returns boxes; the barrier over
this same sample already proves it reads these faces.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import render_qa  # noqa: E402  — configures tesseract_cmd on import
from scripts.measure_reference_face import TEMPLATES_DIR, segment  # noqa: E402

UPSCALE = 2                 # Tesseract reads small type far better at 2x
MIN_CONF = 40
PSM_MODE = 11               # sparse text. Re-tested against 3, 4, 6 and 12 on
                            # the face that reads worst: they add nothing psm 11
                            # misses and merge Cialis's wordmark with its dosage
                            # into one token. See _preparations for where the
                            # useful variation is.
# Two readings of one word overlap at least this much of the smaller box.
DUPLICATE_OVERLAP = 0.6
# Past this, a word's box is not around the word -- it is around the filled
# shape the word is reversed out of. See ink_within.
BOXED_SHAPE_IOU = 0.9
BOUNDARY_ERODE_PX = 3
MIN_ROW_CHARS = 2           # a row of one glyph is OCR noise, never a label
MIN_BRAND_CHARS = 3
MAX_ROW_FRAC = 0.35         # taller than this is two rows merged, not one
LINE_TOLERANCE = 0.02       # share of face height within which words share a line
# How closely a read must match the string it is identified as before its BOX is
# emitted as a measurement of that string.
#
# `_similar` divides by the longer string, so 0.5 is very nearly the score of a
# box covering HALF what it claims to measure -- and the bar sat exactly there.
# Measured, the three rows that entered at 0.50 covered 47%, 47% and 25% of the
# ink in their own band: Xanax's brand box reads u 0.410-0.823 against a wordmark
# running 0.113-0.822, i.e. the right-hand half of "XANAX", and the renderer duly
# set our brand in the middle of the face. This module already states the rule it
# was breaking -- a label at a wrong measured box is worse than one on the grid,
# because the grid is at least consistent.
#
# 0.6 says "more than half, with room for a misread". It is not fitted to the
# eleven: the next score above 0.50 in the sample is 0.74, so anything in that
# gap gives the same answer. What the evidence fixes is the floor, not the value.
MATCH_MIN = 0.6

DOSAGE_RE = re.compile(r"^\d+([.,]\d+)?\s*(mg|g|ml|mcg|µg|ug)\b", re.I)
COUNT_RE = re.compile(r"^\d+\s*\D{2,}$")
LEADING_NUMBER_RE = re.compile(r"^\D*(\d+)")


def number_conflicts(read: str, want: str) -> bool:
    """Does this reading open with a DIFFERENT number from the one expected?

    A pharmaceutical pack says the same words twice: once in the composition
    block and once as the unit count. Lexotanil's composition line reads
    "1 comprimé quadrisécable" and its unit count "30 comprimés quadrisécables"
    -- 0.74 on bigrams, comfortably past any similarity bar -- so the reader
    measured the composition line in the middle of the pack and the renderer set
    "30 Pills" there.

    The number is the one part of a count that IS the content, and a count that
    says 1 is not a count that says 30. Note what this does NOT reject: a reading
    that merely lost the number, like Viagra's "film-coated tablets" for "4
    film-coated tablets". That is an incomplete read of the right line rather
    than evidence of a different one, and rejecting it would cost a good row to
    fix a bad one. Fires once across the eleven.
    """
    w = LEADING_NUMBER_RE.match(want)
    r = LEADING_NUMBER_RE.match(read)
    return bool(w and r and w.group(1) != r.group(1))


def _preparations(img: Image.Image):
    """The same face, prepared for the reader three ways.

    One pass is not enough, and the failure is per carton rather than per
    project. `02_T1_SMALL_Cialis` is the case: a face with five perfectly legible
    lines returned FOUR words and not one of its labels, because braille dots are
    embossed straight across the wordmark and the type sits dark-on-cream at low
    contrast. Each preparation recovers something the others miss -- unsharp
    masking finds its "10 mg", a contrast stretch finds "tadalafil" -- and none
    of them finds everything.

    Merging PAGE-SEGMENTATION modes was tried instead and is not worth it: psm
    3, 4 and 6 return Cialis's wordmark and dosage run together as one token
    ("‘ialistem"), which is a worse box than no box. The variation that helps is
    in the pixels, not in the layout analysis.

    This is the same move `type_qa.read_rows` makes when it reads our own face
    upright and inverted, for the same reason: a reader that binarises per region
    gives different answers to different preparations of one image, and the union
    is strictly more than any single pass.
    """
    grey = img.convert("L")
    return (img,
            grey.filter(ImageFilter.UnsharpMask(radius=3, percent=200)),
            ImageEnhance.Contrast(grey).enhance(2.5))


def _duplicate(box, kept_box) -> bool:
    """Is this the same word already found, read again by another preparation?

    Containment rather than IoU. Two preparations return the same word at
    slightly different extents -- one clips a serif, the other includes a stray
    mark -- and an intersection-over-union test at any sane threshold lets both
    through: Modafinil's ingredient came back as the row "Modaftin! afin!",
    which is one word counted twice.
    """
    ix = max(0.0, min(box[0] + box[2], kept_box[0] + kept_box[2]) - max(box[0], kept_box[0]))
    iy = max(0.0, min(box[1] + box[3], kept_box[1] + kept_box[3]) - max(box[1], kept_box[1]))
    inter = ix * iy
    smaller = min(box[2] * box[3], kept_box[2] * kept_box[3])
    return bool(inter and smaller and inter / smaller >= DUPLICATE_OVERLAP)


def _words(img: Image.Image):
    """Every word Tesseract finds, across preparations of the face."""
    import pytesseract

    w, h = img.size
    found = []
    for prep in _preparations(img):
        big = prep.resize((w * UPSCALE, h * UPSCALE), Image.LANCZOS)
        d = pytesseract.image_to_data(big, config=f"--psm {PSM_MODE}",
                                      output_type=pytesseract.Output.DICT)
        _collect(d, found)
    return found


def _collect(d, found):
    """Add this pass's words to *found*, keeping the fuller read of a duplicate."""
    for i, raw in enumerate(d["text"]):
        text = raw.strip()
        if not text or int(d["conf"][i]) < MIN_CONF:
            continue
        box = (d["left"][i] / UPSCALE, d["top"][i] / UPSCALE,
               d["width"][i] / UPSCALE, d["height"][i] / UPSCALE)
        if box[2] <= 0 or box[3] <= 0:
            continue
        for j, (kbox, ktext, _kconf) in enumerate(found):
            if _duplicate(box, kbox):
                if len(_alnum(text)) > len(_alnum(ktext)):
                    found[j] = (box, text, int(d["conf"][i]))
                break
        else:
            found.append((box, text, int(d["conf"][i])))
    return found


def _lines(words, w, h):
    """Group words into rows by vertical centre."""
    rows = []
    for box, text, conf in sorted(words, key=lambda t: t[0][1]):
        cy = (box[1] + box[3] / 2) / h
        for row in rows:
            if abs(row["cy"] - cy) <= LINE_TOLERANCE:
                row["words"].append((box, text, conf))
                row["cy"] = sum((b[1] + b[3] / 2) / h for b, _, _ in row["words"]) / len(row["words"])
                break
        else:
            rows.append({"cy": cy, "words": [(box, text, conf)]})

    out = []
    for row in rows:
        boxes = [b for b, _, _ in row["words"]]
        x0 = min(b[0] for b in boxes); x1 = max(b[0] + b[2] for b in boxes)
        y0 = min(b[1] for b in boxes); y1 = max(b[1] + b[3] for b in boxes)
        out.append({
            "text": " ".join(t for _, t, _ in sorted(row["words"], key=lambda t: t[0][0])),
            "u0": round(x0 / w, 4), "u1": round(x1 / w, 4),
            "v0": round(y0 / h, 4), "v1": round(y1 / h, 4),
            "cap_frac": round((y1 - y0) / h, 4),
            # The words kept alongside the row they were grouped into. A row is
            # the right unit for identifying a label and the wrong one for
            # measuring where a single string sits: the bottom row of a pack
            # carries the dosage at one end and the unit count at the other, on
            # one baseline and touching nowhere, and its box is the whole face
            # wide. `type_qa` narrows a row back to the words that spell the
            # string it is asking about. Nothing in the spec this module writes
            # is built from these.
            "words": [
                {"text": t,
                 "u0": round(b[0] / w, 4), "u1": round((b[0] + b[2]) / w, 4),
                 "v0": round(b[1] / h, 4), "v1": round((b[1] + b[3]) / h, 4)}
                for b, t, _ in sorted(row["words"], key=lambda t: t[0][0])],
        })
    return sorted(out, key=lambda r: r["v0"])


def _alnum(text: str) -> str:
    return re.sub(r"[^0-9A-Za-zÀ-ÿ]", "", text)


def usable(row, min_chars=MIN_ROW_CHARS) -> bool:
    """Is this row a label at all?

    Two rejections, both earned: a row of one glyph is OCR finding a mark in the
    artwork -- a red warning triangle came back as "A" and a hologram's edge as
    "¢" -- and a row taller than a third of the face is several lines that the
    grouping ran together, not one row with a huge cap height.
    """
    return (len(_alnum(row["text"])) >= min_chars
            and row["cap_frac"] <= MAX_ROW_FRAC)


def _similar(a: str, b: str) -> float:
    """Crude character-bigram overlap. Enough to match OCR against a known word."""
    a, b = _alnum(a).lower(), _alnum(b).lower()
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a and a == b else 0.0
    A = {a[i:i + 2] for i in range(len(a) - 1)}
    B = {b[i:i + 2] for i in range(len(b) - 1)}
    # Divided by the LONGER string, so a fragment cannot pass as the whole. With
    # the shorter one in the denominator, "tablets" scored 1.0 against "4
    # film-coated tablets" and Cialis's top line was emitted as its ingredient
    # row -- a measured box in the wrong place, which is worse than no box.
    return len(A & B) / max(1, len(A), len(B))


FONT_DIR = PROJECT_ROOT / "05_assets" / "blender" / "fonts"
# Which face the driver sets each role in. Restated rather than imported: the
# driver only imports under Blender's own interpreter.
BOLD_ROLES = {"brand_name_display", "dosage_display"}
_PROFILE_CACHE: dict[tuple, tuple] = {}


def ink_profile(role: str, text: str) -> tuple[float, float]:
    """A string's ink box in CAP heights: (height, how far its top sits above cap).

    An OCR box is the extent of the GLYPHS -- ascenders above the cap line,
    descenders below the baseline -- and how much of it is cap height depends
    entirely on which letters the string happens to carry. Measured over the
    twenty reference rows this sample measures, that ratio runs **1.034 to
    1.384**: "ALPRAZOLAM" is all caps and its ink IS its cap height, while
    "Lorazepam Orion" descends and its box is a third taller.

    A PROXY, and worth naming as one. The reference's own typeface is unknown
    and unknowable from a photograph, so the profile is taken in the face this
    project actually prints in. What it is really measuring is which CATEGORIES
    of glyph the string contains -- has-cap, has-ascender, has-descender -- and
    those move together across sans-serif faces even where the exact ratios do
    not.
    """
    from PIL import ImageFont
    key = (role in BOLD_ROLES, text)
    if key not in _PROFILE_CACHE:
        path = FONT_DIR / ("DejaVuSans-Bold.ttf" if key[0] else "DejaVuSans.ttf")
        font = ImageFont.truetype(str(path), 200)
        cap = font.getbbox("H")
        cap_h = cap[3] - cap[1]
        box = font.getbbox(text)
        height = box[3] - box[1]
        _PROFILE_CACHE[key] = ((height / cap_h, (cap[1] - box[1]) / cap_h)
                               if height > 0 and cap_h > 0 else (1.0, 0.0))
    return _PROFILE_CACHE[key]


def _box_iou(a: dict, b: tuple) -> float:
    x0 = max(a["u0"], b[0]); x1 = min(a["u1"], b[1])
    y0 = max(a["v0"], b[2]); y1 = min(a["v1"], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    union = ((a["u1"] - a["u0"]) * (a["v1"] - a["v0"])
             + (b[1] - b[0]) * (b[3] - b[2]) - inter)
    return inter / union if union > 0 else 0.0


def ink_within(face, row: dict, parts) -> dict:
    """A row's real ink box where the reader boxed a filled SHAPE instead.

    Tesseract binarises per region, and a colour block with type reversed out of
    it is one blob: the word box comes back as the BLOCK. Measured on our own
    Cialis render, "20mg" was returned at exactly the block's outline --
    v 0.2948-0.4292 against glyphs at 0.3165-0.4133 -- which reads back as a row
    38% oversized and 0.02 high, the worst figures in the group on a carton the
    scene dump says is built exactly right.

    Two things keep this from being a licence to shrink any box. It fires only
    where the box IS the shape, and it measures inside the shape's own polygon
    ERODED clear of its boundary: simply taking the ink inside the returned box
    recovers nothing, because a sliver of board along the box's edge is as far
    from the fill as the white glyphs are and spans the full height.

    `parts` is [(fill_hex, outline, holes)] in face coordinates, passed by both
    readers. The holes are cut out of the mask for the same reason the driver
    cuts them out of the curve: a hole is board, and ink found in one belongs to
    whatever shows through, not to this shape.
    It does not fire on the photographs -- a printed block's edge is soft enough
    that Tesseract boxes the glyphs there, which is why the reference's own
    Cialis dosage was measured at 0.3158-0.4133 all along.
    """
    if not parts:
        return row
    import numpy as np
    from PIL import ImageDraw

    for fill, outline, holes in parts:
        us = [float(q[0]) for q in outline]
        vs = [float(q[1]) for q in outline]
        if _box_iou(row, (min(us), max(us), min(vs), max(vs))) < BOXED_SHAPE_IOU:
            continue
        w, h = face.size
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        draw.polygon([(u * w, v * h) for u, v in outline], fill=255)
        for ring in holes or ():
            if len(ring) >= 3:
                draw.polygon([(u * w, v * h) for u, v in ring], fill=0)
        for _ in range(BOUNDARY_ERODE_PX):
            mask = mask.filter(ImageFilter.MinFilter(3))
        inside = np.asarray(mask) > 0
        if inside.sum() < 100:
            continue
        hx = (fill or "#000000").lstrip("#")
        rgb = np.array([int(hx[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])
        arr = np.asarray(face.convert("RGB")).astype(float) / 255.0
        dist = np.linalg.norm(arr - rgb, axis=-1)
        ink = inside & (dist > 0.5 * dist[inside].max())
        ys, xs = np.nonzero(ink)
        if not len(ys):
            continue
        box = {"u0": round(float(xs.min()) / w, 4),
               "u1": round(float(xs.max() + 1) / w, 4),
               "v0": round(float(ys.min()) / h, 4),
               "v1": round(float(ys.max() + 1) / h, 4)}
        # The WORDS have to come with it. Everything downstream rebuilds a row
        # from them -- `_unclaimed` before scoring, `narrow_to_string` inside it
        # -- so leaving the reader's word boxes in place quietly restores the
        # block's own rectangle and the correction never reaches the figures.
        # Inside a filled shape there is one label and no per-word extent worth
        # keeping, so it becomes one word carrying the row's text.
        return {**row, **box,
                "cap_frac": round(box["v1"] - box["v0"], 4),
                "words": [{"text": row["text"], **box}]}
    return row


def _word_key(word: dict) -> tuple:
    return (word["u0"], word["u1"], word["v0"], word["v1"])


def _row_from_words(words: list[dict]) -> dict:
    v0, v1 = min(w["v0"] for w in words), max(w["v1"] for w in words)
    return {"text": " ".join(w["text"] for w in words),
            "u0": min(w["u0"] for w in words), "u1": max(w["u1"] for w in words),
            "v0": v0, "v1": v1, "cap_frac": round(v1 - v0, 4),
            "words": words}


def narrow_to_string(row: dict, want: str) -> dict:
    """Trim a row to the words that spell the string being asked about.

    A row is the right unit for IDENTIFYING a label and the wrong one for
    MEASURING it, because the reader groups words by vertical centre and a
    carton sets several labels on one line. Measured across the eleven, three
    reference rows came back wider than the string they were matched to:
    "0,5 mg ALPRAZOLAMUM" for Alprazolam, "Sildenafil Citrate Tablets" for
    Sildenafil Citrate, "50 mg film-coated tablets" for 4 film-coated tablets.
    Every one of those boxes then placed our own row across two of the
    reference's.

    Only ever narrows, and only when narrowing reads CLOSER to the string asked
    about, so a row that is already one label is returned untouched.
    """
    words = row.get("words") or []
    if len(words) < 2 or not want:
        return row
    best, score = words, _similar(row["text"], want)
    for i in range(len(words)):
        for j in range(i + 1, len(words) + 1):
            run = words[i:j]
            sc = _similar(" ".join(w["text"] for w in run), want)
            # A shorter run at the SAME score is the tighter measurement, and the
            # tie is not hypothetical: `_similar` compares alphanumerics only, so
            # trailing marks cost a reading nothing while widening its box.
            # Kamagra's dosage came back as the row "100mg ~“ | |", scoring a
            # clean 1.00 over a box a sixth of the face wider than the type in it.
            if sc > score or (sc == score and len(run) < len(best)):
                best, score = run, sc
    return row if len(best) == len(words) else _row_from_words(best)


def assign_roles(rows, expected: dict | None = None) -> dict:
    """Which measured row is the brand, the dosage, the ingredient, the count.

    Matched against the REFERENCE's own strings, which D-1 recorded in each
    folder's metadata. Assigning by structure alone -- tallest row is the brand,
    a number with a unit is the dosage -- was tried and reaches about half: it
    made "tablets" the Cialis brand, "sildenafil" the Viagra one and "nil" the
    Modafinil one, because on a photograph the largest wordmark is often the
    hardest thing to read cleanly.

    Those strings identify rows; they are never printed. The renderer draws the
    manifest's words, and the two differ on four of the eleven -- Motiron for
    Ritalin, Aspendos for Modafinil, Lorazepam Orion for Ativan, Zopiclone
    Actavis for Imovane.
    """
    taken, roles, matched, boxes = set(), {}, set(), {}
    rows = [r for r in rows if usable(r)]
    # Words already claimed by a role, not rows. Once a box is narrowed to the
    # words that spell its string, a row can legitimately serve two roles -- the
    # bottom band of a pack carries the dosage at one end and the unit count at
    # the other. Claiming the whole row cost Viagra exactly that: the dosage
    # matched "50 mg" out of "50 mg film-coated tablets" at 1.00 and took the
    # count's words with it.
    claimed: set[tuple] = set()

    def _unclaimed(row):
        words = [w for w in (row.get("words") or []) if _word_key(w) not in claimed]
        if not row.get("words"):
            return row
        return _row_from_words(words) if words else None

    if expected:
        for role, want in expected.items():
            if not want:
                continue
            # If the expected string opens with a number and the face shows that
            # number ANYWHERE, the row carrying it is the row. Reading more of
            # the face made this bite: with three preparations the reader finds
            # Lexotanil's form line "comprimé quadrisécable" near the top, which
            # scores 0.78 against "30 comprimés quadrisécables" while the real
            # count sits at the foot of the pack wrapped over two lines and can
            # never score that high.
            #
            # Only when the number IS somewhere. Viagra's count reads "4
            # film-coated tablets" on one preparation and loses the "4" on
            # another; if no candidate has it, a numberless read is the best
            # available and is taken.
            wanted = LEADING_NUMBER_RE.match(want)
            digits = wanted.group(1) if wanted else None
            if digits and not any(digits in r["text"] for r in rows):
                digits = None
            best, score, box = None, 0.0, None
            for i, r in enumerate(rows):
                if i in taken:
                    continue
                free = _unclaimed(r)
                if free is None:
                    continue
                candidate = narrow_to_string(free, want)
                if number_conflicts(candidate["text"], want):
                    continue
                if digits and digits not in candidate["text"]:
                    continue
                sc = _similar(candidate["text"], want)
                if sc > score:
                    best, score, box = i, sc, candidate
            if best is not None and score >= MATCH_MIN:
                roles[role] = best
                boxes[role] = box
                matched.add(role)
                claimed |= {_word_key(w) for w in (box.get("words") or [])}
                if not box.get("words"):
                    taken.add(best)

    for i, r in enumerate(rows):
        if DOSAGE_RE.match(r["text"]) and "dosage_display" not in roles:
            roles["dosage_display"] = i
            taken.add(i)
    for i, r in enumerate(rows):
        if i in taken:
            continue
        if COUNT_RE.match(r["text"]) and "unit_count_display" not in roles:
            roles["unit_count_display"] = i
            taken.add(i)

    rest = [i for i in range(len(rows))
            if i not in taken and usable(rows[i], MIN_BRAND_CHARS)]
    if rest and "brand_name_display" not in roles:
        brand = max(rest, key=lambda i: rows[i]["cap_frac"])
        roles["brand_name_display"] = brand
        taken.add(brand)
        rest = [i for i in rest if i != brand]
    if rest and "active_ingredient_display" not in roles:
        below = [i for i in rest if rows[i]["v0"] > rows[roles["brand_name_display"]]["v0"]] \
            if "brand_name_display" in roles else rest
        pool = below or rest
        roles["active_ingredient_display"] = max(
            pool, key=lambda i: len(re.sub(r"[^A-Za-zÀ-ÿ]", "", rows[i]["text"])))
    return roles, matched, boxes


def measure(folder: Path, preview: bool = False) -> dict:
    flat, _labels, _named, _meta, _src = segment(folder)
    w, h = flat.size
    # The fitted fields, so a row the reader boxed as a filled SHAPE can be
    # measured on its glyphs instead. `fit_design_spec` runs before this and
    # writes them into the same file. It does not fire on any of the eleven
    # photographs -- a printed block's edge is soft enough that Tesseract boxes
    # the glyphs -- and it is passed anyway so both readers run the same code.
    spec_path = folder / "design_spec.json"
    fitted = json.loads(spec_path.read_text(encoding="utf-8")) if spec_path.exists() else {}
    parts = [(f.get("fill"), p["outline"], p.get("holes") or [])
             for f in (fitted.get("fields") or []) for p in (f.get("parts") or [])
             if len(p.get("outline") or []) >= 3]
    rows = [ink_within(flat, r, parts)
            for r in _lines(_words(flat), w, h) if usable(r)]
    lc = (_meta.get("label_content") or {})
    expected = {
        "brand_name_display": lc.get("brand_name_display"),
        "active_ingredient_display": _meta.get("active_ingredient"),
        "dosage_display": lc.get("dosage_display"),
        "unit_count_display": lc.get("unit_count_display"),
    }
    roles, matched, boxes = assign_roles(rows, expected)
    # Only rows identified BY TEXT are emitted. The structural fallback -- tallest
    # row is the brand -- is what put "tablets" on Cialis and "nil" on Modafinil,
    # and a label placed at a wrong measured box is worse than one on the generic
    # grid: the grid is at least consistent. Roles that did not match keep the
    # grid, and the count is printed so the coverage is never assumed.
    roles = {r: i for r, i in roles.items() if r in matched}

    out = {}
    for role in roles:
        r = boxes[role]
        centre = 0.5 * (r["u0"] + r["u1"])
        # The box is ink; the renderer needs CAP HEIGHT, and the two differ by
        # whatever glyphs this string happens to carry. Converting here rather
        # than in the driver keeps the field honest to its name and keeps the
        # font proxy in one place -- the driver would otherwise have to take
        # metrics for a string it never prints.
        ink_h, above_cap = ink_profile(role, r["text"])
        cap_frac = round(r["cap_frac"] / ink_h, 4)
        out[role] = {
            "u0": r["u0"], "u1": r["u1"], "v0": r["v0"], "v1": r["v1"],
            "cap_frac": cap_frac,
            # Where the reference's CAPITALS start, which is what a row is set
            # against. `v0` stays the ink top: it is what the collision guards
            # treat as the row's occupied area, and it is what was measured.
            "cap_top_v": round(r["v0"] + above_cap * cap_frac, 4),
            "align": "LEFT" if centre < 0.45 else ("RIGHT" if centre > 0.62 else "CENTER"),
            "read_as": r["text"],
        }

    spec_path = folder / "design_spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["type_rows"] = out
    spec["type_rows_note"] = (
        "GEOMETRY ONLY. `read_as` records the reference's own words, which are "
        "how each row was identified and are NOT what gets printed: the renderer "
        "draws the manifest's strings. The reference and the catalogue often "
        "carry different products -- Motiron for Ritalin, Aspendos for Modafinil.")
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")

    if preview:
        from PIL import ImageDraw
        img = flat.copy()
        d = ImageDraw.Draw(img)
        for role, r in out.items():
            d.rectangle([r["u0"] * w, r["v0"] * h, r["u1"] * w, r["v1"] * h],
                        outline=(255, 0, 255), width=3)
            d.text((r["u0"] * w, max(0, r["v0"] * h - 12)), role, fill=(255, 0, 255))
        out_dir = PROJECT_ROOT / "02_processing" / "reference_measurement"
        out_dir.mkdir(parents=True, exist_ok=True)
        img.save(out_dir / f"{folder.name}.rows.png")
    return {"rows": len(rows), "roles": out}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--folder")
    p.add_argument("--all", action="store_true")
    p.add_argument("--preview", action="store_true")
    args = p.parse_args()

    if args.folder:
        folders = [TEMPLATES_DIR / args.folder]
    elif args.all:
        from src.design_group import TEMPLATE_SAMPLE
        folders = [TEMPLATES_DIR / n for n in sorted(TEMPLATE_SAMPLE)]
    else:
        p.error("pass --folder NAME or --all")

    for folder in folders:
        r = measure(folder, args.preview)
        got = sorted(r["roles"])
        print(f"{folder.name:32s} rows={r['rows']:3d}  matched {len(got)}/4: "
              f"{', '.join(k.replace('_display', '') for k in got) or 'nothing'}")
        for role, v in r["roles"].items():
            print(f"      {role.replace('_display',''):18s} v{v['v0']:.3f}-{v['v1']:.3f} "
                  f"u{v['u0']:.3f}-{v['u1']:.3f} cap {v['cap_frac']:.3f} "
                  f"{v['align']:6s} <- {v['read_as']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
