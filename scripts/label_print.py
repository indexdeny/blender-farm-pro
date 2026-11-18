"""Phase A — separate what is PRINTED on the carton from what is lying in front of it.

    python scripts/label_print.py --aid OUT_DIR          # draw the labelling aids
    python scripts/label_print.py --init                 # write/merge print_truth.json
    python scripts/label_print.py --ceiling              # what the vocabulary could reach

WHY THIS EXISTS. The tracer currently admits anything that runs off the face, reads
as a block, or fills its own bounding box. None of those tests can tell a printed
panel from a blister lying across the carton, and on at least eight of the 28
references one gets traced as design: Kamagra's teal pouch (seven parts), Cialis
Professional's loose tablet, Waklert's and Xanax Pfizer's blisters, Provigil's box
lid and the table under it. Two more references carry a photograph of a person, and
the tracer returns ragged blobs -- noise, not design.

No threshold fixes that, because the distinction is not geometric. It is a fact
about the photograph, and a person has to state it once per component. This script
makes stating it cheap and makes the statement durable.

WHAT A LABEL IS ATTACHED TO. `measure_reference_face.segment()` is deterministic --
fixed k-means seeding, fixed merge order -- so for a given photograph and a given
set of face corners the partition is reproducible, and a component can be named by
its role and its rank by area inside that role. That is exactly the order
`fit_design_spec.components()` iterates, so a label maps one-to-one onto what the
fitter sees.

It follows that a label is only valid for the corners it was made against.
`print_truth.json` records those corners and `verify()` refuses when they have
moved -- silently re-using a stale label would put the blister back in the spec
with nothing in the log to say so, which is the failure mode this whole phase
exists to remove.

CLASSES. Six, and the boundaries are what matter:

    print            ink on the carton. Goes into the spec.
    object           a thing in the photograph that is not the printed face:
                     a tablet, a pouch, a blister, the box lid, the table, the
                     background. Never goes into the spec.
    type             letterforms. The renderer draws every string from the
                     manifest, so a spec carrying these would print the
                     reference's words -- already the reason `is_design_field`
                     exists.
    unrepresentable  printed, and this vocabulary cannot hold it: a photographic
                     insert, a continuous-tone gradient, speckle no outline
                     describes. Recorded WITH A REASON rather than traced into
                     noise or dropped in silence, so a blank area on the carton
                     is a statement instead of an omission.
    blend            not a design element of its own -- one printed surface
                     split into two components by a gradient or by an
                     antialiased edge. Two shapes, one cause:

                     the BOARD, split off the substrate cluster by lighting.
                     `MIN_FILL_CONTRAST` drops these at an 0.08 colour distance
                     and Xanax Pfizer's shaded board sits at 0.090, so it is
                     kept and traced as a field covering 26.6% of the face.

                     a FIELD's own rim, the antialiased boundary between it and
                     the board, which lands in a neighbouring cluster. Calling
                     one of those `print` emits a second field with the same
                     outline as the first, and since `rasterise()` paints in
                     spec order the rim then ERASES the field it came from:
                     Lexotanil's two hexagons scored IoU 0.0 that way, and
                     Modalert's red rule, Tapentadol's block and Hydrocodone's
                     panel all had the same duplicate.

                     Either way it is the same surface twice, and counting it as
                     print overstates the ceiling and breaks the spec.
    mark             a manufacturer logo, wordmark or holographic element.
                     Printed, and perfectly representable -- it is out by the
                     OWNER'S decision, not by any limit of the vocabulary, and
                     those are different facts about a blank area. Kept apart
                     from `unrepresentable` because Phase G's `design.marks[]`
                     needs exactly this set, and re-deriving it later from a
                     reason string would be the second implementation this
                     project keeps paying for. Requires a reason naming it.

Reads only, except for `--init`, which writes `print_truth.json` into each folder
and MERGES: an existing label is never overwritten, a component that has appeared
is added as `unclassified`, and one that has vanished is kept and flagged so its
disappearance is visible rather than silent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.design_group import FOLDER_BY_STEM, TEMPLATES_DIR  # noqa: E402
from scripts.fit_design_spec import (  # noqa: E402
    MIN_HOLE_FRAC, TRUTH_NAME, components, enclosed_background, load_truth,
)
from scripts.measure_reference_face import SAME_SURFACE_MAX, _hex, segment  # noqa: E402
from scripts.reference_regions import recovered_records  # noqa: E402

#: folder name -> catalogue SKU stem. `FOLDER_BY_STEM` runs the other way and
#: looking a folder up in it returns None for every folder, which is how the
#: first run of this script came back with `"sku": null` on all 28.
STEM_BY_FOLDER = {folder: stem for stem, folder in FOLDER_BY_STEM.items()}

#: The group in catalogue order. Sorting folder names as text puts `133_Ambien`
#: before `59_Cialis`, which makes every listing this script prints unreadable
#: against every other report in the project.
FOLDERS = sorted(STEM_BY_FOLDER, key=lambda n: int(n.split("_")[0]))

CLASSES = ("print", "object", "type", "unrepresentable", "mark", "blend",
           "unclassified")

#: The second population, added for contract 1.8: the HOLES inside a component
#: classified `print`. Two classes, and they are told apart by looking:
#:
#:     window     the field is not there. Board, or another printed field: the
#:                statement is about THIS field's absence, and what shows through
#:                is whatever the paint order puts behind it. Adderall's brand
#:                winds around a window covering 44.4% of the face, and filling
#:                it is what made that one part enclose 9.07 times its own ink;
#:                Kamagra's teal has a window where the salmon dosage badge sits.
#:                The only class that is CUT.
#:     lettering  the reference's own type, reversed out of the field. Board
#:                shows through it on the photograph for the same reason it shows
#:                through a window, and NOTHING in the segmentation tells them
#:                apart -- both are board.
#:     mark       a manufacturer's logo or a regulatory symbol sitting in the
#:                field. Not cut either, and separate from `lettering` for the
#:                same reason the component vocabulary keeps `mark` apart from
#:                `type`: the owner excluded logos by decision, not because a
#:                renderer draws them from a string. Ativan's Pfizer oval,
#:                Adderall's C-II, Inderal's LCI roundel.
#:     object     something lying in front of the carton, enclosed by a component
#:                that reached around it. Not cut: the field continues underneath,
#:                and what the photograph shows there is not the carton. All
#:                twelve of `340_Xanax_Pfizer`'s holes are blister foil, reached
#:                by the one-pixel thread that panel is already known for.
#:     blend      an edge or a gradient, not a feature: the lit top edge of a
#:                filled box, a hairline at the carton's own boundary. Not cut,
#:                for the same reason the component class of that name exists.
#:
#: A person, because three instruments were tried and all three failed on real
#: cartons. The share of the hole lying in a component already classified `type`
#: separates 45 of 238 and misses the rest: Cialis's "1" is one stroke of "10 mg"
#: and lands in the SUBSTRATE cluster, which is never enumerated. The reference's
#: own OCR word boxes cover 131 and read NOTHING on `344_Modafinil_Generic`,
#: whose ten holes spell "Modalert (R) 200" reversed out of a purple band. Size
#: is the escape this project already removed once.
#:
#: The stake is the invariant, not the metric. `59-min` is a 20 mg Cialis and its
#: reference photograph is a 10 mg pack; `344-min` is Modafinil Generic and its
#: photograph is Modalert 200. Cutting those holes prints the other package's
#: dosage and brand on our carton, in board, in the shape the photograph has --
#: which is the same act as printing a plausible LOT, and this driver already
#: refuses that.
HOLE_CLASSES = ("window", "lettering", "mark", "object", "blend",
                "unclassified")

#: One hue per hole class, for the aid only.
HOLE_TINT = {"window": (40, 170, 90), "lettering": (220, 90, 40),
             "mark": (196, 150, 30), "object": (196, 84, 30),
             "blend": (150, 150, 150), "unclassified": (222, 60, 60)}

#: Enumerate down to this share of the face. Deliberately below
#: `fit_design_spec.MIN_REGION_FRAC` (0.008), so the labelling covers components
#: the fitter currently drops as well as the ones it keeps -- the ceiling has to
#: count print the vocabulary is failing to reach, not only print it reaches for.
#: Anything smaller is pooled per role as `residue` and reported, not labelled:
#: at 0.001 the group produces components in the thousands and hand-labelling
#: stops being possible, which would defeat the point.
ENUMERATE_MIN_FRAC = 0.001

FONT = PROJECT_ROOT / "05_assets" / "blender" / "fonts" / "DejaVuSans-Bold.ttf"

#: One hue per class, for the aid only.
TINT = {"print": (34, 139, 176), "object": (196, 84, 30), "type": (120, 116, 108),
        "unrepresentable": (150, 60, 150), "mark": (196, 150, 30),
        "blend": (150, 150, 150), "unclassified": (222, 60, 60)}


def enumerate_components(folder: Path):
    """Every component of every non-substrate cluster, largest first within its role.

    Returns (flat, records, residue) where a record carries the component's key,
    its role, its share of the face, its bounding box and centroid, and the mask
    itself for drawing. `residue` is the share of each role too small to enumerate.
    """
    flat, labels, named, meta, source = segment(folder)
    w, h = flat.width, flat.height
    lab = labels.reshape(h, w)
    total = float(w * h)
    min_px = int(ENUMERATE_MIN_FRAC * total)

    records, residue = [], {}
    substrate_label = named["substrate"]["label"]
    for role in sorted(named):
        group = named.get(role)
        if group is None or group["label"] == substrate_label:
            continue
        mask = lab == group["label"]
        parts = components(mask, min_px)
        covered = sum(int(p.sum()) for p in parts)
        residue[role] = round(100.0 * (int(mask.sum()) - covered) / total, 3)
        for i, part in enumerate(parts):
            ys, xs = np.nonzero(part)
            records.append({
                "key": f"{role}#{i}",
                "role": role,
                "fill": _hex(group["colour"]),
                "area_pct": round(100.0 * float(part.sum()) / total, 3),
                "bbox_uv": [round(float(xs.min()) / w, 4), round(float(ys.min()) / h, 4),
                            round(float(xs.max()) / w, 4), round(float(ys.max()) / h, 4)],
                "centroid_uv": [round(float(xs.mean()) / w, 4), round(float(ys.mean()) / h, 4)],
                "_mask": part,
            })

    # Global k=4 is kept as the stable base partition. Printed regions it put
    # inside the substrate are appended afterwards, so every legacy role/key
    # above retains its identity and existing print_truth labels remain valid.
    for group in recovered_records(np.asarray(flat), lab, named, SAME_SURFACE_MAX):
        role = group["role"]
        mask = group["mask"]
        parts = components(mask, min_px)
        covered = sum(int(part.sum()) for part in parts)
        residue[role] = round(100.0 * (int(mask.sum()) - covered) / total, 3)
        for i, part in enumerate(parts):
            ys, xs = np.nonzero(part)
            records.append({
                "key": f"{role}#{i}",
                "role": role,
                "fill": group["fill"],
                "area_pct": round(100.0 * float(part.sum()) / total, 3),
                "bbox_uv": [round(float(xs.min()) / w, 4),
                            round(float(ys.min()) / h, 4),
                            round(float(xs.max()) / w, 4),
                            round(float(ys.max()) / h, 4)],
                "centroid_uv": [round(float(xs.mean()) / w, 4),
                                round(float(ys.mean()) / h, 4)],
                "_mask": part,
            })
    return flat, records, residue, named, meta, source


def enumerate_holes(folder: Path, records, known: dict):
    """Every hole of every component classified `print`, largest first.

    A hole in a component the label already dropped is not a question anyone has
    to answer -- the component is not in the spec, so neither is its interior.
    Keyed `role#i/hole#j` off the component's own key, so a hole is named by
    something already stable rather than by a second enumeration of its own.
    """
    out = []
    for r in records:
        if known.get(r["key"]) != "print":
            continue
        part = r["_mask"]
        h, w = part.shape
        total = float(w * h)
        min_px = int(MIN_HOLE_FRAC * total)
        for j, hole in enumerate(enclosed_background(part)):
            if hole.sum() < min_px:
                continue
            ys, xs = np.nonzero(hole)
            out.append({
                "key": f'{r["key"]}/hole#{j}',
                "of": r["key"],
                "area_pct": round(100.0 * float(hole.sum()) / total, 3),
                "bbox_uv": [round(float(xs.min()) / w, 4), round(float(ys.min()) / h, 4),
                            round(float(xs.max()) / w, 4), round(float(ys.max()) / h, 4)],
                "centroid_uv": [round(float(xs.mean()) / w, 4), round(float(ys.mean()) / h, 4)],
                "_mask": hole,
            })
    return out


def truth_path(folder: Path) -> Path:
    return folder / TRUTH_NAME


def init(folder: Path) -> dict:
    """Write or MERGE `print_truth.json`. An existing label is never overwritten."""
    flat, records, residue, _named, meta, source = enumerate_components(folder)
    previous = load_truth(folder) or {}
    old = {c["key"]: c for c in previous.get("components", [])}

    out = []
    for r in records:
        prior = old.get(r["key"], {})
        out.append({
            "key": r["key"], "role": r["role"], "fill": r["fill"],
            "area_pct": r["area_pct"], "bbox_uv": r["bbox_uv"],
            "centroid_uv": r["centroid_uv"],
            "class": prior.get("class", "unclassified"),
            **({"reason": prior["reason"]} if prior.get("reason") else {}),
            **({"note": prior["note"]} if prior.get("note") else {}),
        })
    known = {c["key"]: c.get("class", "unclassified") for c in out}
    holes_old = {c["key"]: c for c in previous.get("holes", [])}
    holes = []
    for r in enumerate_holes(folder, records, known):
        prior = holes_old.get(r["key"], {})
        holes.append({
            "key": r["key"], "of": r["of"], "area_pct": r["area_pct"],
            "bbox_uv": r["bbox_uv"], "centroid_uv": r["centroid_uv"],
            "class": prior.get("class", "unclassified"),
            **({"reason": prior["reason"]} if prior.get("reason") else {}),
        })
    hseen = {r["key"] for r in holes}
    for key, prior in holes_old.items():
        if key not in hseen:
            prior = dict(prior)
            prior["vanished"] = True
            holes.append(prior)

    seen = {r["key"] for r in records}
    # A label whose component is gone is KEPT and flagged. Deleting it would erase
    # the evidence that the partition moved under it.
    for key, prior in old.items():
        if key not in seen:
            prior = dict(prior)
            prior["vanished"] = True
            out.append(prior)

    doc = {
        "schema": "print_truth/1",
        "sku": STEM_BY_FOLDER.get(folder.name),
        "source_image": source,
        # A label is only valid for the corners it was made against.
        "front_face_px": meta.get("front_face_px"),
        "rectified_px": [flat.width, flat.height],
        "enumerate_min_frac": ENUMERATE_MIN_FRAC,
        "residue_pct_by_role": residue,
        "classes": list(CLASSES),
        "components": out,
        # Contract 1.8's second population. `hole_min_frac` travels with it for
        # the same reason `enumerate_min_frac` does: both sides have to
        # enumerate identically, and a floor read out of the truth file cannot
        # drift from the one the labelling was made at.
        "hole_classes": list(HOLE_CLASSES),
        "hole_min_frac": MIN_HOLE_FRAC,
        "holes": holes,
    }
    truth_path(folder).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def set_classes(folder: Path, assignments: dict, rest: str | None) -> dict:
    """Classify components. `assignments` maps key -> "class" or "class:reason".

    Bulk, because the group holds 664 components and most of them are one thing:
    on a carton whose face is mostly white type, naming the four exceptions and
    sweeping the rest is the difference between a command and an afternoon. The
    sweep is explicit -- `--rest` has no default -- so nothing is classified by
    omission.
    """
    doc = load_truth(folder)
    if doc is None:
        raise SystemExit(f"{folder.name}: run --init first")
    by_key = {c["key"]: c for c in doc["components"]}
    # Holes are keyed `role#i/hole#j` and cannot collide with a component key,
    # so one dict serves both populations and the caller never has to say which
    # it means. Their vocabulary is different, and the check below reads the
    # vocabulary off the key.
    holes_by_key = {c["key"]: c for c in doc.get("holes", [])}
    unknown = [k for k in assignments if k not in by_key and k not in holes_by_key]
    if unknown:
        raise SystemExit(f"{folder.name}: no such component(s): {' '.join(unknown)}")

    for key, value in assignments.items():
        cls, _, reason = value.partition(":")
        if key in holes_by_key:
            if cls not in HOLE_CLASSES[:-1]:
                raise SystemExit(
                    f"{folder.name}: {key}={cls} is not one of {HOLE_CLASSES[:-1]}")
            hole = holes_by_key[key]
            hole["class"] = cls
            if reason:
                hole["reason"] = reason
            continue
        if cls not in CLASSES[:-1]:
            raise SystemExit(f"{folder.name}: {key}={cls} is not one of {CLASSES[:-1]}")
        comp = by_key[key]
        comp["class"] = cls
        if reason:
            comp["reason"] = reason
        elif cls not in ("unrepresentable", "mark"):
            comp.pop("reason", None)
    if rest:
        # Same "class:reason" form as --set, because the sweep lands on
        # `unrepresentable` and `mark` too, and both require a reason.
        rest_cls, _, rest_reason = rest.partition(":")
        pool = (doc.get("holes", []) if rest_cls in HOLE_CLASSES[:-1]
                else doc["components"])
        if rest_cls not in CLASSES[:-1] and rest_cls not in HOLE_CLASSES[:-1]:
            raise SystemExit(f"--rest {rest_cls} is not one of "
                             f"{CLASSES[:-1]} or {HOLE_CLASSES[:-1]}")
        for comp in pool:
            if not comp.get("vanished") and comp.get("class") == "unclassified":
                comp["class"] = rest_cls
                if rest_reason:
                    comp["reason"] = rest_reason
    truth_path(folder).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def verify(folder: Path) -> tuple[bool, str]:
    """Is this folder's truth usable — present, complete, and made against these corners?"""
    doc = load_truth(folder)
    if doc is None:
        return False, "print_truth.json absent"
    _flat, _labels, _named, meta, _source = segment(folder)
    if doc.get("front_face_px") != meta.get("front_face_px"):
        return False, "labelled against different front_face_px — re-run --init and re-label"
    bad = [c["key"] for c in doc["components"]
           if not c.get("vanished") and c.get("class") not in CLASSES[:-1]]
    if bad:
        return False, f"{len(bad)} component(s) still unclassified: {' '.join(bad[:6])}"
    missing = [c["key"] for c in doc["components"]
               if c.get("class") in ("unrepresentable", "mark") and not c.get("reason")]
    if missing:
        return False, f"unrepresentable/mark without a reason: {' '.join(missing)}"
    if "holes" not in doc:
        return False, "no `holes` section — re-run --init for contract 1.8"
    bad = [c["key"] for c in doc.get("holes", [])
           if not c.get("vanished") and c.get("class") not in HOLE_CLASSES[:-1]]
    if bad:
        return False, f"{len(bad)} hole(s) still unclassified: {' '.join(bad[:6])}"
    return True, "ok"


