"""
PHARMAGEN PRO — Render QA (OCR Post-Render Quality Assurance)
Version: 2.0 (2026-08-07) — P8.0

PURPOSE:
    Non-blocking diagnostic module. Runs after image generation.
    For each PNG in the processed-images directory, extracts text via OCR
    and cross-references the corresponding RENDER MANIFEST -- the contract
    the renderer actually consumed, not the passport it was built from -- to
    check that each of `label_content.brand_name_display`,
    `active_ingredient_display`, `dosage_display` and `unit_count_display` is
    recognisable in the rendered pixels.

    Deskews the carton's front face first when the renderer left a
    `{stem}.view.json` sidecar (see src/deskew.py): raw OCR on the
    27.5-35 degree rotated carton misses almost everything, so scoring the
    skewed frame would report false failures on correct packshots. Falls
    back to the raw frame, flagged, when no sidecar exists or deskewing
    fails.

    All directories default from config.yaml (--dir, --manifests, --report
    all override it). --dir in particular follows render.engine: the
    blender engine's own output directory when engine is "blender", Gemini's
    raw-render directory otherwise -- the two engines' output is segregated on
    disk, so this script picks the one matching the configured engine rather
    than a single hardcoded folder.

    Outputs a Markdown report to 06_docs/RENDER_QA_REPORT.md by default.
    A diagnostic, never a gate: status is one of OK / WARN / UNAVAILABLE /
    NO_MANIFEST. There is no failing status that blocks the pipeline.

USAGE:
    python scripts/render_qa.py
    python scripts/render_qa.py --dir 02_processing/blender_test_renders
    python scripts/render_qa.py --manifests 04_passports/render_manifests
    python scripts/render_qa.py --limit 20

DEPENDENCIES:
    pip install pytesseract Pillow
    Tesseract binary: https://github.com/UB-Mannheim/tesseract/wiki
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import re
import os
import argparse
from pathlib import Path
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Resolved through the config, not hardcoded: this fork remapped every path onto
# numbered folders, and a stale default does not fail loudly -- it finds no
# images and reports a clean run over nothing.
# `python scripts/render_qa.py` puts scripts/ (not the project root) at
# sys.path[0], so src wouldn't be importable without this -- the same pattern
# scripts/catalogue_sweep.py and scripts/generate_architecture_snapshot.py use.
_SCRIPT_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_ROOT))

from src.utils import load_config, get_path, resolve_path, PROJECT_ROOT  # noqa: E402

_CFG = load_config()
# Source follows the selected engine. Blender writes to its own directory
# precisely so resume and Stage 3 cannot confuse the two engines' output.
_ENGINE = (_CFG.get("render") or {}).get("engine", "gemini")
DEFAULT_PROCESSED_DIR = (resolve_path(_CFG["blender"]["output_dir"])
                         if _ENGINE == "blender"
                         else get_path(_CFG, "renders_raw"))
DEFAULT_MANIFESTS_DIR  = get_path(_CFG, "passports_manifests")
DEFAULT_REPORT_PATH    = PROJECT_ROOT / "06_docs" / "RENDER_QA_REPORT.md"

# Minimum OCR text length to consider extraction valid
MIN_OCR_TEXT_LENGTH = 20

# ─────────────────────────────────────────────────────────────────────────────
# OCR BACKEND
# ─────────────────────────────────────────────────────────────────────────────

_TESSERACT_AVAILABLE = False
_TESSERACT_ERROR = ""

try:
    import pytesseract
    from PIL import Image
    import shutil

    # Quick check if tesseract is in PATH, if not try default Windows paths
    if not shutil.which("tesseract"):
        possible_paths = [
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR" / "tesseract.exe",
            Path(os.environ.get("LocalAppData", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
        ]
        for p in possible_paths:
            if p.exists():
                pytesseract.pytesseract.tesseract_cmd = str(p)
                break

    # Quick sanity check
    pytesseract.get_tesseract_version()
    _TESSERACT_AVAILABLE = True
except ImportError:
    _TESSERACT_ERROR = "pytesseract not installed. Run: pip install pytesseract"
except Exception as e:
    _TESSERACT_ERROR = f"Tesseract binary not found or not configured: {e}"


def extract_text(image) -> tuple[bool, str]:
    """Run OCR on a path or an already-loaded image, in BOTH polarities.

    Returns (success, text_or_error).

    Read twice, as-is and inverted, because a pharmaceutical carton
    REVERSES type out of its dark fields as a matter of normal design --
    Kamagra sets its dosage and unit count white inside a teal field --
    while Tesseract is built for dark type on a light ground. A single
    pass therefore reports a correctly printed row as missing, which is a
    fact about the reader and not about the packshot.

    Measured over the barrier's nine-SKU sample: the inverted pass
    recovers `344-min`'s unit count and costs nothing anywhere else. It
    is a union and not a replacement, so a row that only reads in the
    normal polarity is not traded away for one that only reads inverted.

    It does not rescue every reversed row -- `64-min` still comes back as
    "3 30 Pind" -- because contrast is not the only thing wrong with
    those rows. Those stay in `KNOWN_OCR_MISSES` with their own causes.
    """
    if not _TESSERACT_AVAILABLE:
        return False, _TESSERACT_ERROR
    try:
        # Imported locally on purpose. render_qa.py imports PIL.Image inside the
        # same try block as pytesseract, so on a machine without pytesseract the
        # module-level name never exists -- and isinstance(image, Image.Image)
        # would raise NameError instead of reporting "OCR unavailable".
        from PIL import Image as _Image
        from PIL import ImageOps as _ImageOps
        img = image if isinstance(image, _Image.Image) else _Image.open(image)
        # Use --psm 6 (uniform text block) for better coverage on a label grid
        text = pytesseract.image_to_string(img, config="--psm 6")
        # Converted first: ImageOps.invert refuses RGBA and palette modes,
        # and the fixtures carry both.
        flipped = _ImageOps.invert(img.convert("RGB"))
        text += "\n" + pytesseract.image_to_string(flipped, config="--psm 6")
        return True, text
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────────────
# MANIFEST + VIEW LOADERS
# ─────────────────────────────────────────────────────────────────────────────

def load_manifest(sku_stem: str, manifests_dir: Path) -> dict | None:
    """The render manifest for a SKU -- the contract the renderer consumed.

    Checking against the passport instead would compare the pixels to a
    document the renderer never read; where the two disagree, that is a false
    alarm rather than a finding.
    """
    path = manifests_dir / f"{sku_stem}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_view(image_path: Path) -> dict | None:
    """The renderer's sidecar saying where the printed faces landed."""
    path = image_path.with_suffix(".view.json")
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# QA CHECKS
# ─────────────────────────────────────────────────────────────────────────────

