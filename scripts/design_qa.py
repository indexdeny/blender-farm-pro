"""D-6 — how far a rendered carton is from the packaging it copies.

    python scripts/design_qa.py                 # measure every design SKU
    python scripts/design_qa.py --sku 59-min --preview

Rectifies our own render with the corners the driver publishes, classifies it
into the design spec's own colours, and compares. Two distances are reported and
kept apart, because they fail for different reasons and one can hide the other:

  spec vs reference   how much of the real carton the spec captured   (D-2)
  render vs spec      how faithfully the renderer built that spec     (D-4)

A high second number with a low first is a renderer building a bad spec
perfectly. The composite -- render against the rectified photograph -- is
reported too, but the two components are what a fix acts on.

Classification is by NEAREST SPEC COLOUR on the illumination-flattened frame,
not by re-clustering. Two independent k-means runs give two partitions with no
guaranteed correspondence, so the clusters would have to be matched up before
anything could be compared, and that matching is exactly where a wrong answer
would hide.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.deskew import flatten_face  # noqa: E402
from src.design_group import FOLDER_BY_STEM, TEMPLATES_DIR, load_design  # noqa: E402
from src.mark_geometry import drawable_mark_parts  # noqa: E402
from src.utils import load_config, resolve_path  # noqa: E402
from scripts.calibrate_render import appearance, load_curve  # noqa: E402
from scripts.measure_reference_face import rectified_face  # noqa: E402
from scripts.fit_design_spec import part_region, rasterise  # noqa: E402
from scripts.design_coverage import spec_index  # noqa: E402
from scripts.measure_reference_face import _flatten_illumination  # noqa: E402

_CFG = load_config()
_BL = _CFG["blender"]
RENDER_DIR = resolve_path(_BL["output_dir"])
MANIFEST_DIR = resolve_path(_CFG["paths"]["passports_manifests"])
PREVIEW_DIR = PROJECT_ROOT / "02_processing" / "reference_measurement"

OUT_WIDTH = 1100
DARK_V = 0.30      # type: ours prints it, the spec does not carry it
# The gradient estimate this comparison uses, as a divisor of the face's long
# edge. Wider than the segmentation's, and deliberately: clustering only asks
# which pixels resemble each other, while this asks how a rendered field compares
# with the colour the driver was told to paint. A narrow estimate follows the
# design itself, so on a carton that is half dark it divides the light half by a
# low local value AND a low global mean -- Kamagra's cream board measured 0.413
# from its own fill on a render that was correct.
FLATTEN_RADIUS_DIV = 2.0

# Two spec colours closer than this cannot be told apart by a nearest-colour
# classifier once a render and a photograph have each added their own noise, so
# the agreement figure stops measuring fidelity and starts measuring which side
# of a coin flip each pixel landed. Modafinil's substrate #A09C9D and highlight
# #A9A5A7 are four levels apart and scored 19.4% against a render that looks
# nearly identical to its spec. A number that cannot discriminate has to say so
# rather than be read as a failure.
SEPARABLE_MIN = 0.08

# Below this, an entry is close enough to the line between two others that the
# boundary between those two averages to it, and a field's precision is decided
# by how much edge the carton has rather than by the render. Set at the gap in
# the evidence: three cartons sit at 0.013-0.017 and the next is 0.064.
ON_LINE_MIN = 0.03


def _hex_rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])


def _front_palette_entries(spec: dict) -> tuple[list[dict], list[tuple[str, str]], list[int]]:
    """Return the palette vocabulary for the front-face instrument only."""
    fields = [field for field in (spec.get("fields") or [])
              if field.get("surface", "front") == "front"]
    entries = [("substrate", spec["substrate"])]
    to_field = [0]
    for n, field in enumerate(fields):
        for colour in dict.fromkeys(part["fill"] for part in field["parts"]):
            entries.append((field["role"], colour))
            to_field.append(n + 1)
    return fields, entries, to_field


def flatten_on_substrate(rgb: np.ndarray, substrate_core: np.ndarray) -> np.ndarray:
    """Divide out the lighting gradient, estimated ONLY where the board is one colour.

    A blur of the whole face cannot separate shading from design. At a narrow
    radius it follows the artwork -- Kamagra's cream measured 0.48 from the fill
    it was painted -- and at a wide one it stops removing the gradient that a
    near-degenerate palette needs removed. Fitting a plane over the SUBSTRATE
    region, which the spec draws and is therefore known exactly, lets no design
    structure into the estimate at all; and a lighting gradient across a flat
    card is very nearly a plane.

    Measured against both blurs, worst colour error: Kamagra 0.482 / 0.252 /
    **0.187**, Imovane 0.133 / 0.091 / **0.060**, and the two cartons with wide
    palettes unchanged at 0.060.
    """
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    lum = rgb.max(-1)
    sel = substrate_core & (lum > 0.05)
    if sel.sum() < 500:
        return _flatten_illumination(rgb, FLATTEN_RADIUS_DIV)
    A = np.stack([xx[sel], yy[sel], np.ones(int(sel.sum()))], 1).astype(float)
    coef, *_ = np.linalg.lstsq(A, lum[sel], rcond=None)
    est = np.maximum(coef[0] * xx + coef[1] * yy + coef[2], 1e-3)
    return np.clip(rgb / est[..., None] * float(est.mean()), 0.0, 1.0)


def _substrate_core(spec_idx: np.ndarray, erode: int = 19) -> np.ndarray:
    """The substrate, eroded clear of its own boundaries."""
    from PIL import ImageFilter
    return np.asarray(
        Image.fromarray(((spec_idx == 0) * 255).astype("uint8"))
        .filter(ImageFilter.MinFilter(erode))) > 0


def _substrate_residual(frame: np.ndarray, core: np.ndarray) -> float:
    """How flat a model left the one surface known to be a single colour.

    The illumination estimate's own error, judged where the answer is not in
    doubt: the spec draws the substrate and states its paint, so anything left
    varying inside it is the model failing, not the carton. Nothing about the
    FIELDS enters, which is what keeps this from being a choice made by looking
    at the result.
    """
    sel = core & (frame.max(-1) >= DARK_V)
    if sel.sum() < 500:
        return float("inf")
    return float(np.linalg.norm(frame[sel].std(axis=0)))


def _nearest(frame: np.ndarray, palette: np.ndarray) -> np.ndarray:
    return ((frame[:, :, None, :] - palette[None, None, :, :]) ** 2).sum(-1).argmin(-1)


def _anchor(frame: np.ndarray, substrate_core: np.ndarray,
            substrate_rgb: np.ndarray) -> np.ndarray:
    """Put the frame on the spec's own level, using the one region it knows.

    The gain is read off the SUBSTRATE, eroded clear of its own edges: the spec
    draws that region and states its paint, so this is a grey card the picture
    actually contains rather than a fitted correction.

    Two jobs, and it has been demoted from the first.

    It was the CLASSIFIER's level fix, and as one point per channel it could
    only ever be a gain. That was enough for Imovane, whose highlight had fallen
    to the substrate side of a boundary a 5% shift had moved past it (85.1% ->
    98.4% when the gain was introduced), and not enough for Kamagra, whose two
    greens are displaced by a LIFT a gain cannot reach. The classifier now
    compares against a measured transfer curve instead -- calibrate_render.py.

    What remains is putting the two illumination candidates on one level so
    `_substrate_residual` compares their flatness rather than their exposure.

    Deliberately NOT applied to `colour_error_by_region`, and the reason has not
    changed: that figure asks whether the renderer painted the colour it was
    told to, and putting the frame on the spec's level is precisely how you
    erase its answer. An earlier attempt put the gain in front of both and was
    reverted for costing Kamagra fourteen points; the lesson was where it
    belongs, not that it is wrong. Note the curve is applied the other way
    round, to the PALETTE, so it cannot be mistaken for correcting the render.
    """
    sel = substrate_core & (frame.max(-1) >= DARK_V)
    if sel.sum() < 500:
        return frame
    gain = substrate_rgb / np.maximum(np.median(frame[sel], axis=0), 1e-3)
    return np.clip(frame * gain, 0.0, 1.0)


def _refer_to_substrate(seen: np.ndarray, frame: np.ndarray,
                        substrate_core: np.ndarray) -> np.ndarray:
    """Put the predicted appearance on this frame's own level.

    The chart is measured on the rectified face as it comes; the frame being
    classified has had its illumination divided out, and `flatten_on_substrate`
    renormalises to the estimate's mean rather than preserving the level. The
    residual is small -- 0.02 to 0.03 -- and on most cartons it changes nothing.

    On Imovane it changes everything, and that is why both halves are here. Its
    substrate and highlight are 0.086 apart, so being 0.03 out on the level is
    a third of the gap the classifier has to resolve: the curve alone read its
    worst field at 76.2% with a swing of +-2.9, against 91.9% and +-0.1 for the
    gain-anchored paint it replaced. Kamagra is the opposite case, needing the
    curve's LIFT, which no gain can supply -- 8.4% against 90.7%.

    So: the curve supplies the shape, the grey card the level. Same gain
    `_anchor` takes, applied to the MODEL rather than to the frame, which is
    what keeps it clear of ColourError. Multiplicative because the thing being
    undone is: the flattening scales the frame, ambient light included.
    """
    sel = substrate_core & (frame.max(-1) >= DARK_V)
    if sel.sum() < 500:
        return seen
    gain = np.median(frame[sel], axis=0) / np.maximum(seen[0], 1e-3)
    return np.clip(seen * gain, 0.0, 1.0)


def _classify(img: Image.Image, palette: np.ndarray,
              substrate_core: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Nearest-colour index per pixel, plus a mask of pixels worth scoring.

    Dark pixels are dropped: our render prints the label and the reference
    carries type the spec deliberately does not represent. Scoring them would
    measure the type grid, which is a different piece of work, and would move
    this number every time a string changed length.
    """
    a = _flatten_illumination(np.asarray(img.convert("RGB")).astype(float) / 255.0,
                              FLATTEN_RADIUS_DIV)
    mask = a.max(-1) >= DARK_V
    if substrate_core is not None:
        a = _anchor(a, substrate_core, palette[0])
    return _nearest(a, palette), mask


