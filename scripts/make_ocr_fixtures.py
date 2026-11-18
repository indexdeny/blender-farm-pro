"""Build the committed OCR fixture set from the current renders.

The barrier that proves label text reaches pixels ran on ONE SKU, `1-min`, and
the audit named that the weakest point in the product's headline claim: "a text
object draws the string it is handed or nothing at all" was verified on 1 of
391. This script builds the fixture set for the reference-template sample so the
same barrier can run over eleven.

    python scripts/make_ocr_fixtures.py            # rebuild every fixture
    python scripts/make_ocr_fixtures.py --check    # report drift, write nothing

Fixtures are full-resolution WEBP rather than PNG. The render itself is 2.8 MB
and twenty-nine of those do not belong in a repository that deliberately tracks
no renders; the same frame as WEBP is a fraction of that, and it keeps the deskew
step real — the view sidecar's corners are in render pixels and still apply, so
the fixture exercises the whole path instead of a pre-flattened crop. It is also
the format Stage 3 delivers.

**Lossless, and every lossy quality was measured failing.** The whole point of
the fixture is that it reads the same as the render it came from, and that is a
property of libwebp rather than of anything this project controls -- so it is
re-measured whenever the pixels change, over the sample's 112 rows.

At contract 1.9 `62_Cialis_Super_Active`'s badge moved a few levels and took its
unit count across Tesseract's decision boundary: q92 disagreed with the PNG on
exactly one row and q98 on none, so the set was written at 98.

**Contract 1.10 falsified that.** Drawing the approved marks put three rows on
the boundary and q98 disagrees on all three, in BOTH directions -- `230-min`'s
ingredient and `357-min`'s brand are read by the PNG and lost by the encode,
while `357-min`'s ingredient is missed by the PNG and RECOVERED by it. Raising
quality does not help and is not the dial: q100 disagrees on three as well, a
DIFFERENT three (`365-min` enters, `230-min` leaves). Lossless disagrees on none.

The cost is stated because it is large: 2.82 MB at q98 against **31.97 MB**
lossless, an 11.3x set in a repository that deliberately tracks no renders.
It is paid for the one property this fixture set may claim -- that the barrier's
verdict is about the RENDER and not about the codec. Three rows in 112 is 2.7%
of the barrier, and two of the three are `357_Adderall`, whose face is the
smallest in the group and enlarged 8.21x.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import load_config, resolve_path  # noqa: E402

# The sample lives in src/design_group.py, which the manifest builder also reads.
# It was defined here first; keeping a second copy beside the one Stage 1 uses is
# the duplicate-source-of-truth this project has already been bitten by twice.
from src.design_group import TEMPLATE_SAMPLE  # noqa: E402,F401

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "ocr"
#: Lossless. See this module's docstring: at contract 1.10 every lossy quality
#: measured disagrees with the PNG on three of the sample's 112 rows, and a
#: fixture that reads differently from its own render cannot stand in for it.
WEBP_LOSSLESS = True

#: The 29th fixture, and it is here because it was NOT and drifted.
#: `TestOCRBarrier` reads `1-min` -- the single-SKU barrier the sample was built
#: to widen -- and nothing rebuilt it, so while the 28 were regenerated at
#: contract 1.6 that one stayed at **1.3**: three contracts back, from before
#: `product_code` existed, showing a carton with an image filename printed under
#: its barcode. A fixture maintained by hand is a fixture nobody maintains.
EXTRA_STEMS = ("1-min",)

#: Kept as PNG rather than WEBP because `TestOCRBarrier` skips itself unless
#: `1-min.png` exists, and the skip would be silent. It costs 3 MB against the
#: 28 sample fixtures' 2 MB together, which is the argument in this module's
#: docstring pointing the other way -- so it is a deliberate exception, not an
#: oversight, and converting it means changing that test's fixture name too.
PNG_STEMS = frozenset({"1-min"})

_CFG = load_config()
RENDER_DIR = resolve_path(_CFG["blender"]["output_dir"])
MANIFEST_DIR = resolve_path(_CFG["paths"]["passports_manifests"])


def sample_stems() -> list[str]:
    """The sample's SKU stems, in catalogue order."""
    return sorted(set(TEMPLATE_SAMPLE.values()),
                  key=lambda s: int(s.split("-")[0]))


def all_stems() -> list[str]:
    """Every stem this module owns: the sample plus `1-min`.

    Kept separate from `sample_stems()` because the barrier tests index the
    SAMPLE by it and `1-min` is not in the sample -- it is the SKU the sample was
    built to widen past.
    """
    return sorted(set(sample_stems()) | set(EXTRA_STEMS),
                  key=lambda s: int(s.split("-")[0]))


def build(stem: str, check_only: bool) -> str:
    from PIL import Image

    png = RENDER_DIR / f"{stem}.png"
    view = png.with_suffix(".view.json")
    manifest = MANIFEST_DIR / f"{stem}.json"
    for required in (png, view, manifest):
        if not required.exists():
            return f"MISSING {required}"

    as_png = stem in PNG_STEMS
    webp_out = FIXTURE_DIR / (f"{stem}.png" if as_png else f"{stem}.webp")
    if check_only:
        return "present" if webp_out.exists() else "ABSENT"

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    if as_png:
        shutil.copy2(png, webp_out)
    else:
        Image.open(png).save(webp_out, "WEBP", lossless=WEBP_LOSSLESS, method=6)
    shutil.copy2(view, FIXTURE_DIR / f"{stem}.view.json")
    # The manifest travels WITH the fixture rather than being read from
    # 04_passports/: the barrier's subject is whether these pixels show the
    # strings the renderer was handed, and re-reading a manifest that has since
    # been regenerated would compare the render against a contract it never saw.
    shutil.copy2(manifest, FIXTURE_DIR / f"{stem}.manifest.json")
    return f"{webp_out.stat().st_size / 1024:.0f} KB"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true",
                   help="report which fixtures exist; write nothing")
    args = p.parse_args()

    stems = all_stems()
    print(f"[fixtures] {len(stems)} SKU: {len(sample_stems())} from "
          f"{len(TEMPLATE_SAMPLE)} template folders plus {len(EXTRA_STEMS)}")
    total = 0
    for stem in stems:
        note = build(stem, args.check)
        print(f"  {stem:10s} {note}")
        if note.endswith("KB"):
            total += float(note.split()[0])
    if not args.check:
        print(f"[fixtures] {total / 1024:.2f} MB in {FIXTURE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