def extract_numeric(s: str) -> str:
    """Extract the first numeric value (including decimals) from a string."""
    m = re.search(r"\d+(?:[.,]\d+)?", s or "")
    return m.group(0).replace(",", ".") if m else ""


# Which manifest fields are checked, and what OCR has to contain for a hit.
# A display string may carry punctuation or a unit the recogniser mangles, so
# each significant token is matched independently -- and tolerant of the
# whitespace/hyphen/percent noise OCR routinely introduces around punctuation
# -- rather than requiring the whole string verbatim.
CHECKED_FIELDS = ("brand_name_display", "active_ingredient_display",
                  "dosage_display", "unit_count_display")


def _respaced_pattern(literal: str) -> str:
    """Escape *literal* into a pattern that tolerates OCR re-spacing AROUND
    its punctuation while keeping its digits glued to one another.

    "0.025%" becomes r"0\\s*\\.\\s*025\\s*%": a space may open either side of
    the '.' and before the '%', because those thin marks are exactly what the
    recogniser re-spaces -- this catalogue's own renders read "0.025%" back as
    "0.025 %" as readily as intact -- but no gap is allowed between '0' and
    '2', or '2' and '5'.

    Refusing a gap between two digits is the whole point. A space between
    digits is evidence of two separate tokens, not of one token respaced: a
    literal "10" permitted to match "1 0" would weld two unrelated
    single-digit values together, which is the same defect this function's
    caller was fixed for, only occurring inside the match instead of at its
    edge. Punctuation carries no such ambiguity -- nothing on these labels
    prints a lone '%' or '.' as a token of its own -- so a gap beside one is
    safe to forgive.
    """
    out, prev = [], ""
    for ch in literal:
        if ch.isspace():
            # Whitespace already IN the expected value marks a place a gap is
            # allowed; it must not force one, since OCR may read the value
            # closed up. Recorded as a non-digit so the next character opens
            # a gap rather than gluing onto the previous digit.
            prev = " "
            continue
        if out and not (prev.isdigit() and ch.isdigit()):
            out.append(r"\s*")
        out.append(re.escape(ch))
        prev = ch
    return "".join(out)