def aid(folder: Path, out_dir: Path, holes_only: bool = False) -> Path:
    """Draw the face, and the face with every component tinted and named.

    `holes_only` draws the second population instead: the holes inside the
    components already called `print`, tinted and named in their own vocabulary.
    A hole is told from a window BY LOOKING -- the two are the same pixels to
    every instrument tried -- so it has to be legible at the size a letter is.
    """
    flat, records, residue, _named, _meta, _source = enumerate_components(folder)
    doc = load_truth(folder) or {}
    known = {c["key"]: c.get("class", "unclassified") for c in doc.get("components", [])}
    w, h = flat.width, flat.height

    if holes_only:
        records = enumerate_holes(folder, records, known)
        known = {c["key"]: c.get("class", "unclassified") for c in doc.get("holes", [])}
        palette = HOLE_TINT
    else:
        palette = TINT

    over = flat.convert("RGB").copy()
    tint = np.asarray(over).astype(float)
    for r in records:
        col = np.array(palette.get(known.get(r["key"], "unclassified"),
                                   palette["unclassified"]), dtype=float)
        m = r["_mask"]
        tint[m] = 0.45 * tint[m] + 0.55 * col
    over = Image.fromarray(tint.astype("uint8"))

    d = ImageDraw.Draw(over)
    f = ImageFont.truetype(str(FONT), max(13, int(w / 62)))
    for r in records:
        x = r["centroid_uv"][0] * w
        y = r["centroid_uv"][1] * h
        txt = f'{r["key"]} {r["area_pct"]:.2f}%'
        box = d.textbbox((x, y), txt, font=f, anchor="mm")
        d.rectangle([box[0] - 5, box[1] - 3, box[2] + 5, box[3] + 3], fill=(255, 255, 255))
        d.text((x, y), txt, font=f, fill=(15, 15, 20), anchor="mm")
        u0, v0, u1, v1 = r["bbox_uv"]
        d.rectangle([u0 * w, v0 * h, u1 * w, v1 * h], outline=(20, 20, 24), width=2)

    pad, head = 16, 46
    card = Image.new("RGB", (w + 2 * pad, head + h * 2 + pad * 3), (250, 250, 248))
    cd = ImageDraw.Draw(card)
    cd.text((pad, 12), f"{folder.name}   ({STEM_BY_FOLDER.get(folder.name)})   "
                       f"{len(records)} {'hole' if holes_only else 'component'}(s)",
            font=ImageFont.truetype(str(FONT), 26), fill=(18, 18, 22))
    card.paste(flat.convert("RGB"), (pad, head))
    card.paste(over, (pad, head + h + pad))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{folder.name}.{'holes' if holes_only else 'label'}.png"
    card.save(path)
    return path