LUMA = np.array([0.2126, 0.7152, 0.0722])


def _collinearity(palette: np.ndarray, names: list) -> tuple:
    """How near any spec colour sits to the line between two others.

    `palette_closest_pair` asks whether two entries can be told apart, and
    misses the condition that actually breaks these cartons: an entry lying ON
    the segment between two others is what every boundary pixel between those
    two averages to. Xanax has the group's second-WIDEST closest pair, 0.522,
    and its `#968974` sits 0.013 off the line from substrate to brand -- a 44%
    blend of them. Every antialiased glyph edge on the carton read as that
    field.

    Not a gate, because nothing can be done about it from the renderer's side:
    the colours are the carton's. It is reported so a low field IoU on Xanax
    (0.013) or Ativan (0.017) is read as the palette rather than as the build.
    """
    import itertools
    best, who = float("inf"), ""
    for k in range(len(palette)):
        for i, j in itertools.combinations([x for x in range(len(palette)) if x != k], 2):
            a, b = palette[i], palette[j]
            ab = b - a
            t = float(np.clip(np.dot(palette[k] - a, ab) / max(np.dot(ab, ab), 1e-9), 0, 1))
            d = float(np.linalg.norm(palette[k] - (a + t * ab)))
            if d < best:
                best, who = d, f"{names[k]} on {names[i]}-{names[j]}"
    return (None, None) if best == float("inf") else (round(best, 4), who)