def _digit_bounded_search(literal: str, text: str) -> bool:
    """Is *literal* (digits, optionally with '.', '%') present in *text* on a
    DIGIT boundary, not a \\b WORD boundary?

    '(?<!\\d)40(?!\\d)', never '\\b40\\b'. Every dosage/unit value in this
    catalogue glues its unit straight onto the number ("40mg", "0.025%"),
    and '\\b' cannot separate a digit from a following letter: '0' and 'm'
    are both word characters, so '\\b40\\b' finds no boundary inside "40mg"
    and never matches it, even though "40mg" is right there on the page. A
    digit boundary keeps the property a plain substring match would lose:
    '5' must not match inside '500', nor '10' inside '100'.

    *text* is the OCR text with its ORIGINAL spacing. Tolerating the "0.025 %"
    reading by deleting every space from the text instead -- what this did
    before -- cannot tell a space OCR inserted inside one token from a space
    that was printed between two, and this catalogue prints a dosage directly
    before a unit count: "0.025% 30 Tubes" collapsed to "0.025%30Tubes", where
    the trailing '(?!\\d)' hit the '3' of a different token and rejected a
    value plainly present on the label. The tolerance belongs on the pattern,
    where the literal's own shape says where a gap is plausible (see
    `_respaced_pattern`), not on the text, which cannot know.
    """
    return re.search(rf"(?<!\d){_respaced_pattern(literal)}(?!\d)", text) is not None


def _normalize_alnum(s: str) -> str:
    """Fold *s* down to bare letters and digits, lowercased -- no spaces, no
    punctuation.

    OCR re-spaces and drops punctuation constantly: this catalogue's own
    renders came back "Retin-A" as both a stray-quote glyph in place of the
    hyphen and, just as often, plain respacing ("Retin - A"); "0.025%" comes
    back "0.025 %" as readily as intact. A hyphen or a decimal point is
    exactly the kind of thin mark a scan misses or repositions. Folding both
    the token and the OCR text down to their letters and digits, in order,
    absorbs that formatting noise without weakening what the check is FOR:
    the same letters/digits must still appear contiguously and in the same
    order, so an OCR reading that drops a letter outright -- not just its
    punctuation -- is correctly still a miss.
    """
    return re.sub(r"[^a-z0-9]", "", s.lower())


# Glyph confusion is deliberately NOT folded here, though it costs one real
# field: `135-min` prints "1mg" and Tesseract reads "lmg" -- a lowercase L for
# the digit one, in every page-segmentation mode.
#
# Folding l/i -> 1 and o -> 0 on both sides was tried and measured. It fixes
# nothing, because a dosage like "1mg" is not matched through this function at
# all: `_field_present` routes a leading number down `_digit_bounded_search`,
# against the raw OCR text, precisely so that '5' cannot match inside '500'.
# Teaching THAT path the lookalikes is what would be needed, and it is unsafe:
# with 'l' and 'o' admitted as digits, the "10" of "10 Pills" matches inside
# "Lorazepam" -- a word in this very sample -- at a legitimate word boundary.
#
# So the miss is carried as a known one instead, where a reader can see it:
# tests/test_render_qa.py::TestOCRBarrierOverTheTemplateSample. The barrier's
# real subject survives either way -- it exists to catch INVENTED text, the
# Gemini engine's "Datels", which is whole tokens away from anything in the
# manifest. Glyph-level fidelity is guarded better elsewhere: the scene test
# compares the built text object's `body` byte-for-byte against the manifest,
# so a driver that truly drew a letter L for a 1 fails there, in a check no
# rescan can fool.


