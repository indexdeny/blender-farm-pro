"""D-1 — measure a reference carton's front face.

Rectifies the front face out of a reference photograph and reports what the
design is actually made of: the share of the face each colour field covers, and
the true colour of each field.

    python scripts/measure_reference_face.py --all
    python scripts/measure_reference_face.py --folder 02_T1_SMALL_Cialis
    python scripts/measure_reference_face.py --folder 15_T1_Xanax --preview

Corners come from `front_face_px` in the folder's metadata.json and are set by
hand: a photograph gives no reliable automatic handle on which quadrilateral is
the front face, and the failure is silent -- the first Cialis corner set was
40px too high, pulled the lid into the frame, and rectified into something that
looked entirely plausible until it was compared with the photograph. `--preview`
writes the rectified face and its segmentation so that comparison is possible;
setting corners without looking at the preview is guessing.

WHY THE CLASSIFIER IS NOT A COLOUR TEST. These eleven cartons are olive, navy,
purple, magenta, lime. A rule keyed on any hue reads one of them and lies about
the rest. Illumination is divided out, then the whole face is clustered into four
by k-means, and the clusters are labelled by property: the largest is the
substrate, the most saturated of the rest is the brand field, the brightest
remainder is the highlight, and the darkest is type only while it stays small.

Every clause there was put in by a measurement that contradicted a simpler rule.
"Least saturated is the substrate" named Lexotanil's cyan band the brand colour
and its lime board the highlight -- that board is saturated. "Dark is type" gave
Kamagra 30.7% type, because its teal field is dark. Both were labelling failures
over a partition that was already correct.

The `type` share is reported when a dark cluster separates and left blank when it
does not, and nothing downstream should need it: the renderer draws type from the
manifest's strings, not from a measured area. What D-2 needs from here is the
FIELDS -- their colours and how much of the face each covers.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.deskew import flatten_face  # noqa: E402

TEMPLATES_DIR = PROJECT_ROOT / "Reference Templates"
OUT_WIDTH = 1100
DARK_V = 0.35          # a cluster darker than this MAY be type
TYPE_MAX_SHARE = 0.15  # ...but only while it stays this small a share of the face
# Two clusters closer than this in RGB are one printed surface that the
# clustering split under a lighting gradient, not two design elements. Kamagra's
# board came back as #D9D6CB over 31.1% of the face and #D3CCC1 over 14.6%; the
# real carton has one cream. The same figure bounds what a measurement can tell
# apart afterwards, so it is imported by scripts/fit_design_spec.py rather than
# written down twice.
SAME_SURFACE_MAX = 0.08
KMEANS_ITERS = 40
KMEANS_SEED_STEPS = 3  # deterministic seeding: quantiles of luminance


def _hsv(rgb: np.ndarray):
    mx, mn = rgb.max(-1), rgb.min(-1)
    v = mx
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    return s, v


def _flatten_illumination(rgb: np.ndarray, radius_div: float = 6.0) -> np.ndarray:
    """Divide out the photograph's lighting gradient before anything is classified.

    These are product photographs, not scans: on the Cialis carton the left of
    the face is roughly half as bright as the right. Classify on that directly
    and the SHADED part of the brand field falls under any darkness threshold
    that catches type -- measured, it put 13.1% of the face in "type" where the
    true figure is 5.0%, and collapsed substrate and highlight into one cluster.

    Shading multiplies; so dividing by a heavily blurred luminance removes it and
    leaves the printed fields.

    THE RADIUS IS A CALLER'S CHOICE, and the two callers need different answers.

    A sixth of the face follows the design's own large-scale structure. For
    CLUSTERING that is harmless -- k-means only asks which pixels resemble each
    other, never how they compare with a nominal colour -- and it helps, because
    the residual gradient is what separates two near-identical creams.

    For comparing a render against the colour the driver was told to paint, it is
    a defect. The result is divided by a local estimate AND multiplied by a global
    mean, both of which drop when a design is half dark: Kamagra's teal covers
    half its carton, so its cream board measured 0.413 away from the colour it was
    painted -- the largest error in the group, on a render that was correct.
    Measured across the sample, the ratio of rendered substrate to nominal tracked
    how dark the whole face is (Kamagra 0.673, Cialis 0.850, Ritalin 0.930,
    Modafinil 0.948), which is the signature of a correction eating signal rather
    than shading. At half the face the estimate is nearly a plane, which is what a
    lighting gradient actually is, and Kamagra reads 0.829.

    Widening it HERE was tried and reverted: it changes the partition, and through
    it every spec -- Viagra picked up its holographic patch as a design field and
    Imovane a grey one, costing them 20 and 8 points against their photographs.
    scripts/design_qa.py passes the wide radius for its own comparison instead.
    """
    from PIL import ImageFilter

    lum = rgb.max(-1)
    radius = max(rgb.shape[0], rgb.shape[1]) / radius_div
    blurred = np.asarray(
        Image.fromarray((lum * 255).astype("uint8"))
        .filter(ImageFilter.GaussianBlur(radius=radius)),
        dtype=float) / 255.0
    blurred = np.maximum(blurred, 1e-3)
    return np.clip(rgb / blurred[..., None] * float(blurred.mean()), 0.0, 1.0)


def _kmeans(x: np.ndarray, k: int) -> np.ndarray:
    """Tiny deterministic k-means. No sklearn, no scipy, no randomness.

    Seeded from luminance quantiles rather than random points, because a
    measurement that moves between runs cannot be committed as data.
    """
    lum = x.mean(1)
    qs = np.linspace(0.15, 0.85, k)
    centres = np.stack([x[np.argmin(np.abs(lum - np.quantile(lum, q)))] for q in qs])
    labels = np.zeros(len(x), dtype=int)
    for _ in range(KMEANS_ITERS):
        d = ((x[:, None, :] - centres[None, :, :]) ** 2).sum(-1)
        new = d.argmin(1)
        if (new == labels).all():
            break
        labels = new
        for j in range(k):
            if (labels == j).any():
                centres[j] = x[labels == j].mean(0)
    return labels


def _hex(rgb01) -> str:
    r, g, b = (np.clip(np.asarray(rgb01), 0, 1) * 255).round().astype(int)
    return f"#{r:02X}{g:02X}{b:02X}"


def _catalogue_aspect(folder: Path) -> float | None:
    """height/width of the face OUR renderer builds for this SKU.

    Recorded beside the reference's own aspect, never used to rectify it. The
    two are different cartons: the Viagra photograph shows a face far taller
    than the catalogue's 110x50, and forcing the reference into the catalogue's
    proportions would squash the design being measured -- then the layout
    extracted from it would be wrong in a way no later step could detect.

    Reconciling the two is a decision for D-2 (stretch the design, or preserve
    its proportions and let the margins differ). A measurement step should not
    make that decision silently by choosing a divisor.
    """
    try:
        from scripts.make_ocr_fixtures import TEMPLATE_SAMPLE
        stem = TEMPLATE_SAMPLE[folder.name]
        manifest = json.loads(
            (PROJECT_ROOT / "04_passports" / "render_manifests" / f"{stem}.json")
            .read_text(encoding="utf-8"))
        d = manifest["carton"]["passport_dimensions"]
        return round(float(d["height_mm"]) / float(d["width_mm"]), 4)
    except Exception:
        return None


def rectified_face(folder: Path):
    """The folder's front face, flattened. Computed, never cached.

    Split out of `segment` so `design_qa` can obtain the SAME rectified face
    without going through a file. It used to read one from
    `02_processing/reference_measurement/{folder}.flat.png`, which is a derived
    artefact keyed by folder name, and both ways of going stale duly happened:
    `aa28834` renamed two folders and orphaned their previews, so the report
    printed 0.0% agreement for two cartons for two days; and `304_Sonata`'s
    corners were set six hours after every preview in that directory was
    written, so its face was quietly out of date for five days with no name
    lost at all.

    Nothing here needs a cache. The face is a perspective warp of one JPEG --
    `flatten_face` and nothing else, no k-means, no clustering -- and the
    project already applies exactly this reasoning to the other side of the
    same comparison: `design_qa.render_fresh` deletes and re-renders our own
    PNG every run because a stale one makes the comparison worthless. The
    reference is the same comparison and gets the same treatment.

    Returns (flat, source, corners) so a caller can record what it read.
    """
    meta_path = folder / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    corners = meta.get("front_face_px")
    if not corners:
        raise SystemExit(
            f"{folder.name}: no `front_face_px` in metadata.json. Set the four "
            f"front-face corners (TL, TR, BR, BL) by hand against a coordinate "
            f"overlay, then re-run with --preview and check the result.")

    source = meta.get("front_face_measurement", {}).get("source_image")
    if not source:
        images = meta.get("reference_images") or []
        source = next((i for i in images if "front" in i.lower()), images[0] if images else None)
    if not source or not (folder / source).exists():
        raise SystemExit(f"{folder.name}: source image {source!r} not found")

    # The reference is rectified to its OWN proportions -- flatten_face's
    # default, the averaged edge ratio of the quad. What the catalogue thinks
    # this SKU measures is recorded next to it, not imposed on it.
    return flatten_face(folder / source, corners, out_width=OUT_WIDTH,
                        aspect=None), source, corners


def segment(folder: Path):
    """Rectify a reference face and partition it into named fields.

    Split out of `measure` so the D-2 spec fitter works from exactly the same
    partition the D-1 measurement reported. Two implementations of "the same"
    segmentation is the shape of defect this project has already been bitten by
    twice -- once in render_qa's two copies of one fold, once in the sweep's two
    ideas of what a report covers.

    Returns (flat, labels, named, meta, source): `flat` is the rectified RGB
    image, `labels` is one k-means label per pixel, `named` maps
    substrate/brand/highlight/type to a group dict (or None where that role did
    not separate), `meta` is the folder's metadata and `source` the photograph
    it was rectified from. All five callers unpack five; this said three.
    """
    meta_path = folder / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    flat, source, corners = rectified_face(folder)
    raw = np.asarray(flat).astype(float) / 255.0
    a = _flatten_illumination(raw)
    s, v = _hsv(a)

    # Everything is clustered together, including the dark pixels. Splitting type
    # off first by a darkness threshold reads whichever cartons print dark type
    # on light board and misreads the rest: Kamagra's dark teal FIELD went under
    # any threshold that catches type and came back as 30.7% "type", and
    # Lexotanil's saturated lime substrate outranked its own cyan band on
    # saturation, so the band was named the brand colour and the substrate the
    # highlight. Both are labelling failures, not clustering failures -- the
    # partition was right in each case.
    px = a.reshape(-1, 3)
    raw_px = raw.reshape(-1, 3)
    labels = _kmeans(px, 4)

    groups = []
    for j in range(4):
        m = labels == j
        if not m.any():
            continue
        mean = px[m].mean(0)
        ms, mv = _hsv(mean[None, :])
        # Reported colour comes from the RAW pixels, by median. Classification
        # needs the illumination-corrected image; the ink's actual colour is a
        # property of the photograph, and a median resists the shaded tail that
        # would drag a mean toward black.
        groups.append({"n": int(m.sum()), "mean": mean, "labels": [j],
                       "colour": np.median(raw_px[m], axis=0),
                       "sat": float(ms[0]), "val": float(mv[0])})

    # Merge before naming. Roles are handed out one per cluster, so two clusters
    # of one surface consume two roles and push a real field off the end -- which
    # is what happened: Kamagra's four clusters were teal, dark teal, cream and
    # cream, and the SECOND cream, 31.1% of the face, got no role at all and
    # never reached the spec. The carton then rendered two thirds teal against a
    # photograph that is under half.
    merged = True
    while merged and len(groups) > 1:
        merged = False
        for i in range(len(groups)):
            for j2 in range(i + 1, len(groups)):
                a, b = groups[i], groups[j2]
                if float(np.linalg.norm(a["colour"] - b["colour"])) >= SAME_SURFACE_MAX:
                    continue
                big, small = (a, b) if a["n"] >= b["n"] else (b, a)
                big["labels"] = big["labels"] + small["labels"]
                keep = np.isin(labels, big["labels"])
                big["n"] = int(keep.sum())
                big["mean"] = px[keep].mean(0)
                big["colour"] = np.median(raw_px[keep], axis=0)
                ms2, mv2 = _hsv(big["mean"][None, :])
                big["sat"], big["val"] = float(ms2[0]), float(mv2[0])
                groups.remove(small)
                merged = True
                break
            if merged:
                break

    # One label per surviving group, so every later consumer -- the role map, the
    # spec fitter's masks -- sees the merge rather than the raw partition.
    for g in groups:
        for lab in g["labels"][1:]:
            labels[labels == lab] = g["labels"][0]
        g["label"] = g["labels"][0]

    total = px.shape[0]
    # Type is the darkest cluster, but ONLY while it stays small. Printed type
    # covers a few percent of a face; a dark cluster covering a quarter of one is
    # a colour field that happens to be dark, and calling it type would both
    # invent a huge type area and hide a field.
    darkest = min(groups, key=lambda g: g["val"])
    type_group = darkest if (darkest["val"] < DARK_V
                             and darkest["n"] / total < TYPE_MAX_SHARE) else None
    fields = [g for g in groups if g is not type_group]

    # Substrate is the LARGEST remaining field -- robust whatever colour the board
    # is, where "least saturated" is not: Lexotanil's board is lime.
    substrate = max(fields, key=lambda g: g["n"])
    rest = [g for g in fields if g is not substrate]
    # None, never the substrate. The old fallback aliased brand to substrate when
    # nothing was left, which was harmless while every face produced at least
    # three clusters and became a hole the moment merging could leave two:
    # Modafinil's whole board was then handed to the fitter as a colour FIELD, it
    # traced the face, dropped 92% of it as glyphs, and scored 24.2%.
    brand = max(rest, key=lambda g: g["sat"]) if rest else None
    rest = [g for g in rest if g is not brand and g is not None]
    highlight = max(rest, key=lambda g: g["val"]) if rest else None

    named = {"substrate": substrate, "brand": brand,
             "highlight": highlight, "type": type_group}
    # Nothing measured is allowed to go unnamed. Any cluster still without a role
    # after merging is a real surface the face carries, and dropping it silently
    # is how a third of a carton went missing.
    for n, extra in enumerate(g for g in groups if g not in named.values()):
        named[f"secondary_{n + 1}"] = extra
    for role, g in named.items():
        if g is not None:
            g["role"] = role
    return flat, labels, named, meta, source


def measure(folder: Path, preview_dir: Path | None = None) -> dict:
    flat, labels, named, meta, source = segment(folder)
    meta_path = folder / "metadata.json"
    a = _flatten_illumination(np.asarray(flat).astype(float) / 255.0)
    px = a.reshape(-1, 3)
    total = px.shape[0]
    substrate, brand = named["substrate"], named["brand"]
    highlight, type_group = named["highlight"], named["type"]

    result = {
        "source_image": source,
        "rectified_px": [flat.width, flat.height],
        "reference_aspect": round(flat.height / flat.width, 4),
        "catalogue_aspect": _catalogue_aspect(folder),
        "fields": {
            "brand":     {"pct": round(100 * brand["n"] / total, 1),     "hex": _hex(brand["colour"])},
            "substrate": {"pct": round(100 * substrate["n"] / total, 1), "hex": _hex(substrate["colour"])},
            "highlight": ({"pct": round(100 * highlight["n"] / total, 1), "hex": _hex(highlight["colour"])}
                          if highlight else None),
            "type":      ({"pct": round(100 * type_group["n"] / total, 1), "hex": _hex(type_group["colour"])}
                          if type_group else None),
        },
        "method": ("rectified with src/deskew.flatten_face from hand-set corners; "
                   "type split by value < 0.35, remainder k-means k=3 labelled by "
                   "saturation and value, not by hue"),
        "note": ("shares are of the FRONT FACE. The `color_zones` block counts the "
                 "whole photograph, background included, and the two are not "
                 "comparable."),
    }

    if preview_dir is not None:
        preview_dir.mkdir(parents=True, exist_ok=True)
        flat.save(preview_dir / f"{folder.name}.flat.png")
        # Each cluster painted with its OWN measured mean. The preview then shows
        # the design exactly as the measurement understands it -- flat fields, no
        # gradient, no shading -- so a misread field is visible rather than
        # plausible.
        centre_by_label = {j: px[labels == j].mean(0)
                           for j in range(4) if (labels == j).any()}
        vis = np.stack([centre_by_label[l] for l in labels]).reshape(a.shape)
        Image.fromarray((vis * 255).astype("uint8")).save(preview_dir / f"{folder.name}.seg.png")

    meta["design_measurement"] = result
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--folder", help="one template folder name")
    p.add_argument("--all", action="store_true",
                   help="every folder in the sample that has corners set")
    p.add_argument("--preview", metavar="DIR", nargs="?", const="__scratch__",
                   help="write the rectified face and its segmentation for inspection")
    args = p.parse_args()

    preview = None
    if args.preview:
        preview = (PROJECT_ROOT / "02_processing" / "reference_measurement"
                   if args.preview == "__scratch__" else Path(args.preview))

    if args.folder:
        folders = [TEMPLATES_DIR / args.folder]
    elif args.all:
        from scripts.make_ocr_fixtures import TEMPLATE_SAMPLE
        folders = [TEMPLATES_DIR / name for name in sorted(TEMPLATE_SAMPLE)]
    else:
        p.error("pass --folder NAME or --all")

    print(f"{'folder':32s} {'brand':>18s} {'substrate':>18s} {'highlight':>14s} {'type':>7s}")
    done = 0
    for folder in folders:
        meta = folder / "metadata.json"
        if not meta.exists():
            print(f"{folder.name:32s} no metadata.json")
            continue
        if not json.loads(meta.read_text(encoding="utf-8")).get("front_face_px"):
            print(f"{folder.name:32s} — corners not set")
            continue
        r = measure(folder, preview)
        f = r["fields"]
        def cell(k, w=0):
            g = f.get(k)
            return f"{g['hex']} {g['pct']:5.1f}%" if g else f"{'—':>13s}"
        print(f"{folder.name:32s} {cell('brand')} {cell('substrate')} "
              f"{cell('highlight')} {cell('type')}")
        done += 1
    print(f"\n{done} of {len(folders)} measured")
    return 0


if __name__ == "__main__":
    sys.exit(main())
