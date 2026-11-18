"""D-2c — how much of the reference's PRINT a design spec actually carries.

    python scripts/design_coverage.py                  # every design SKU
    python scripts/design_coverage.py --control        # ...and prove it discriminates
    python scripts/design_coverage.py --out report.json

ADDED BESIDE `verification.pixel_agreement`, NEVER IN PLACE OF IT. That field is
the record of a measurement taken at a particular time, and other records cite
it; rewriting it retroactively would invalidate every one of them. Nothing here
writes a spec, a manifest or a passport — this script only reads.

WHAT WAS WRONG WITH THE OLD FIGURE. `fit_design_spec.verify()` scores every
pixel of the face, and on these 28 cartons the substrate covers 87% to 96% of
it. The number is therefore very nearly a statement about the BOARD. A spec that
carries no field at all draws substrate everywhere, the segmentation calls the
same pixels substrate, and the two agree on 100% of the face: `155-min`,
`304-min` and `308-min` each score a perfect 1.0000 while carrying zero fields
against photographs whose printed design covers 7.0% to 11.6% of the face.
`74-min` scores 0.9499 on a single five-vertex polygon whose own IoU against the
region it claims is 0.336.

WHAT THIS MEASURES INSTEAD. Only the printed area: every pixel the segmentation
assigns to something other than the board, plus every pixel the spec draws a
field on. Agreement over that union — so a spec that declares no print scores no
agreement, instead of scoring the board.

FOUR FIGURES, AND THEY ANSWER DIFFERENT QUESTIONS.

  print_agreement  Computed here, directly: agreement over the union of "the
                   reference prints something here" and "the spec draws
                   something here". It counts the ink that landed inside a
                   colour cluster, because reconstructing which components the
                   fitter dropped as glyphs would mean a second implementation
                   of its tracing loop, and this project has already paid twice
                   for duplicated logic.

  print_iou        Built ONLY from figures the fitter itself recorded: its own
                   `iou_by_field`, weighted by each printed cluster's share of
                   the face, with every printed cluster that produced NO field
                   entered at zero. It therefore inherits the fitter's glyph
                   exclusion exactly.

Where those two agree, the glyph question does not matter. Where they diverge,
the divergence IS the glyph question, and both are printed rather than one
chosen.

  truth_agreement  The same question asked of the hand-made ground truth in
                   `print_truth.json` instead of the raw clusters — see
                   `truth_from_labels`. The cluster figures take every
                   non-substrate cluster to be print, which counts Provigil's box
                   lid, the table under it and a stock-agency watermark as design
                   the spec failed to draw. This one counts only what a person
                   classified as printed design. Reported BESIDE the cluster
                   figure, never in place of it: `print_agreement` is what the
                   audit recorded and what its 52.99% mean refers to, and
                   redefining it would make the before and the after
                   incomparable at the moment the comparison matters.

  spec_off_print   How much of the face the spec draws a field on where the
                   reference prints no design — over a blister, a box lid, the
                   table, a letterform, a logo, a photograph, or the board
                   counted twice. It needs its own figure because
                   `truth_agreement` cannot see it: those pixels are outside the
                   scored area by design, since what a carton prints underneath a
                   blister is not in the photograph and is evidence about neither
                   side. Known upward bias: a legitimate field with type printed
                   on it reports that type's area here, because letterforms are
                   excluded too. The bias is constant per carton, so a before and
                   after difference is clean while the absolute value is an upper
                   bound.

THE TYPE CLUSTER IS EXCLUDED FROM BOTH, and it is the only exclusion.
Letterforms are drawn by the renderer from the manifest's strings; a spec is
right not to carry them, and this project already refuses a spec that traces the
reference's words. `type_pct` reports how much was excluded, so the exclusion is
not silent.

No module-level `DEFAULT_*` path constant is defined, deliberately: this script
writes nothing unless `--out` names a file. tests/test_script_paths.py walks
`DEFAULT_*` constants, so there is nothing here for it to check and nothing here
that can quietly point at the source project's layout.
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

from src.design_group import (  # noqa: E402
    FOLDER_BY_STEM, TEMPLATES_DIR, load_design, simple_ring,
)
from scripts.fit_design_spec import (  # noqa: E402
    TRUTH_NAME, components, design_component_sources, load_truth, part_region,
)
from src.mark_geometry import drawable_mark_parts  # noqa: E402
from scripts.measure_reference_face import _hex, segment  # noqa: E402

#: folder name -> catalogue SKU stem, the direction this script asks in.
STEM_BY_FOLDER = {folder: stem for stem, folder in FOLDER_BY_STEM.items()}

SUBSTRATE = 255   # the index rasterise()/verify() leave wherever no field is drawn

#: Contract 1.10. A mark is neither a field nor the board, and it gets its own
#: index so no figure can read it as either.
#:
#: It will usually DISAGREE with the hand-made ground truth, and that is honest
#: rather than a defect: the segmentation clusters `74_Viagra`'s Pfizer oval with
#: the SUBSTRATE -- it is `#D8D9D5` on a navy band -- so the truth says "board"
#: exactly where the spec now draws a mark. `MARKS_DECISION.md` said so in
#: advance: "the +9.937 is not carried forward -- it was measured by cutting a
#: hole with nothing behind it, and drawing a mark into the hole is a different
#: measurement". Cutting alone gains it back and drawing the mark spends it, and
#: the figure must show that rather than keep the gain.
MARK = 254


def spec_index(spec: dict, w: int, h: int) -> np.ndarray:
    """Which field the spec draws at each pixel; `SUBSTRATE` where none.

    The same region fill `fit_design_spec.verify()` scores against -- outline
    minus holes, even-odd within each ring, painted in the field list's order.
    Drawn as an INDEX rather than in colours because two fields may share a
    fill, and a colour match a field did not earn is precisely the error this
    whole exercise is about.
    """
    idx = np.full((h, w), SUBSTRATE, dtype=int)
    # CONTRACT 1.10: a mark is indexed as the FIELD whose cluster it was found
    # in, because that is what the ground truth says is there. A component mark
    # is a region of that cluster and drawing it in its own colour does not stop
    # it being that cluster's ink -- indexing it otherwise cost `64_Kamagra`'s
    # highlight 0.964 -> 0.882 for a mark it draws correctly.
    #
    # A HOLE mark is the other case and is deliberately left to disagree: the
    # hole is enclosed BACKGROUND, so the truth calls it substrate, and drawing
    # a mark there is a real departure from what the segmentation saw.
    # MARKS_DECISION.md said so before any of this was built -- "the +9.937 is
    # not carried forward" -- and the figure has to show it rather than keep the
    # gain that cutting alone earned.
    front_fields = [field for field in (spec.get("fields") or [])
                    if field.get("surface", "front") == "front"]
    for n, field in enumerate(front_fields):
        for part in field.get("parts") or []:
            # `part_region` and not a polygon fill, so this instrument and the
            # spec's own raster cut holes the same way. Contract 1.8. It also
            # puts each vertex back on the pixel it was traced from, which is
            # worth 1.39 points of `truth_agreement` here -- see `part_region`.
            region = part_region(part, w, h)
            if region is not None:
                idx[np.asarray(region)] = n
    # AFTER the fields, and the order is not cosmetic. `rasterise()` paints marks
    # last because a mark is printed ON a surface, and the driver builds them in
    # front of every field. Painting them FIRST here let a field overwrite them,
    # so the index map and the target image disagreed about who owned those
    # pixels: `157-min`'s type field then had the mark's colour inside a region
    # labelled as the field, and its `region_colour_gap` read 0.3868 against
    # 0.1376. Three readers, one order.
    for mark in sorted(spec.get("marks") or [], key=lambda m: m.get("z", 0)):
        for part in drawable_mark_parts(mark):
            region = part_region(part, w, h)
            if region is None:
                continue
            # ALWAYS its own index, never its field's. Indexing a component
            # mark as the field whose cluster it came from was tried first, to
            # make it agree with a ground truth that is keyed by field -- and it
            # is now pointless and harmful at once. Pointless because
            # `truth_agreement` and `verify()` both drop a mark's area outright;
            # harmful because `region_colour_gap` reads this map, so the mark's
            # OWN colour then landed inside its field's region and was averaged
            # into it. Measured: `157_Valium`'s type field read **0.3868**
            # against 0.1376 for a mark drawn exactly where it belongs.
            idx[np.asarray(region)] = MARK
    return idx


def truth_index(lab: np.ndarray, named: dict, roles: list):
    """Which region the REFERENCE has at each pixel, indexed like the spec.

    `roles` is the spec's own field order, so index *n* means the same thing on
    both sides. A printed cluster the spec emitted nothing for gets its own
    negative code, which matches no spec index and never can — that is the whole
    point: print the spec declined to represent has to read as disagreement
    rather than as board.

    Returns (truth, scored, printed, unrepresented) where `printed` maps every
    non-board, non-type role to its label and `scored` drops the type cluster.
    """
    truth = np.full(lab.shape, SUBSTRATE, dtype=int)

    printed = {role: g["label"] for role, g in named.items()
               if g is not None and role not in ("substrate", "type")}

    for n, role in enumerate(roles):
        group = named.get(role)
        if group is not None:
            truth[lab == group["label"]] = n

    unrepresented = [r for r in printed if r not in roles]
    for k, role in enumerate(unrepresented):
        truth[lab == printed[role]] = -2 - k          # never equals a spec index

    scored = np.ones(lab.shape, bool)
    if named.get("type") is not None:
        scored &= lab != named["type"]["label"]
    return truth, scored, printed, unrepresented


def truth_from_labels(folder: Path, flat_rgb: np.ndarray, lab: np.ndarray,
                      named: dict, roles: list):
    """The reference's PRINT, as a person classified it, indexed like the spec.

    `truth_index` above takes a whole non-substrate CLUSTER to be print. That was
    the only definition available before Phase A, and it is wrong in both
    directions at once: it counts Provigil's box lid, the table under it and a
    stock-agency watermark as design the spec failed to draw, while a printed
    field below the enumeration floor -- Imovane's 0.67% blue rule -- is invisible
    to the fitter and so never appears on either side.

    This reads `print_truth.json` instead. Truth is exactly the components a
    person called `print`; the scored area is the board plus those components,
    so an object, a letterform, a logo, a photograph and a surface counted twice
    are all neither drawn nor counted as a miss.

    Returns (truth, scored, missing_roles).
    """
    truth = np.full(lab.shape, SUBSTRATE, dtype=int)
    doc = load_truth(folder)
    if doc is None:
        raise SystemExit(f"{folder.name}: {TRUTH_NAME} absent; run label_print.py")
    label_of = {c["key"]: c.get("class") for c in doc["components"]}
    min_px = int(float(doc["enumerate_min_frac"]) * lab.size)

    by_role: dict[str, np.ndarray] = {}
    candidate = np.zeros(lab.shape, bool)
    for role, mask, _group in design_component_sources(flat_rgb, lab, named):
        candidate |= mask
        keep = np.zeros(lab.shape, bool)
        for i, part in enumerate(components(mask, min_px)):
            if label_of.get(f"{role}#{i}") == "print":
                keep |= part
        if keep.any():
            by_role[role] = keep

    for n, role in enumerate(roles):
        if role in by_role:
            truth[by_role[role]] = n
    missing = [r for r in by_role if r not in roles]
    for k, role in enumerate(missing):
        truth[by_role[role]] = -2 - k

    printed = np.zeros(lab.shape, bool)
    for m in by_role.values():
        printed |= m
    scored = ~candidate | printed
    return truth, scored, missing


def read_spec(folder: Path, name: str) -> dict:
    """A spec by filename, with the same ring repair `load_design` applies.

    Needed so `design_spec.v01.json` -- the pre-Phase-B measurement, preserved
    beside the new one -- can be scored by exactly the same instrument. Comparing
    a before and an after through two different loaders would measure the
    loaders.
    """
    if name == "design_spec.json":
        return load_design(STEM_BY_FOLDER[folder.name])
    spec = json.loads((folder / name).read_text(encoding="utf-8"))
    for field in spec.get("fields") or []:
        for part in field.get("parts") or []:
            outline = part.get("outline") or []
            if len(outline) >= 4:
                fixed = simple_ring(outline)
                if len(fixed) != len(outline):
                    part["outline"] = [list(q) for q in fixed]
                    part["simplified_from"] = len(outline)
            part["holes"] = [
                [list(q) for q in (simple_ring(ring) if len(ring) >= 4 else ring)]
                for ring in (part.get("holes") or [])]
    return spec


def coverage(folder: Path, spec_name: str = "design_spec.json") -> dict:
    """Both print figures for one carton, plus what they were computed over."""
    stem = STEM_BY_FOLDER[folder.name]
    # The canonical loader, so the regions scored here are the regions every
    # consumer receives -- self-crossing outlines repaired, spec on disk
    # untouched. `simplified_parts` reports how many that was.
    spec = read_spec(folder, spec_name)
    flat, labels, named, meta, source = segment(folder)
    w, h = flat.width, flat.height
    lab = labels.reshape(h, w)
    total = float(w * h)

    front_fields = [
        field for field in (spec.get("fields") or [])
        if field.get("surface", "front") == "front"
    ]
    roles = [field["role"] for field in front_fields]
    s_idx = spec_index(spec, w, h)
    t_idx, scored, printed, unrepresented = truth_index(lab, named, roles)

    type_pct = (100.0 * float((lab == named["type"]["label"]).sum()) / total
                if named.get("type") else 0.0)

    # The mark exclusion belongs here too, and for the same reason it belongs to
    # `truth_agreement`: this figure compares the spec's fields against RAW
    # clusters by index, and a mark matches no cluster by construction. Left in,
    # it read 52.36% against 52.66% -- a third of a point of pure category error.
    mark_mask = np.zeros(lab.shape, bool)
    for mark in (spec.get("marks") or []):
        for part in drawable_mark_parts(mark):
            region = part_region(part, w, h)
            if region is not None:
                mark_mask |= np.asarray(region)
    scored = scored & ~mark_mask

    ref_print = (t_idx != SUBSTRATE) & scored
    spec_print = (s_idx != SUBSTRATE) & scored
    union = ref_print | spec_print
    agreement = float((s_idx == t_idx)[union].mean()) if union.any() else None

    # The same question asked of the hand-made ground truth instead of the raw
    # clusters -- see truth_from_labels. Reported BESIDE the cluster figure, not
    # in place of it: the cluster figure is what the audit recorded and what the
    # 52.99% mean refers to, and silently redefining it would make the two
    # incomparable at exactly the moment the comparison matters.
    lt_idx, lt_scored, lt_missing = truth_from_labels(
        folder, np.asarray(flat), lab, named, roles)
    # CONTRACT 1.10: a drawn mark leaves the scored area, in BOTH directions.
    #
    # This figure compares the spec's FIELDS against the components a person
    # called `print`, by region identity. A mark is deliberately neither: it has
    # its own class, its own decision and its own index, and `truth_from_labels`
    # counts only `print`. Scoring one against a field-indexed ground truth is a
    # category error, and it was measured being one -- `230_Slimex`, whose only
    # spec content is two approved marks, read **0.00%**, and `272_Valium_Brand`
    # 54.31%, because every pixel they draw was compared with a truth that said
    # substrate. Widening the ground truth to admit approved marks was tried and
    # recovered 0.20 points of the group, because the indices still cannot match
    # for a mark whose role is not a field at all.
    #
    # Excluding it is the honest treatment and it says something worth saying:
    # **`truth_agreement` cannot judge a mark.** Excluded on the CUT side too,
    # so cutting a hole and drawing into it is neutral here rather than banking
    # the gain that cutting alone earned -- which is exactly what
    # MARKS_DECISION.md warned: "the +9.937 is not carried forward".
    #
    # What judges a mark is the render: `render~spec`, `render~ref` and
    # `region_colour_gap`, plus looking at it. `mark_pct` below keeps its size
    # visible so its absence from this figure cannot be read as its absence from
    # the carton.
    lt_scored = lt_scored & ~mark_mask
    lt_ref = (lt_idx != SUBSTRATE) & lt_scored
    lt_spec = (s_idx != SUBSTRATE) & lt_scored
    lt_union = lt_ref | lt_spec
    truth_agreement = (float((s_idx == lt_idx)[lt_union].mean())
                       if lt_union.any() else None)

    # What the spec draws OUTSIDE the printed design -- over a blister, a box
    # lid, the table, a letterform, a logo, a photograph, or the board counted
    # twice.
    #
    # It needs its own figure because `truth_agreement` cannot see it: the
    # scored area is the board plus the labelled print, so a polygon laid over
    # the blister falls outside it and costs nothing. That exclusion is the
    # right convention -- what the carton prints under a blister is not in the
    # photograph, so those pixels are evidence about neither side, the same
    # reason the glyph rim and the region seam are excluded in design_qa. But it
    # makes the one thing Phase B removes invisible to the agreement figure, and
    # a fix nothing can measure is a fix nobody can defend.
    off_print = (s_idx != SUBSTRATE) & ~lt_scored & ~mark_mask

    recorded = ((spec.get("verification") or {}).get("iou_by_field") or {})
    weighted = weight = 0.0
    per_role = {}
    for role, label in printed.items():
        share = float((lab == label).sum()) / total
        iou = recorded.get(role)
        iou = 0.0 if iou is None else float(iou)
        per_role[role] = {"face_pct": round(100 * share, 2),
                          "iou": iou, "in_spec": role in roles}
        weighted += share * iou
        weight += share
    print_iou = (weighted / weight) if weight else None

    return {
        "folder": folder.name,
        "sku": stem,
        "fields": len(roles),
        "parts": sum(len(f.get("parts") or []) for f in front_fields),
        "vertices": sum(len(p["outline"]) for f in front_fields
                        for p in (f.get("parts") or [])),
        "simplified_parts": sum(1 for f in front_fields
                                for p in (f.get("parts") or [])
                                if "simplified_from" in p),
        "pixel_agreement": (spec.get("verification") or {}).get("pixel_agreement"),
        "print_pct": round(100 * float(ref_print.sum()) / total, 2),
        "spec_print_pct": round(100 * float(spec_print.sum()) / total, 2),
        "type_pct": round(type_pct, 2),
        "print_agreement": None if agreement is None else round(agreement, 4),
        "truth_agreement": (None if truth_agreement is None
                            else round(truth_agreement, 4)),
        "truth_print_pct": round(100 * float(lt_ref.sum()) / total, 2),
        "spec_off_print_pct": round(100 * float(off_print.sum()) / total, 2),
        "truth_missing_roles": lt_missing,
        "print_iou": None if print_iou is None else round(print_iou, 4),
        "printed_roles": per_role,
        "unrepresented_roles": unrepresented,
        # Cheap proof that this segmentation is the one the spec was fitted to.
        # A partition that had drifted would make every figure above a
        # comparison between two different measurements.
        "substrate_reproducible": _hex(named["substrate"]["colour"]) == spec.get("substrate"),
        "source_image": source,
        "reference_aspect": round(h / w, 4),
        "catalogue_aspect": (meta.get("design_measurement") or {}).get("catalogue_aspect"),
    }


def control(folder: Path) -> dict:
    """Does the figure tell a blank spec from a perfect one?

    Both ends, on the same carton and the same segmentation:

      blank   every field removed. Nothing is drawn, so nothing can agree, and
              the figure must read 0.0 wherever the reference prints anything.
      perfect the spec replaced by the segmentation itself — the best any spec
              of this vocabulary could possibly do. Must read 1.0.

    A figure that cannot separate those two is not measuring what it claims,
    which is exactly the fault it exists to correct.
    """
    flat, labels, named, meta, source = segment(folder)
    w, h = flat.width, flat.height
    lab = labels.reshape(h, w)

    t_idx, scored, printed, _ = truth_index(lab, named, [])
    s_idx = np.full(lab.shape, SUBSTRATE, dtype=int)
    union = ((t_idx != SUBSTRATE) | (s_idx != SUBSTRATE)) & scored
    blank = float((s_idx == t_idx)[union].mean()) if union.any() else None

    t_idx, scored, printed, _ = truth_index(lab, named, sorted(printed))
    s_idx = t_idx.copy()                       # the perfect spec: the truth itself
    union = ((t_idx != SUBSTRATE) | (s_idx != SUBSTRATE)) & scored
    perfect = float((s_idx == t_idx)[union].mean()) if union.any() else None

    return {"folder": folder.name, "blank": blank, "perfect": perfect,
            "print_pct": round(100 * float(((t_idx != SUBSTRATE) & scored).sum())
                               / (w * h), 2)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sku", help="one SKU stem; default is every design SKU")
    parser.add_argument("--control", action="store_true",
                        help="also run the blank-spec / perfect-spec check")
    parser.add_argument("--out",
                        help="write the rows as JSON here (writes nothing without it)")
    parser.add_argument("--spec", default="design_spec.json",
                        help="which spec file to score; use design_spec.v01.json "
                             "for the measurement preserved before Phase B")
    args = parser.parse_args()

    stems = ([args.sku] if args.sku
             else sorted(FOLDER_BY_STEM, key=lambda s: int(s.split("-")[0])))

    rows = []
    print(f"{'SKU':9s} {'folder':24s} {'fld':>3s} {'prt':>3s} "
          f"{'pixel_agr':>10s} {'print_agr':>10s} {'truth_agr':>10s} "
          f"{'print%':>6s} {'truth%':>6s} {'off%':>7s}  not in the spec")
    for stem in stems:
        row = coverage(TEMPLATES_DIR / FOLDER_BY_STEM[stem], args.spec)
        rows.append(row)
        old, new, tru = (row["pixel_agreement"], row["print_agreement"],
                         row["truth_agreement"])
        print(f"{stem:9s} {row['folder']:24s} {row['fields']:3d} {row['parts']:3d} "
              f"{(f'{100 * old:.2f}%' if old is not None else '--'):>10s} "
              f"{(f'{100 * new:.2f}%' if new is not None else 'n/a'):>10s} "
              f"{(f'{100 * tru:.2f}%' if tru is not None else 'n/a'):>10s} "
              f"{row['print_pct']:6.2f} {row['truth_print_pct']:6.2f} "
              f"{row['spec_off_print_pct']:7.2f}  "
              f"{','.join(row['truth_missing_roles']) or '-'}")

    old = [r["pixel_agreement"] for r in rows if r["pixel_agreement"] is not None]
    new = [r["print_agreement"] for r in rows if r["print_agreement"] is not None]
    tru = [r["truth_agreement"] for r in rows if r["truth_agreement"] is not None]
    if old and new:
        print(f"\nspec scored: {args.spec}   over {len(rows)} carton(s)")
        print(f"  pixel_agreement {100 * sum(old) / len(old):6.2f}%   the whole face, "
              f"and the face is 87-96% board")
        print(f"  print_agreement {100 * sum(new) / len(new):6.2f}%   over the raw "
              f"clusters, which count the table and the box lid as print")
        if tru:
            print(f"  truth_agreement {100 * sum(tru) / len(tru):6.2f}%   over what a "
                  f"person classified as printed design")
        off = [r["spec_off_print_pct"] for r in rows]
        print(f"  drawn off print {sum(off) / len(off):6.2f}%   of a face, laid over "
              f"objects, type, logos, photographs or the board")

    if args.control:
        print(f"\n{'folder':24s} {'blank spec':>10s} {'perfect spec':>12s} {'print%':>6s}")
        failed = []
        for stem in stems:
            c = control(TEMPLATES_DIR / FOLDER_BY_STEM[stem])
            blank = "n/a" if c["blank"] is None else f"{100 * c['blank']:.1f}%"
            perfect = "n/a" if c["perfect"] is None else f"{100 * c['perfect']:.1f}%"
            print(f"{c['folder']:24s} {blank:>10s} {perfect:>12s} {c['print_pct']:6.2f}")
            if c["blank"] not in (0.0, None) or c["perfect"] not in (1.0, None):
                failed.append(c["folder"])
        print("\nblank spec scores 0.0 and perfect spec 1.0 on every carton"
              if not failed else f"\nDISCRIMINATION FAILED on: {failed}")

    if args.out:
        Path(args.out).write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
        print(f"\n{args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