# The word/token split used on BOTH sides of a comparison: to cut a manifest
# field into its significant tokens (below, in `_field_present`) and to cut
# OCR text into the "words" `_alnum_word_index` anchors match boundaries to.
# It must be the same pattern on both sides -- a separator the expected-field
# splitter treats as significant ("/", ",", ":", whitespace) but the text-side
# boundary detector does not is exactly how a legitimate match gets rejected:
# this catalogue's own "0.025g/0.025%" and "Caffeine/Ergotamine" values, with
# no space around the "/", round-tripped through mismatched splitters as a
# false regression during this fix's own 391-SKU sweep (see task-7-report.md)
# before the two were unified onto this one pattern. '.', '%' and '-' are kept
# INSIDE a token on purpose, since those are exactly the marks OCR re-spaces
# ("Retin - A", "0.025 %") that this whole branch exists to tolerate.
_TOKEN_SPLIT_RE = r"[^\w.%-]+"


def _alnum_word_index(text: str):
    """Fold *text* to bare letters/digits the same way `_normalize_alnum`
    folds a token, but keep where each original word (split on
    `_TOKEN_SPLIT_RE`, the same pattern that cuts a manifest field into
    tokens) begins and ends in the folded string.

    Returns (flat, starts, ends): `flat` is the lowercased, punctuation-
    stripped concatenation of every word in *text*, words joined with no
    separator; `starts`/`ends` are the sets of offsets into `flat` where an
    original word begins / one-past-ends.

    This exists because a bare `needle in flattened_text` substring check --
    the first version of this fix -- can manufacture a match the text does
    not contain: flattening "foo x yzoo" to "fooxyzoo" and searching for
    "xyz" finds it, spanning the tail of one unrelated word ("x") and the
    head of the next ("yzoo"), even though neither word has anything to do
    with "xyz". A match is only real if it starts where some word starts and
    ends where some word (the same one, or a later one with nothing but
    other complete words in between) ends -- which is exactly the case for
    an OCR reading that broke ONE word into pieces at a space
    ("Cream" -> "Cre am": starts at "Cre"'s start, ends at "am"'s end) and
    exactly NOT the case for two genuinely different, unrelated words that
    happen to spell the needle across their boundary.
    """
    flat_parts = []
    starts, ends = set(), set()
    pos = 0
    for word in re.split(_TOKEN_SPLIT_RE, text):
        # Through _normalize_alnum, not a second copy of its regex. The
        # docstring above says "the same way `_normalize_alnum` folds a token",
        # and until now that was an assertion about two separate
        # implementations. Adding a glyph-confusion table to one of them turned
        # every field in the sample into a miss inside a single edit -- the
        # needle folded and the haystack did not. One function, so the next
        # change to the fold cannot desynchronise them.
        piece = _normalize_alnum(word)
        if not piece:
            continue
        starts.add(pos)
        pos += len(piece)
        ends.add(pos)
        flat_parts.append(piece)
    return "".join(flat_parts), starts, ends


def _token_present(token: str, text: str, text_index) -> bool:
    """Is *token* recognisable in the OCR text?

    A token containing a letter is matched by folding it down to bare
    letters/digits (see `_normalize_alnum`) and searching for that needle in
    *text_index*'s folded text -- but only accepting an occurrence that
    starts and ends on a real word boundary (see `_alnum_word_index`), so
    the match cannot bridge into the middle of an unrelated adjacent word.

    A token that is nothing but digits and punctuation ("0.025%") is matched
    on a digit boundary against *text* as OCR read it, by a pattern that
    tolerates a gap beside the token's own punctuation ("0.025 %") while
    still refusing to let '5' match inside '500' -- see
    `_digit_bounded_search`. Folding it down to bare digits the way a letter
    token is folded would destroy that guarantee ('5' would then match inside
    '500' as freely as inside '5mg').
    """
    if re.search(r"[a-zA-Z]", token):
        flat, starts, ends = text_index
        needle = _normalize_alnum(token)
        if not needle:
            return False
        pos = 0
        while True:
            i = flat.find(needle, pos)
            if i == -1:
                return False
            if i in starts and i + len(needle) in ends:
                return True
            pos = i + 1
    return _digit_bounded_search(token, text)