def scored_mask(frame: np.ndarray, palette: np.ndarray,
                spec_idx: np.ndarray) -> np.ndarray:
    """Pixels a comparison is entitled to score.

    The dark cut exists to keep printed TYPE out of the figures: our render
    prints it and the spec deliberately does not carry it. It must not also cut
    the dark FIELDS the spec does carry, and where it did, it cut them in the
    one way that cannot show up as a low score -- a field is dropped exactly
    where our render painted it dark, i.e. where we got it RIGHT, leaving the
    field scored only over the pixels we missed.

    Ritalin is the demonstration. Its `type` field is `#2E1D3C`, its only field,
    and it reported the group's BEST agreement (99.87%) on an IoU of 0.043. With
    the field's own pixels admitted the IoU is 0.926 and the agreement does not
    move, because the field is 1.6% of the face. Kamagra is the opposite corner:
    its two greens are 53% of the face, were being seen as 3%, and its agreement
    falls 96.9% -> 84.0% once they are scored.

    Whether a pixel counts therefore depends on what the SPEC expects there, not
    on how bright the pixel happens to be. `_colour_error` and `_response` were
    given this in contract 1.5; `_agreement` was not, which is the defect.

    The two darkness tests are deliberately different and the asymmetry is safe
    in the only direction that matters: the cut is on the pixel's MAX channel,
    the restore on the fill's LUMA, and luma <= max always, so no fill the cut
    can reach is left unrestored.

    The cut takes the ink's RIM with it, one pixel wide. A pixel straddling a
    glyph edge is a mixture of ink and board and is evidence about neither, and
    on a palette where some entry happens to sit on the line between the two, it
    is evidence for that entry. Xanax is the case: `#968974` is a 44% blend of
    its substrate and its brand to within 0.013, so every glyph edge on the
    carton read as highlight. 99.8% of its false highlight pixels lay within two
    pixels of dropped ink, they came to 0.80% of the face against a field that
    is 0.93% of it, and the field read 49.8% at 93.0% recall and 51.8%
    precision. With the rim dropped, 82.9%.

    ONE pixel, and the width is measured rather than chosen: r=1 takes the mean
    field from 80.1% to 90.1%, r=2 to 90.3% and r=3 no further. The benefit
    saturates at the resampling width because that is all this is -- the face is
    rectified to 1100px from a 2048 render. It costs 0.5-1.7% of the scored
    pixels, reported as `edge_dropped` rather than left silent.

    What this still cannot answer: a dark pixel where the spec draws the light
    substrate is either a dark field overrunning its outline or the printed type
    the spec does not carry, and nothing in the colour separates them. The cut
    drops it either way, so a dark field's overspill costs nothing and its IoU
    degenerates to RECALL -- the figure catches a field placed short, not one
    placed wide. Light fields are scored both ways as before.
    """
    expects_dark = ((palette * LUMA).sum(1) < DARK_V)[spec_idx]
    lit = frame.max(-1) >= DARK_V
    ink = ~lit & ~expects_dark
    rim = np.asarray(Image.fromarray((ink * 255).astype("uint8"))
                     .filter(ImageFilter.MaxFilter(3))) > 0
    return (lit | expects_dark) & ~(rim & ~expects_dark) & ~_seam(spec_idx)