def ceiling(folders) -> list[dict]:
    """How much of each face is print, object, type, unrepresentable — and unlabelled."""
    rows = []
    for folder in folders:
        doc = load_truth(folder)
        if doc is None:
            rows.append({"folder": folder.name, "labelled": False})
            continue
        share = {c: 0.0 for c in CLASSES}
        for comp in doc["components"]:
            if comp.get("vanished"):
                continue
            share[comp.get("class", "unclassified")] += comp["area_pct"]
        residue = sum(doc.get("residue_pct_by_role", {}).values())
        rows.append({
            "folder": folder.name, "sku": doc.get("sku"), "labelled": True,
            **{k: round(v, 2) for k, v in share.items()},
            "residue": round(residue, 2),
            # What the vocabulary is allowed to aim at: printed design, minus the
            # letterforms the renderer draws itself, minus what it cannot hold,
            # minus what the owner put out of scope, minus a surface counted twice.
            "reachable": round(share["print"], 2),
        })
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--folder", action="append", help="one folder name; repeatable")
    p.add_argument("--aid", metavar="DIR", help="write the labelling aid images here")
    p.add_argument("--holes", action="store_true",
                   help="with --aid, draw the HOLES inside the print components")
    p.add_argument("--init", action="store_true", help="write/merge print_truth.json")
    p.add_argument("--ceiling", action="store_true", help="report the class shares")
    p.add_argument("--set", action="append", metavar="KEY=CLASS[:REASON]",
                   help="classify one component; repeatable")
    p.add_argument("--rest", metavar="CLASS",
                   help="classify every component still unclassified")
    p.add_argument("--verify", action="store_true", help="is every component classified?")
    args = p.parse_args()

    names = args.folder or FOLDERS
    folders = [TEMPLATES_DIR / n for n in names]
    if not (args.aid or args.init or args.ceiling or args.verify
            or args.set or args.rest):
        p.error("pass --aid DIR, --init, --set, --rest, --ceiling or --verify")

    if args.set or args.rest:
        if len(folders) != 1:
            p.error("--set/--rest need exactly one --folder")
        pairs = dict(a.split("=", 1) for a in (args.set or []))
        doc = set_classes(folders[0], pairs, args.rest)
        left = sum(1 for c in doc["components"]
                   if not c.get("vanished") and c.get("class") == "unclassified")
        counts = {}
        for c in doc["components"]:
            if not c.get("vanished"):
                counts[c["class"]] = counts.get(c["class"], 0) + 1
        print(f"{folders[0].name:24s} {counts}  unclassified left: {left}")

    if args.init:
        for folder in folders:
            doc = init(folder)
            n = len(doc["components"])
            un = sum(1 for c in doc["components"] if c.get("class") == "unclassified")
            print(f"{folder.name:24s} {n:3d} component(s), {un:3d} unclassified")

    if args.aid:
        out = Path(args.aid)
        for folder in folders:
            print(f"{folder.name:24s} -> {aid(folder, out, args.holes).name}")

    if args.verify:
        bad = 0
        for folder in folders:
            ok, why = verify(folder)
            bad += not ok
            print(f"{folder.name:24s} {'ok' if ok else 'NOT USABLE: ' + why}")
        print(f"\n{len(folders) - bad}/{len(folders)} usable")
        return 1 if bad else 0

    if args.ceiling:
        rows = ceiling(folders)
        print(f"{'folder':24s} {'print':>7s} {'object':>7s} {'type':>7s} "
              f"{'unrepr':>7s} {'mark':>6s} {'blend':>6s} {'unclass':>8s} {'residue':>8s}")
        for r in rows:
            if not r["labelled"]:
                print(f"{r['folder']:24s} not labelled")
                continue
            print(f"{r['folder']:24s} {r['print']:7.2f} {r['object']:7.2f} {r['type']:7.2f} "
                  f"{r['unrepresentable']:7.2f} {r['mark']:6.2f} {r['blend']:6.2f} "
                  f"{r['unclassified']:8.2f} {r['residue']:8.2f}")
        done = [r for r in rows if r.get("labelled")]
        if done:
            n = len(done)
            print(f"\nmean over {n}: print {sum(r['print'] for r in done)/n:.2f}%  "
                  f"object {sum(r['object'] for r in done)/n:.2f}%  "
                  f"type {sum(r['type'] for r in done)/n:.2f}%  "
                  f"unrepresentable {sum(r['unrepresentable'] for r in done)/n:.2f}%  "
                  f"mark {sum(r['mark'] for r in done)/n:.2f}%  "
                  f"blend {sum(r['blend'] for r in done)/n:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