def _field_present(expected: str, text: str) -> bool:
    """Is *expected* recognisable in *text*?

    A field whose first word is a bare number, possibly with a unit glued on
    ("40mg", "10 Pills"), is checked on that number alone, digit-bounded --
    see `_digit_bounded_search` -- but that is not the WHOLE check: whatever
    comes after that leading number ("Pills" in "30 Pills") still has to be
    found via `_token_present`, the same as any other significant token.
    Reducing the field to its number and stopping there -- what this branch
    used to do -- lets one numeric field satisfy another: 11 of 391 SKU pair
    a `dosage_display` and `unit_count_display` that reduce to the same
    digits ("30mg" / "30 Pills", "20mg" / "20 Pills", ...), e.g. 21-min's
    "30mg" and "30 Pills". Before this fix, `_field_present("30 Pills",
    "... Zolpidem 30mg")` returned True with no "Pills" anywhere in the
    text -- the exact defect this docstring already calls out for the
    brand/ingredient pair, just reached from the numeric path instead of the
    token path. A bare "40mg" has no trailing word, so it is unaffected;
    "10 Pills" additionally requires "Pills" to be found. A remainder too
    SHORT to be a significant token ("30 EA") is checked whole rather than
    dropped -- dropping it left an empty token list, which satisfies `all()`
    and reopened the same collision by a second route. The catalogue's
    shortest unit today is "Pen", exactly at the three-character threshold.

    Otherwise EVERY significant token (length >= 3) must be found, not just
    the longest one and not merely a majority. Both weaker rules were tried
    and both broke on real catalogue data:

    - "longest token wins" is a false-positive trap whenever two checked
      fields share a word -- brand_name_display "Atomoxetine Generic" and
      active_ingredient_display "Atomoxetine" (293 of 391 SKU carry a
      one-word ingredient this pattern repeats for -- e.g. "Colchicine
      Generic" / "Colchicine", "Modafinil Generic" / "Modafinil"): the
      longest token of the brand field IS the ingredient's whole value, so
      the brand field reads "found" purely because the ingredient field put
      it on the page, even though "Generic" was never printed anywhere.
    - "allow one missing token out of N>=3" looks safer but is not: three
      SKU in this catalogue (409-min, 411-min, 412-min) carry a THREE-token
      brand of the same "<ingredient words> Generic" shape --
      "Nandrolone Decanoate Generic" against ingredient "Nandrolone
      Decanoate", "Testosterone Cypionate Generic" against "Testosterone
      Cypionate". Allowing one of three tokens to be missing lets "Generic"
      be the dropped one and still calls the brand found, on exactly the
      same borrowed-from-another-field basis as "longest token wins".
      There is no token-count threshold that is safe for both a 2-token and
      a 3-token instance of the same collision shape.

    What actually needed relaxing was never the token COUNT -- it was how
    forgivingly each individual token is compared, since the false failures
    measured against this catalogue (`Retin-A Cream 0.025%` read back
    "Retin - A Cream 0.025 %", "0.03%" read back "0.03 %") are punctuation
    respacing, not missing words. `_token_present` fixes that directly, but
    doing it by flattening the whole OCR text to one contiguous
    letters-and-digits blob and substring-searching it -- this function's
    first cut -- is itself unsound: it can find a token that spans the tail
    of one word and the head of an unrelated next word ("Xyz" "found" inside
    "foo x yzoo", which contains no "xyz" at all). `_token_present` therefore
    requires a letter-bearing token's match to BEGIN where some original word
    (split on `_TOKEN_SPLIT_RE`, the SAME pattern used to cut *expected* into
    tokens below -- using a looser split for the text side than for the
    expected side is its own bug, caught by this fix's own 391-SKU sweep: a
    field like "0.025g/0.025%" or "Caffeine/Ergotamine" splits into two
    tokens on '/' here, and if the text side only split on whitespace, the
    verbatim "0.025g/0.025%" in the OCR text stayed ONE unsplit word with no
    boundary at the '/', so the legitimately-present first half failed the
    end-boundary check) begins and END where some (possibly later) word
    ends, with nothing but other complete words in between -- true for an
    OCR split of one word into fragments ("Cream" over "Cre am"), false for
    a match that bridges into the middle of a genuinely different word.
    """
    expected = (expected or "").strip()
    if not expected:
        return False
    num = extract_numeric(expected)
    leading = expected.split()[0]
    if num and num == leading.rstrip("mgMG%"):
        if not _digit_bounded_search(num, text):
            return False
        # Whatever follows the leading number ("Pills" in "30 Pills") is a
        # significant token like any other and must still be found -- the
        # number alone is not the whole field.
        remaining = expected[len(leading):].strip()
        text_index = _alnum_word_index(text)
        tokens = [t for t in re.split(_TOKEN_SPLIT_RE, remaining) if len(t) >= 3]
        if remaining and not tokens:
            # A remainder too short to clear the significance filter is still
            # part of the field and still has to be on the page. Letting the
            # empty token list satisfy `all()` below is the same collision one
            # more time: a unit count written "30 EA" would fall back to
            # matching the digits alone, and a "30mg" dosage elsewhere on the
            # page would satisfy it. This is the fallback the general branch
            # already applies; the numeric branch was simply missing it.
            return _token_present(remaining, text, text_index)
        return all(_token_present(t, text, text_index) for t in tokens)
    tokens = [t for t in re.split(_TOKEN_SPLIT_RE, expected) if len(t) >= 3]
    text_index = _alnum_word_index(text)
    if not tokens:
        return _token_present(expected, text, text_index)
    return all(_token_present(t, text, text_index) for t in tokens)