def _seam(spec_idx: np.ndarray) -> np.ndarray:
    """Where two spec regions meet, one pixel either side.

    The same argument as the ink's rim, and the same measurement behind it: a
    pixel straddling a boundary is a mixture of both regions and is evidence
    about neither. Ativan is the case here -- `#8E9DA0` is a 42% blend of its
    substrate and its `secondary_1`, **94.0% of its false highlight pixels lay
    within two pixels of a spec boundary**, and the field read 63.8% at 92.2%
    recall and 67.4% precision. Excluded, 94.4%.

    The asymmetry that causes it is structural rather than anyone's mistake:
    `rasterise` fills polygons hard-edged, and our render arrives through a
    Lanczos rectification, so the target has a step where we have a ramp. The
    ramp passes through every colour between the two fills, and if some entry
    of the palette lives there it collects the whole boundary.

    ONE pixel, measured the same way the rim was: r=1 takes the group's mean
    field from 90.1% to 95.2% and r=2, 3, 4 give 95.3%, 95.2%, 95.1% -- it
    saturates, then decays. Costs 0.1-4.1% of the scored pixels.

    **It does not blind the figure to a misplaced field**, which was the thing
    to check before throwing pixels away. Shifting our own classification two
    pixels and re-scoring with the seam excluded: Ativan 94.4% -> 59.5%,
    Modafinil 100.0% -> 65.2%, Valium 98.4% -> 64.6%, Ritalin 98.6% -> 70.2%.
    A one-pixel exclusion cannot hide a two-pixel error.

    Nor does it hollow a field out: every field keeps at least 68.9% of itself
    and all but Ativan's highlight keep 83% or more. `field_kept_min` travels in
    the report so a field measured on a sliver would say so.

    A softer TARGET was tried instead -- the spec rasterised at 4x and averaged
    down, so both sides carry a ramp. It is better than nothing and much worse
    than this (Ativan 70.4% against 94.4%), because a box-filtered 4x raster is
    not the same ramp a Lanczos rectification leaves.
    """
    idx = spec_idx.astype("uint8")
    lo = np.asarray(Image.fromarray(idx).filter(ImageFilter.MinFilter(3)))
    hi = np.asarray(Image.fromarray(idx).filter(ImageFilter.MaxFilter(3)))
    return lo != hi


def _agreement(a_idx, b_idx, mask, n) -> dict:
    match = float((a_idx == b_idx)[mask].mean()) if mask.any() else 0.0
    iou = {}
    for k in range(n):
        x, y = (a_idx == k) & mask, (b_idx == k) & mask
        union = (x | y).sum()
        iou[k] = round(float((x & y).sum() / union), 3) if union else None
    return {"agreement": round(match, 4), "iou": iou}


# A render is a photograph of paint, and a photograph has an exposure and a black
# level. Fitting both needs more regions than parameters: two points determine a
# line exactly, so a two-region carton would report a residual of zero and mean
# nothing by it.
MIN_RESPONSE_REGIONS = 3


def _response(ours: np.ndarray, spec_idx: np.ndarray, palette: np.ndarray,
              mask: np.ndarray):
    """The picture's own response: what gain and black level map paint to pixels.

    Measured because ColourError was reporting it as colour error. The two worst
    figures in the group are both a SUBSTRATE, and both render at exactly 0.87
    times their spec on all three channels -- a neutral scale, which is an
    exposure and not a colour. The dark regions go the other way: Kamagra's
    `#00463B` has a red channel of zero on the spec and 0.128 in our render,
    because a lit surface in a studio does not return black.

    Neither is the renderer painting the wrong colour, and neither is a defect:
    they are what a picture of paint does. Reported separately so the figure
    beside them can be read as what it claims to be. Removing them takes
    Kamagra's worst region from 0.189 to 0.024.

    Per channel, least squares over the region means. At three regions this has
    one degree of freedom, so the residual is correspondingly optimistic; at two
    it has none and is not attempted.
    """
    obs, want = [], []
    for k in range(len(palette)):
        sel = (spec_idx == k) & mask
        if sel.sum() < 50:
            continue
        obs.append(ours[sel].mean(0))
        want.append(palette[k])
    if len(obs) < MIN_RESPONSE_REGIONS:
        return None, {}
    obs, want = np.array(obs), np.array(want)
    gain, lift = np.zeros(3), np.zeros(3)
    for ch in range(3):
        A = np.stack([obs[:, ch], np.ones(len(obs))], 1)
        gain[ch], lift[ch] = np.linalg.lstsq(A, want[:, ch], rcond=None)[0]
    residual, n = {}, 0
    for k in range(len(palette)):
        sel = (spec_idx == k) & mask
        if sel.sum() < 50:
            residual[k] = None
            continue
        residual[k] = round(float(np.linalg.norm(obs[n] * gain + lift - want[n])), 4)
        n += 1
    return {"gain": [round(float(g), 3) for g in gain],
            "lift": [round(float(v), 3) for v in lift]}, residual