def check_image(image_path: Path, manifest: dict, view: dict | None = None) -> dict:
    """OCR one render and score it against the manifest that produced it.

    Deskews first when the renderer supplied face corners: on a 27.5-35 degree
    carton, raw OCR misses almost everything (measured 2026-08-03), so scoring a
    skewed frame would report false failures on correct packshots.

    Never returns a hard failure. This is a diagnostic; the module's contract is
    that it does not block the pipeline.
    """
    label = (manifest.get("label_content") or {})
    expected = {f: str(label.get(f, "") or "") for f in CHECKED_FIELDS}
    result = {
        "sku": image_path.stem,
        "ocr_ok": False, "ocr_error": "", "deskewed": False,
        "fields": {}, "found": 0,
        "expected": sum(1 for v in expected.values() if v),
        "confidence": None, "status": "UNKNOWN", "flags": [],
    }

    source = image_path
    corners = (view or {}).get("front_face_px")
    if corners:
        try:
            from src.deskew import flatten_face
            source = flatten_face(image_path, corners)
            result["deskewed"] = True
        except Exception as e:
            result["flags"].append(f"deskew failed, reading the raw frame: {e}")
    elif view is None:
        # No {stem}.view.json beside the image at all -- distinct from the
        # branch below, where the sidecar exists but carries no corners.
        # Conflating the two tells an operator to re-render to produce a
        # sidecar that is already sitting there.
        result["flags"].append(
            "no {stem}.view.json; reading the raw frame, where a rotated "
            "carton reads poorly")
    else:
        # The sidecar exists but front_face_px is null -- render_driver.py
        # emits exactly this when _face_corners_px() could not locate the
        # front face. Re-rendering without also fixing that would reproduce
        # the same null.
        result["flags"].append(
            "{stem}.view.json exists but front_face_px is null (the "
            "renderer could not locate the front face); reading the raw "
            "frame, where a rotated carton reads poorly")

    ok, text = extract_text(source)
    result["ocr_ok"] = ok
    if not ok:
        result["ocr_error"] = text
        result["status"] = "UNAVAILABLE"
        result["flags"].append(f"OCR unavailable: {text[:80]}")
        return result

    result["fields"] = {f: _field_present(expected[f], text) if expected[f] else None
                        for f in CHECKED_FIELDS}
    hits = sum(1 for v in result["fields"].values() if v)
    result["found"] = hits
    result["confidence"] = round(hits / result["expected"], 2) if result["expected"] else None

    for field, present in result["fields"].items():
        if present is False:
            result["flags"].append(f"not recognised: {field}={expected[field]!r}")
    if len(text) < MIN_OCR_TEXT_LENGTH:
        result["flags"].append(
            "OCR returned very little text; the image may be blank")
    if result["expected"] == 0:
        # Not reachable through the schema today -- CHECKED_FIELDS are all
        # required -- but check_image is a public entry point, and
        # `hits == result["expected"]` is `0 == 0` for a manifest with an
        # empty label_content. "Nothing to check" must not read as
        # "everything checked out."
        result["flags"].append(
            "label_content has no checkable fields; nothing was verified")
        result["status"] = "WARN"
    else:
        result["status"] = "OK" if hits == result["expected"] else "WARN"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# REPORT WRITER
# ─────────────────────────────────────────────────────────────────────────────

def write_report(results: list[dict], report_path: Path):
    """Write a Markdown QA report."""
    report_path.parent.mkdir(parents=True, exist_ok=True)

    total = len(results)
    by_status = {s: sum(1 for r in results if r["status"] == s)
                 for s in ("OK", "WARN", "UNAVAILABLE", "NO_MANIFEST")}
    scored = [r for r in results if r["confidence"] is not None]
    mean_conf = round(sum(r["confidence"] for r in scored) / len(scored), 3) if scored else None
    raw_frames = [r for r in results if r["ocr_ok"] and not r["deskewed"]]

    lines = [
        "# RENDER QA REPORT",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Diagnostic, never blocking. Checks that each label string the render "
        "manifest specifies is actually READABLE in the rendered pixels — which "
        "`--dump-scene` cannot tell you, since it sees the text object rather "
        "than the image.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Images checked | {total} |",
        f"| All fields read (OK) | {by_status['OK']} |",
        f"| Some field unread (WARN) | {by_status['WARN']} |",
        f"| OCR unavailable | {by_status['UNAVAILABLE']} |",
        f"| No render manifest | {by_status['NO_MANIFEST']} |",
        f"| Mean confidence | {mean_conf if mean_conf is not None else '—'} |",
        "",
    ]

    if not _TESSERACT_AVAILABLE:
        lines += ["> [!WARNING]",
                  f"> Tesseract is not available: {_TESSERACT_ERROR}",
                  "> Install with: winget install --id UB-Mannheim.TesseractOCR",
                  ""]

    if raw_frames:
        lines += [
            "> [!WARNING]",
            f"> {len(raw_frames)} image(s) were read WITHOUT deskewing, having no "
            "`{stem}.view.json` beside them. A rotated carton reads very poorly "
            "raw, so treat those scores as unreliable rather than as findings. "
            "Re-render them to produce the sidecar.",
            "",
        ]

    lines += [
        "## Results",
        "",
        "| SKU | Deskewed | Brand | Ingredient | Dosage | Count | Confidence | Status |",
        "|---|---|---|---|---|---|---:|---|",
    ]
    mark = lambda v: "—" if v is None else ("OK" if v else "MISS")
    for r in results:
        f = r.get("fields") or {}
        conf = "—" if r["confidence"] is None else f"{r['confidence']:.2f}"
        lines.append(
            f"| {r['sku']} | {'yes' if r['deskewed'] else 'RAW'} "
            f"| {mark(f.get('brand_name_display'))} "
            f"| {mark(f.get('active_ingredient_display'))} "
            f"| {mark(f.get('dosage_display'))} "
            f"| {mark(f.get('unit_count_display'))} "
            f"| {conf} | {r['status']} |")

    flagged = [r for r in results if r["flags"]]
    if flagged:
        lines += ["", "## Flagged", ""]
        for r in flagged:
            lines.append(f"### {r['sku']} ({r['status']})")
            lines += [f"- {flag}" for flag in r["flags"]]
            lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[DONE] Report written to: {report_path}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="OCR post-render QA for PharmaGen PRO. Non-blocking diagnostic."
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_PROCESSED_DIR,
        help=f"Directory of processed PNG images (default: {DEFAULT_PROCESSED_DIR})",
    )
    parser.add_argument(
        "--manifests",
        type=Path,
        default=DEFAULT_MANIFESTS_DIR,
        help=f"Directory of render manifests (default: {DEFAULT_MANIFESTS_DIR})",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=f"Output report path (default: {DEFAULT_REPORT_PATH})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of images to check (default: all)",
    )
    parser.add_argument(
        "--stems",
        default=None,
        help="Comma-separated SKU stems to check instead of the whole directory "
             "(e.g. '59-min,135-min'). Errors if any stem has no render.",
    )
    args = parser.parse_args()

    if not _TESSERACT_AVAILABLE:
        print(f"[WARN] {_TESSERACT_ERROR}")
        print("[WARN] Proceeding — report will mark all as UNAVAILABLE.")

    if not args.dir.exists():
        print(f"[WARN] Processed images directory not found: {args.dir}")
        print(f"       No images to check. Writing empty report.")
        write_report([], args.report)
        return

    images = sorted(args.dir.glob("*.png"))
    if not images:
        print(f"[WARN] No PNG files found in {args.dir}")
        write_report([], args.report)
        return

    # --stems narrows to a named set. --limit takes whatever sorts first, which
    # is fine for a smoke check and useless for a sample chosen on purpose: the
    # reference-template group is eleven specific SKU scattered from 59-min to
    # 404-min. A missing stem is an error rather than a silent shortfall, or the
    # report would claim the sample and cover part of it.
    if args.stems:
        wanted = [s.strip() for s in args.stems.split(",") if s.strip()]
        by_stem = {p.stem: p for p in images}
        missing = [s for s in wanted if s not in by_stem]
        if missing:
            print(f"[ERROR] no render for: {', '.join(missing)} (in {args.dir})")
            return 2
        images = [by_stem[s] for s in wanted]

    if args.limit:
        images = images[:args.limit]

    print(f"\n[START] Render QA — checking {len(images)} images in {args.dir}")
    print(f"        OCR backend: {'pytesseract OK' if _TESSERACT_AVAILABLE else 'UNAVAILABLE'}")
    print(f"        Manifests:   {args.manifests}")
    print(f"        Report:      {args.report}\n")

    results = []
    ok_count = 0

    for img_path in images:
        sku_stem = img_path.stem
        manifest = load_manifest(sku_stem, args.manifests)

        if manifest is None:
            result = {"sku": sku_stem, "ocr_ok": False,
                      "ocr_error": "Render manifest not found",
                      "deskewed": False, "fields": {}, "found": 0, "expected": 0,
                      "confidence": None, "status": "NO_MANIFEST",
                      "flags": [f"No manifest at {args.manifests / sku_stem}.json"]}
        else:
            result = check_image(img_path, manifest, load_view(img_path))

        status = result["status"]
        icon = "[OK]       " if status == "OK" else f"[{status}]"
        flags_display = " | ".join(result["flags"][:2]) if result["flags"] else ""
        print(f"  {icon} {sku_stem:20s} {flags_display}")

        if status == "OK":
            ok_count += 1

        results.append(result)

    warn_count = sum(1 for r in results if r["status"] == "WARN")
    unavail_count = sum(1 for r in results if r["status"] == "UNAVAILABLE")
    no_manifest_count = sum(1 for r in results if r["status"] == "NO_MANIFEST")
    print(f"\n  Total: {len(results)} | OK: {ok_count} | WARN: {warn_count} "
          f"| UNAVAILABLE: {unavail_count} | NO_MANIFEST: {no_manifest_count}")
    write_report(results, args.report)


if __name__ == "__main__":
    main()