def _colour_error(ours: np.ndarray, spec_idx: np.ndarray, palette: np.ndarray,
                  mask: np.ndarray) -> dict:
    """Did the renderer paint the right colour where the spec said to?

    Survives a palette a classifier cannot separate, which six of the eleven
    have. The regions come from the SPEC, which is known exactly, so nothing has
    to be inferred from our pixels: they are only sampled. Two fills four levels
    apart make "which region is this pixel in" unanswerable while leaving "is
    this region the colour it should be" perfectly well posed.
    """
    out = {}
    for k in range(len(palette)):
        sel = (spec_idx == k) & mask
        if sel.sum() < 50:
            out[k] = None
            continue
        out[k] = round(float(np.linalg.norm(ours[sel].mean(0) - palette[k])), 4)
    return out


def render_fresh(stem: str) -> Path:
    """Render this SKU now. The comparison is worthless against a stale PNG.

    Same reasoning as the sweep's provenance check, applied at its strictest: a
    design render is being compared with the design it was supposed to build, so
    "which driver drew it" is not a detail.
    """
    out = RENDER_DIR / f"{stem}.png"
    for stale in (out, out.with_suffix(".view.json")):
        if stale.exists():
            stale.unlink()
    proc = subprocess.run(
        [str(_BL["executable"]), "--background", "--factory-startup",
         "--python", str(resolve_path(_BL["driver_script"])), "--",
         "--job", str(MANIFEST_DIR / f"{stem}.json"), "--out", str(out),
         "--engine-type", _BL.get("engine_type", "CYCLES"),
         "--samples", str(_BL.get("samples", 16)),
         "--res-x", str(_BL.get("resolution", [2048, 2048])[0]),
         "--res-y", str(_BL.get("resolution", [2048, 2048])[1])],
        capture_output=True, text=True, timeout=900)
    if not out.exists():
        raise SystemExit(f"{stem}: no render produced\n{proc.stderr[-1500:]}")
    return out


def measure(stem: str, preview: bool = False) -> dict:
    spec = load_design(stem)
    folder = TEMPLATES_DIR / FOLDER_BY_STEM[stem]

    # CONTRACT 1.9: the palette is the set of colours the spec actually PAINTS,
    # which is one per distinct part fill and no longer one per field. A field
    # whose parts disagree needs both entries or the classifier has no word for
    # one of them; under 1.8, and under 1.9's Stage A, every part carries its
    # field's colour and this reduces to exactly the old palette.
    #
    # `to_field` maps each entry back to the field it belongs to, and every
    # REPORTED figure is computed on the mapped indices. That is what keeps
    # `field_iou_worst` a statement about fields while the classifier works in
    # colours -- otherwise splitting a field into two paints would silently
    # redefine the headline, which is precisely how contract 1.9's first attempt
    # ended up comparing two instruments instead of two renders.
    front_fields, entries, to_field = _front_palette_entries(spec)
    palette = np.stack([_hex_rgb(c) for _, c in entries])
    to_field = np.array(to_field)
    n_report = len(front_fields) + 1
    gaps = [float(np.linalg.norm(palette[i] - palette[j]))
            for i in range(len(palette)) for j in range(i + 1, len(palette))]
    closest = min(gaps) if gaps else 1.0
    on_line, on_line_who = _collinearity(palette, [r for r, _ in entries])
    aspect = float(spec["face_aspect"])
    size = (OUT_WIDTH, max(1, round(OUT_WIDTH * aspect)))

    # The spec, drawn at the comparison size. This is the target both sides are
    # measured against, in its own colours.
    target = rasterise(spec, *size)
    t_idx, _ = _classify(target, palette)

    png = render_fresh(stem)
    view = json.loads(png.with_suffix(".view.json").read_text(encoding="utf-8"))
    ours = flatten_face(png, view["front_face_px"], out_width=OUT_WIDTH, aspect=aspect)
    ours_raw = np.asarray(ours.convert("RGB")).astype(float) / 255.0
    # CONTRACT 1.10: the substrate core is where the spec draws the BOARD, and a
    # mark is not the board however much it resembles one. `74_Viagra`'s Pfizer
    # oval is `#D8D9D5` against a substrate of `#DDDEDB` -- **0.0364** apart, so
    # it classifies as substrate and joins the core, and the illumination plane
    # is then fitted through a region the spec paints separately. Measured, that
    # moved the carton's brand `region_colour_gap` 0.0857 -> 0.1305 for a mark
    # drawn exactly where it belongs.
    mark_area = np.zeros(ours_raw.shape[:2], bool)
    for mark in (spec.get("marks") or []):
        for part in drawable_mark_parts(mark):
            region = part_region(part, *size)
            if region is not None:
                mark_area |= np.asarray(region)
    core = _substrate_core(t_idx) & ~mark_area
    # ColourError always reads the PLANE. It asks whether a region is the colour
    # it should be, so its illumination estimate must not be able to absorb the
    # design -- a blur can, which is the defect recorded against Kamagra below.
    ours_flat = flatten_on_substrate(ours_raw, core)
    scored = scored_mask(ours_flat, palette, t_idx)
    # CONTRACT 1.10: a mark's area leaves the scored set, the same exclusion
    # `verify()` and `design_coverage` make and for a sharper reason here -- a
    # mark's colour is NOT in this palette. The palette is the set of colours the
    # spec paints as FIELDS, so every mark pixel would classify to whichever
    # entry happens to be nearest, on both sides, and land in some field's IoU
    # having nothing to do with that field.
    #
    # Adding the mark colours to the palette was the other option and is worse:
    # `field_iou_worst` would then be a statement about fields and marks at
    # once, which is exactly the silent redefinition `to_field` exists to stop.
    #
    # `region_colour_gap` still judges them, and is the right instrument for it:
    # its regions come from `spec_index`, which gives a mark its own index, so a
    # mark is scored on whether our render puts the measured colour where the
    # photograph has it -- without a vocabulary that has no word for it.
    # Kept before the exclusion, because `region_colour_gap` SHOULD judge a mark
    # and the figures below should not. The gap has no vocabulary -- its regions
    # come from `spec_index`, which gives a mark its own index -- so it can ask
    # the one question that matters here: does our render put the measured
    # colour where the photograph has it? Excluding marks from this too was the
    # first attempt and it left them judged by nothing at all.
    scored_all = scored
    scored = scored & ~mark_area

    # The CLASSIFIER takes whichever model leaves the substrate flattest. Neither
    # is right everywhere and the difference is not small: on `59-min` the plane
    # leaves a residual of 0.085 against the blur's 0.066 and classifies 28.9% of
    # the face as highlight where the spec draws 21.1%, reading 88.6% against the
    # blur's 98.1%; on `155-min` it is the other way round, 0.030 against 0.036
    # and 98.4% against 94.1%. On the other nine the two agree to a tenth of a
    # point, so this changes nothing where nothing needed changing.
    #
    # Chosen on the SUBSTRATE, never on the fields -- see _substrate_residual.
    candidates = {"plane": ours_flat, "blur": _flatten_illumination(ours_raw, 2.0)}
    # The anchor still puts the two models on one level so their flatness is
    # comparable. It no longer stands in for the transfer curve -- see below.
    anchored = {k: _anchor(v, core, palette[0]) for k, v in candidates.items()}
    residual = {k: _substrate_residual(v, core) for k, v in anchored.items()}
    chosen = min(residual, key=residual.get)

    # Classify in the RENDER's space, against each paint as this rig renders it,
    # measured off a chart -- see scripts/calibrate_render.py. Comparing a render
    # against PRINT colours is wrong in a way a gain off the substrate cannot
    # reach: the transfer has a lift, and at the dark end the lift is the larger
    # term. Kamagra's `#00463B` and `#002F26` are 0.122 apart and both render
    # with a red near 0.13 against a spec that says 0.000, so the shared
    # displacement exceeded the gap it had to preserve and 89% of the darker
    # field was classified as the lighter one -- 0.084, the group's worst field
    # by a factor of five. Against the measured appearance it reads 0.907.
    #
    # The curve gives the shape and the grey card the level -- both, because
    # each carton that needs one is broken by the other. See _refer_to_substrate.
    predicted = appearance(palette, *load_curve(stem))
    seen = _refer_to_substrate(predicted, candidates[chosen], core)
    o_idx = _nearest(candidates[chosen], seen)

    # The swing is what the figure does under the same model with a different
    # arbitrary knob -- the erosion the plane is fitted through, the radius the
    # blur is taken at. Differencing against the REJECTED model instead reports
    # the cost of a estimate the substrate already showed to be worse, which is
    # not the figure's uncertainty: it read +-9.5 on `59-min` for exactly that.
    variant = (flatten_on_substrate(ours_raw, _substrate_core(t_idx, 9))
               if chosen == "plane" else _flatten_illumination(ours_raw, 2.5))
    # Referred to the variant's OWN substrate reading: the perturbation is the
    # illumination estimate, and re-levelling is part of what it perturbs.
    alt_idx = _nearest(variant, _refer_to_substrate(predicted, variant, core))

    # Every figure below reads the same mask -- see scored_mask. Inside Xanax's
    # near-black brand the bare cut left only the lit fringe, whose mean sits
    # nowhere near the fill, and ColourError read 0.600 against a render measured
    # at 99.4% agreement. Agreement was left on the bare cut for one contract
    # longer and was reporting the same distortion the other way round.
    colour_err = _colour_error(ours_flat, t_idx, palette, scored)
    response, colour_residual = _response(ours_flat, t_idx, palette, scored)

    # Computed, not looked up. This used to read
    # `{PREVIEW_DIR}/{folder.name}.flat.png`, a derived artefact keyed by folder
    # name, and it went stale both ways it can: a rename orphaned two of them and
    # the report printed 0.0% agreement rather than saying so, and one carton's
    # corners were set after the directory was last written so its face was six
    # hours out of date for five days. `rectified_face` is a perspective warp of
    # one JPEG and costs nothing beside the render this function has already
    # made -- and `render_fresh` re-renders OUR side every run for exactly this
    # reason.
    ref = rectified_face(folder)[0].resize(size, Image.LANCZOS)
    ref_idx, _bare = _classify(ref, palette, core)
    # The photograph carries type too, and its glyph rims blend the same way.
    # Same mask, same reason.
    ref_mask = scored_mask(
        _flatten_illumination(np.asarray(ref.convert("RGB")).astype(float) / 255.0,
                              FLATTEN_RADIUS_DIV),
        palette, t_idx)

    result = {
        "sku": stem,
        "folder": folder.name,
        "palette_closest_pair": round(closest, 4),
        "separable": closest >= SEPARABLE_MIN,
        # A different failure from a close pair, and the pairwise figure cannot
        # see it -- see _collinearity.
        "palette_on_line": on_line,
        "palette_on_line_who": on_line_who,
        # What the ink's rim cost, so the cut is not silent about its own price.
        "edge_dropped": round(float(1 - scored.sum()
                                    / max(((ours_flat.max(-1) >= DARK_V)
                                           | ((palette * LUMA).sum(1) < DARK_V)[t_idx]
                                           ).sum(), 1)), 4),
        "illumination": chosen,
        "illumination_residual": {k: round(v, 4) for k, v in residual.items()},
        "render_vs_spec": _agreement(to_field[o_idx], to_field[t_idx],
                                     scored, n_report),
        # Agreement is area-weighted and a substrate is 55-99.9% of these faces,
        # so a field can be missed entirely without moving it: Ritalin's field
        # is 1.6% of its carton. The worst FIELD is the figure that shows a
        # design failing, and it belongs in the printed table rather than only
        # in the JSON, which is how the collapsed IoUs went unread.
        "field_iou_worst": None,
        # The figure's own uncertainty, measured rather than assumed.
        "agreement_spread": round(abs(
            _agreement(to_field[o_idx], to_field[t_idx], scored, n_report)["agreement"]
            - _agreement(to_field[alt_idx], to_field[t_idx], scored, n_report)["agreement"]), 4),
        "colour_error_by_region": colour_err,
        "colour_error_worst": (max([v for v in colour_err.values() if v is not None],
                                   default=None)),
        # What is left once the picture's own exposure and black level are taken
        # out -- see _response. None where there are too few regions to fit them.
        "response": response,
        "colour_residual_by_region": colour_residual,
        "colour_residual_worst": (max([v for v in colour_residual.values() if v is not None],
                                      default=None)),
        "spec_vs_reference": (spec.get("verification") or {}).get("pixel_agreement"),
        # What each palette index MEANS, because under contract 1.9 it is no
        # longer the field index. `colour_error_by_region` and its residual are
        # keyed by painted colour, and a field whose parts disagree owns more
        # than one of them -- without this the reader cannot tell that entries 1
        # and 2 are one field. The agreements are keyed by FIELD and are mapped
        # through `to_field` before they are computed, so they are unaffected.
        "palette_entries": [{"index": i, "role": role, "fill": col,
                             "field": int(to_field[i]) - 1 if i else None}
                            for i, (role, col) in enumerate(entries)],
    }
    fields = [v for k, v in result["render_vs_spec"]["iou"].items()
              if int(k) > 0 and v is not None]
    result["field_iou_worst"] = min(fields) if fields else None
    # The smallest share of any field left standing once the seam and the rim
    # are gone. A field measured on a sliver has to say so rather than report a
    # confident number about very little of itself.
    kept = []
    f_idx = to_field[t_idx]
    for k in range(1, n_report):
        whole = (f_idx == k)
        if whole.sum() >= 200:
            kept.append(float((whole & scored).sum() / whole.sum()))
    result["field_kept_min"] = round(min(kept), 4) if kept else None
    # Always present, and null is now unreachable rather than merely unlikely:
    # `rectified_face` raises rather than returning nothing. The key is kept
    # optional in shape because the report is read by things that predate this,
    # and because a figure that was never taken must never print as a figure
    # that came out zero -- which is what an absent key did for two days.
    result["render_vs_reference"] = None
    if ref_idx is not None:
        result["render_vs_reference"] = _agreement(
            to_field[o_idx], to_field[ref_idx], scored & ref_mask, n_report)

    # ── A COLOUR COMPARISON THAT SURVIVES THE PALETTE MOVING ────────────────
    # `render_vs_reference` above is an agreement between two index maps, and
    # BOTH are produced by classifying against `palette`. So it moves whenever
    # the palette does -- which is every time a part is painted a different
    # colour. Contract 1.9 was built, measured and rolled back partly on that:
    # its before and after were two instruments rather than two renders
    # (00_PROJECT_STATE/PART_FILL.md).
    #
    # This asks the same question without a vocabulary. The regions come from
    # `spec_index`, which builds them from `part_region` -- GEOMETRY, the same
    # outlines the fitter traced -- so they do not move when paint does. Inside
    # each region both sides are MEASURED and differenced. No classification, no
    # palette, no nearest-colour anything.
    #
    # WHAT IT INHERITS, said here rather than discovered later: the regions are
    # the spec's, and the spec approximates the reference to `spec~ref`, 95-100%
    # across the group. This is not a direct measurement of the photograph; it is
    # a measurement inside the spec's idea of where things are.
    #
    # Both sides are levelled on the substrate the same way, because comparing a
    # flattened render against a raw photograph would report the illumination
    # rather than the paint.
    ref_raw = np.asarray(ref.convert("RGB")).astype(float) / 255.0
    ref_flat = flatten_on_substrate(ref_raw, core)
    geo = spec_index(spec, *size)
    gap = {}
    for k in sorted(set(int(v) for v in np.unique(geo))):
        sel = (geo == k) & scored_all
        if int(sel.sum()) < 50:
            # A region measured on almost nothing says so, rather than
            # reporting a confident number about very little of itself.
            gap[k] = None
            continue
        gap[k] = round(float(np.linalg.norm(
            ours_flat[sel].mean(0) - ref_flat[sel].mean(0))), 4)
    result["region_colour_gap"] = gap
    _g = [v for v in gap.values() if v is not None]
    result["region_colour_gap_worst"] = round(max(_g), 4) if _g else None

    if preview:
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        strip = Image.new("RGB", (size[0], size[1] * 3 + 24), (255, 255, 255))
        strip.paste(rectified_face(folder)[0].resize(size), (0, 0))
        strip.paste(target, (0, size[1] + 12))
        strip.paste(ours, (0, 2 * size[1] + 24))
        strip.save(PREVIEW_DIR / f"{folder.name}.qa.png")
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sku", help="one SKU stem; default is every design SKU")
    p.add_argument("--preview", action="store_true",
                   help="write reference / spec / render as one strip")
    args = p.parse_args()

    stems = [args.sku] if args.sku else sorted(
        FOLDER_BY_STEM, key=lambda s: int(s.split("-")[0]))

    rows = []
    print(f"{'SKU':9s} {'folder':32s} {'spec~ref':>9s} {'render~spec':>12s} "
          f"{'worst fld':>10s} {'render~ref':>11s} {'worst dC':>9s} "
          f"{'residual':>8s} {'swing':>6s}")
    for stem in stems:
        r = measure(stem, args.preview)
        rows.append(r)
        sr = r["spec_vs_reference"]
        flag = "" if r["separable"] else "  (palette not separable)"
        if r["palette_on_line"] is not None and r["palette_on_line"] < ON_LINE_MIN:
            flag += f"  ({r['palette_on_line_who']}, {r['palette_on_line']:.3f})"
        # A dash, not a zero, in every column that can be absent. Too few
        # regions to fit the picture's response is not the same as nothing left
        # after fitting it; a carton with no field is not a carton whose worst
        # field matches nothing; and a photograph that was never rectified is
        # not a render that resembles it on no pixel. Four columns printed a
        # zero for all of those, with the right idiom already on this line.
        def pct(x):
            return "--" if x is None else f"{100 * x:.1f}%"

        resid = r["colour_residual_worst"]
        cerr = r["colour_error_worst"]
        print(f"{stem:9s} {r['folder']:32s} "
              f"{pct(sr):>9s} "
              f"{100 * r['render_vs_spec']['agreement']:11.1f}% "
              f"{pct(r['field_iou_worst']):>10s} "
              f"{pct((r.get('render_vs_reference') or {}).get('agreement')):>11s} "
              f"{('--' if cerr is None else f'{cerr:.3f}'):>9s} "
              f"{('--' if resid is None else f'{resid:.3f}'):>8s} "
              f"+-{100 * r['agreement_spread']:4.1f}{flag}")

    out = PROJECT_ROOT / "00_PROJECT_STATE" / "design_qa.json"
    if args.sku:
        # A single-SKU run used to write the report with one row in it, silently
        # discarding the other ten. Merging them instead would be worse: the
        # rows would then come from different revisions of this script with
        # nothing in the file to say which. The full run is the report.
        print(f"\n--sku is a probe; {out.name} is left alone. Run without it to "
              f"rewrite the report.")
        return 0
    out.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    print(f"\n{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
