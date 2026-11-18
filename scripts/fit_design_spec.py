"""D-2 — turn a measured reference face into a design spec, and prove it.

    python scripts/fit_design_spec.py --folder 02_T1_SMALL_Cialis
    python scripts/fit_design_spec.py --all --preview

Reads the segmentation D-1 produced (`measure_reference_face.segment`, the same
partition, not a second implementation of it) and writes `design_spec.json` into
the folder: a substrate colour and an ordered stack of fields, each a filled
outline in FACE-NORMALISED coordinates (u across, v down, both 0..1).

WHY OUTLINES AND NOT CONICS. The plan said conics, because the Cialis fields are
arcs of large ellipses. Four of the eleven designs are built that way -- and
Lexotanil's bands are straight, Ritalin has no colour field at all, and Kamagra's
transition is five parallel rules. One primitive has to carry all of them, and a
polygon carries a conic to whatever accuracy is asked while a conic cannot carry
a rectangle without special-casing. Smoothness is recorded per outline so D-4 can
fit curves where the source really is curved rather than rebuilding stair-steps.

WHAT MAKES IT A SPEC AND NOT A TRACE. Vertices are simplified until the spec's
own rasterisation stops agreeing with the segmentation. `--verify` reports that
agreement as a percentage of face pixels, so "the spec is right" is a number.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.design_group import RingRepairFailed, simple_ring  # noqa: E402
from scripts.measure_reference_face import (  # noqa: E402
    SAME_SURFACE_MAX, TEMPLATES_DIR, _hex, segment,
)
from scripts.reference_regions import recovered_records  # noqa: E402

#: Per-component ground truth, written by scripts/label_print.py. The name and
#: the loader live in this module rather than in that one because label_print
#: already imports `components` from here, and the reverse direction would be a
#: circular import.
TRUTH_NAME = "print_truth.json"


def load_truth(folder: Path) -> dict | None:
    """The hand-made classification for *folder*, or None if it has none."""
    path = folder / TRUTH_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def design_component_sources(flat_rgb: np.ndarray, labels_2d: np.ndarray,
                             named: dict) -> list[tuple[str, np.ndarray, dict]]:
    """Return legacy cluster masks followed by recovered substrate regions."""
    labels = np.asarray(labels_2d)
    sources = [
        (role, labels == int(named[role]["label"]), named[role])
        for role in sorted(named)
        if role != "substrate" and named.get(role) is not None
    ]
    for recovered in recovered_records(
            flat_rgb, labels, named, SAME_SURFACE_MAX):
        sources.append((
            recovered["role"], recovered["mask"],
            {"label": None, "colour": recovered["colour"],
             "fill": recovered["fill"]},
        ))
    return sources


def write_complete_spec(path: Path, spec: dict, reference_rgb: np.ndarray,
                        truth: dict) -> None:
    """Write *spec* only after the independent completeness gate passes."""
    from scripts.design_completeness import check_design

    residuals = check_design(reference_rgb, spec, truth)
    if residuals:
        first = residuals[0]
        raise SystemExit(
            f"{path.parent.name}: completeness gate found {len(residuals)} "
            f"unexplained connected region(s); largest area="
            f"{first.area_frac:.5f}, bbox={list(first.bbox_uv)}, "
            f"chroma_delta={first.chroma_delta:.5f}. Existing design_spec.json "
            f"was not replaced.")
    path.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def preserve_manual_design_extensions(candidate: dict, previous: dict) -> None:
    """Keep reviewed non-front evidence that front segmentation does not own."""
    front = [field for field in (candidate.get("fields") or [])
             if field.get("surface", "front") == "front"]
    wrapped = [field for field in (previous.get("fields") or [])
               if field.get("surface", "front") != "front"]
    candidate["fields"] = front + wrapped
    for key in (
            "type_rows", "type_rows_note", "carton_profile",
            "reference_aux_text", "surface_field_evidence"):
        if key in previous:
            candidate[key] = previous[key]


def close_matching_front_top_fold(spec: dict, w: int, h: int) -> int:
    """Close a small photographed fold gap only when top ink proves continuity.

    A pale rim at a fold can make segmentation stop a few pixels before the
    rectified face edge. Extending every near-edge component would be guessing;
    a reviewed top-surface field with the same fill and matching U interval is
    independent evidence that the ink crosses that fold. Only those matched
    columns are filled, and only when the observed front component already
    reaches within four percent of the edge.
    """
    top_runs = []
    for field in spec.get("fields") or []:
        if field.get("surface", "front") != "top":
            continue
        for part in field.get("parts") or []:
            outline = part.get("outline") or []
            if len(outline) < 3:
                continue
            us = [float(point[0]) for point in outline]
            vs = [float(point[1]) for point in outline]
            if max(vs) - min(vs) < 0.90:
                continue
            top_runs.append((part.get("fill") or field.get("fill"),
                             min(us), max(us)))

    changed = 0
    for field in spec.get("fields") or []:
        if field.get("surface", "front") != "front":
            continue
        for part in field.get("parts") or []:
            outline = part.get("outline") or []
            if len(outline) < 3:
                continue
            us = [float(point[0]) for point in outline]
            vs = [float(point[1]) for point in outline]
            fill = part.get("fill") or field.get("fill")
            match = next((run for run in top_runs
                          if run[0] == fill
                          and abs(run[1] - min(us)) <= 0.04
                          and abs(run[2] - max(us)) <= 0.04
                          and min(vs) <= 0.04), None)
            if match is None:
                continue

            # A closed vector region needs no fold repair. Rasterizing it again
            # used to turn a straight band into a six-vertex kinked polygon.
            if (len(outline) == 4 and vs.count(0.0) == 2
                    and vs.count(1.0) == 2):
                continue

            # Extend an already linear quadrilateral analytically. The top run
            # owns its fold endpoints; retain the measured bottom endpoints.
            if (len(outline) == 4 and vs.count(min(vs)) == 2
                    and vs.count(max(vs)) == 2):
                bottom = sorted((p for p in outline if p[1] == max(vs)),
                                key=lambda p: p[0])
                part['outline'] = [[match[1],0.0],[match[2],0.0],
                                   list(bottom[1]),list(bottom[0])]
                changed += 1
                continue

            mask = Image.new("1", (w, h), 0)
            pixels = [(min(w - 1, max(0, int(round(u * w)))),
                       min(h - 1, max(0, int(round(v * h)))))
                      for u, v in outline]
            ImageDraw.Draw(mask).polygon(pixels, fill=1)
            region = np.asarray(mask, dtype=bool).copy()
            x0 = min(w - 1, max(0, int(round(match[1] * w))))
            x1 = min(w - 1, max(0, int(round(match[2] * w))))
            for x in range(min(x0, x1), max(x0, x1) + 1):
                rows = np.flatnonzero(region[:, x])
                if len(rows) and rows[0] <= 0.04 * h:
                    region[:rows[0] + 1, x] = True

            traced = trace_outline(region)
            if len(traced) < 8:
                continue
            points, _used = _simplify_to_a_region(
                traced, w, h, SIMPLIFY_TOLERANCE)
            part["outline"] = [
                [round(x / w, 4), round(y / h, 4)] for x, y in points]
            changed += 1
    return changed


def join_measured_edge_band(spec: dict, evidence: list) -> int:
    """Fit one shared boundary, anchored by reviewed top and side ink.

    Only a previously proven rectilinear narrow band and a broad left-edge
    neighbour qualify. Source masks must demonstrate adjacency along the face;
    top runs must meet and left wrap must prove that navy reaches the crease.
    Holes and marks are untouched. Curved or isolated fields do not qualify.
    """
    def runs(surface):
        return [(p.get('fill') or field.get('fill'), p['outline'])
                for field in spec.get('fields', [])
                if field.get('surface', 'front') == surface
                for p in field.get('parts', []) if len(p.get('outline', [])) >= 3]

    top = runs('top')
    side = runs('left')
    changed = 0
    for band, band_mask, regularized in evidence:
        if not regularized:
            continue
        h, w = band_mask.shape
        band_top = [p[0] for p in band['outline'] if p[1] == 0]
        if len(band_top) != 2:
            continue
        band_run = next((outline for fill, outline in top
                         if fill == band['fill']
                         and abs(min(p[0] for p in outline)-min(band_top)) <= 1.1/w
                         and abs(max(p[0] for p in outline)-max(band_top)) <= 1.1/w), None)
        if band_run is None:
            continue
        anchor = min(p[0] for p in band_run)
        outer = max(p[0] for p in band_run)
        for neighbour, mask, _ in evidence:
            if neighbour is band or neighbour['fill'] == band['fill']:
                continue
            matching_top = any(fill == neighbour['fill']
                               and min(p[0] for p in outline) == 0
                               and abs(max(p[0] for p in outline)-anchor) <= 1e-6
                               for fill, outline in top)
            matching_side = any(fill == neighbour['fill']
                                and min(p[0] for p in outline) == 0
                                and max(p[0] for p in outline) == 1
                                and min(p[1] for p in outline) == 0
                                and max(p[1] for p in outline) == 1
                                for fill, outline in side)
            if not matching_top or not matching_side:
                continue
            ys = np.arange(int(.04*h), h)
            if not all(mask[y].any() and band_mask[y].any() for y in ys):
                continue
            left = np.array([np.flatnonzero(mask[y])[0] for y in ys])
            right = np.array([np.flatnonzero(mask[y])[-1] for y in ys])
            adjacent = np.array([np.flatnonzero(band_mask[y])[0] for y in ys])
            # At most the measured antialiased boundary neighbourhood; a white
            # separator or curved field must never be reclassified as a join.
            if (float(np.quantile(left, .95))/w > .008
                    or float(np.max(np.abs(adjacent-right)))/w > .008):
                continue
            v = ys / float(h)
            observed = (right + adjacent) / (2.0*w)
            slope = float(np.dot(v, observed-anchor) / np.dot(v,v))
            if float(np.max(np.abs(observed-(anchor+slope*v)))) > .008:
                continue
            bottom = round(anchor+slope, 8)
            outer_bottom = round(outer+slope, 8)
            if not 0 < bottom < outer_bottom < 1:
                continue
            band['outline'] = [[anchor,0.0],[outer,0.0],[outer_bottom,1.0],[bottom,1.0]]
            neighbour['outline'] = [[0.0,0.0],[anchor,0.0],[bottom,1.0],[0.0,1.0]]
            changed += 1
            break
    return changed


# A field is a share of the FACE, not a pixel count: the rectified faces differ
# in size and a fixed count means a different thing on each. 0.8% keeps the
# Cialis dosage block (2.0% of its face) and drops every letterform, which is the
# distinction that matters -- when type fails to separate into its own cluster,
# its strokes land in a colour field and get traced as though they were design.
# They are not: the renderer draws type from the manifest's strings, and a spec
# carrying letter outlines would print the reference's words instead.
#
# SUPERSEDED BY THE LABEL as of Phase B, and kept because it names the reasoning
# the label replaced. `fit()` now enumerates at the truth file's own floor, which
# is coarser than nothing and finer than this: Imovane's only printed field is
# 0.67% of its face and this threshold would drop it.
MIN_REGION_FRAC = 0.008
# A field has to be visibly different from the board it is printed on. Below this
# distance in RGB it is not a design element -- it is the clustering splitting one
# printed surface into two under a lighting gradient. Measured: Xanax's
# "highlight" #E9DCB6 sits TWO levels from its substrate #E8DBB2, Valium's
# #C9C8C4 two from #C9C5C0, Ritalin's #82837D two from #817F78. All three were
# emitted as fields covering a third of the face, and they are why six of the
# eleven palettes came back inseparable in D-6: a spec that names two colours a
# classifier cannot tell apart makes every later measurement of it meaningless.
#
# Set to the same figure D-6 needs to tell two colours apart
# (scripts/design_qa.SEPARABLE_MIN). The two readings agree: a field this close
# to its board is invisible to a viewer AND unmeasurable afterwards, and emitting
# one produces a spec whose own fidelity cannot be checked.
MIN_FILL_CONTRAST = 0.08
# How much of its own bounding box a component must fill to be admitted as a
# printed shape when it neither runs off the face nor reads as a block. Measured
# on the component's PIXELS with hairline filaments removed, not on its traced
# polygon: the polygon encloses holes, which is right for a block with type
# reversed out of it and wrong here.
#
# This replaced a "large enough" escape, and it had to: the escape could not be
# repaired by choosing a better size, because the thing it was letting through
# is BIGGER than the thing it was there for. Xanax's traced "XA" covers 3.4% of
# its face and Xanax Pfizer's magenta panel 3.2%. They separate on this ratio at
# 0.49 against 0.96.
BOX_FILL_MIN = 0.85
# Douglas-Peucker, in face widths, and the value is measured rather than chosen.
# Against the raw trace the simplification loses, area-weighted over the group's
# 74 printed parts: 2.316% at 0.004, 1.354% at 0.002, 0.891% at 0.001, 0.148% at
# 0.0005. It is the dominant error in the spec's geometry -- larger than anything
# the vocabulary itself costs -- and it is paid for in vertices: 1479, 2550,
# 4721, 15501.
#
# 0.001 is where the two curves cross for this project. It removes 62% of the
# loss for 3.2x the vertices; 0.0005 removes 94% for 10.5x, and at that size the
# ring repair starts costing seconds per `load_design`.
#
# NOT a curve problem, which is what this was expected to be. A cubic fit was
# built and measured against the same traces: it needs 3.5x MORE control points
# than the polyline at WORSE and unstable accuracy (Kamagra 3007 points at 0.995
# against 1172 at 1.000; Adderall between 0.216 and 0.787 depending on
# pre-smoothing). These outlines are boundaries of RASTER regions -- long
# near-straight runs carrying pixel noise -- which is Douglas-Peucker's home
# ground and a cubic's worst case.
SIMPLIFY_TOLERANCE = 0.001
SMOOTH_TURN_DEG = 25.0      # a vertex turning less than this reads as a curve

# How far the tolerance may be relaxed for a part whose ring will not simplify
# into a region. See `_simplify_to_a_region`.
SIMPLIFY_BACKOFF_MAX = 0.02

# The smallest enclosed background a part carries as a HOLE, as a fraction of
# the face. Below it, an island in a printed region is segmentation noise rather
# than something the carton leaves unprinted.
#
# CONTRACT 1.8, and the constant is the cheap half of it. What matters is that a
# part is a REGION -- its outer ring minus its holes -- and not a ring: measured
# over the group's 74 printed parts, the traced ring encloses 1.192 times the
# ink it describes, and subtracting the holes takes that to 0.999. Adderall's
# `brand#1` is the case that shows what kind of error this is: 5.90% of the face
# in ink, 53.48% once its outer ring is filled, IoU 0.110 against its own
# component. It is not a tolerance problem and no tolerance repairs it -- the
# ring is a correct boundary trace of a shape that has holes in it.
#
# What the floor actually decides is HOW MANY HOLES A PERSON MUST CLASSIFY, not
# how well the group scores. Since only `window` holes are cut and the group has
# ten of them, accuracy is flat across every floor tried; the enumeration count
# is not, running 569 / 397 / 282 / 238 / 179 at 0 / 0.00002 / 0.00005 / this /
# 0.0003. The smallest window in the group is Kamagra's 0.053%, twenty times
# this floor, so nothing that matters is near the edge.
#
# It is ten times finer than the component floor the labeller enumerates at,
# which is the same relation `label_print.ENUMERATE_MIN_FRAC` has to the
# fitter's own. Changing it changes the partition and invalidates every hole
# label, which is why `fit()` compares it against the value recorded in
# `print_truth.json` and stops rather than enumerating differently from the
# person who did the looking.
MIN_HOLE_FRAC = 0.0001

# A hole is CUT only where a person called it a window, and that is a
# conclusion, not a preference. Three automatic tests were built and all three
# were measured failing on real cartons:
#
#   the share of the hole lying in a component already classified `type`
#     separates 45 of 238 and no more. Cialis's "1" is one stroke of "10 mg" and
#     lands in the SUBSTRATE cluster, which is never enumerated, so it reads as
#     0.000 type.
#   the reference's own OCR word boxes
#     cover 131 and read NOTHING on `344_Modafinil_Generic`, whose ten holes
#     spell "Modalert (R) 200" reversed out of a purple band. Any threshold low
#     enough to catch them also takes Adderall's genuine window, which sits at
#     0.388.
#   size
#     is the escape this project already removed once, and it fails the same way
#     here: Ritalin's 72 letterform holes and Kamagra's 5 windows overlap in area.
#
# Both populations are BOARD. Nothing in the segmentation tells them apart,
# because there is nothing there to tell apart -- a letter reversed out of a
# field and a window onto the board are the same pixels. The difference is what
# the carton MEANS by them, and that is a question for a person, which is the
# same conclusion Phase B reached about components and for the same reason.
#
# The stake is the invariant rather than the metric, and the metric agrees: the
# letterform holes lie outside the scored area, so declining to cut them costs
# 0.12 points -- measured before `part_region` was made the inverse of the
# normalisation, and the one figure of that phase that cannot be retaken, since
# only the `window` rings are emitted and the other 228 exist nowhere but in a
# re-run of the tracer. `59-min` is a 20 mg Cialis whose photograph is a 10 mg pack;
# `344-min` is Modafinil Generic whose photograph is Modalert 200; `404-min`'s
# 72 holes are "Ritalin 10 mg Tabletten / 50 Tabletten/N2". Cutting those prints
# another package's brand and dosage on our carton, in board, in the shape the
# photograph has -- the same act as printing a plausible LOT, which this driver
# already refuses.
#
# Ten of the group's 238 holes are windows. They carry almost all of the area.
HOLE_CUT_CLASS = "window"


def _neighbours(y, x):
    #  Moore neighbourhood, clockwise from the west. Order matters: the tracer
    #  resumes from the backtrack direction, which is what keeps it on the
    #  outline instead of cutting corners into the interior.
    return [(y, x - 1), (y - 1, x - 1), (y - 1, x), (y - 1, x + 1),
            (y, x + 1), (y + 1, x + 1), (y + 1, x), (y + 1, x - 1)]


def trace_outline(mask: np.ndarray) -> list[tuple[int, int]]:
    """Moore-neighbour boundary trace of the largest blob in *mask*.

    Written out rather than imported: skimage and scipy are not dependencies of
    this project, and adding one to draw an outline would put a compiled package
    in the way of a measurement script.
    """
    h, w = mask.shape
    padded = np.zeros((h + 2, w + 2), bool)
    padded[1:-1, 1:-1] = mask
    ys, xs = np.nonzero(padded)
    if not len(ys):
        return []
    start = (int(ys[0]), int(xs[np.nonzero(ys == ys[0])[0][0]]))

    outline = [start]
    prev = (start[0], start[1] - 1)
    cur = start
    for _ in range(4 * padded.size):
        ring = _neighbours(*cur)
        try:
            i = ring.index(prev)
        except ValueError:
            i = 0
        found = None
        for k in range(1, 9):
            cand = ring[(i + k) % 8]
            if padded[cand]:
                found = cand
                prev = ring[(i + k - 1) % 8]
                break
        if found is None:
            break
        cur = found
        if cur == start and len(outline) > 2:
            break
        outline.append(cur)
    return [(x - 1, y - 1) for y, x in outline]


def components(mask: np.ndarray, min_px: int) -> list[np.ndarray]:
    """Split *mask* into connected regions, largest first.

    A field is rarely one blob: the Cialis olive enters from the left AND sweeps
    across the bottom right, and tracing "the" outline of that mask produced a
    polygon around one half and 65% agreement. Union-find over row runs rather
    than a pixel flood fill -- a 1100x700 face is 770 000 pixels and a
    Python-level flood is slow enough to discourage re-running the fit, which is
    the one thing this step needs to be cheap.
    """
    h, w = mask.shape
    parent: dict[int, int] = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    runs_by_row: list[list[tuple[int, int, int]]] = []
    next_id = 0
    for y in range(h):
        row = mask[y]
        idx = np.flatnonzero(np.diff(np.concatenate(([0], row.view(np.int8), [0]))))
        runs = []
        for x0, x1 in zip(idx[::2], idx[1::2]):
            parent[next_id] = next_id
            runs.append((int(x0), int(x1), next_id))
            next_id += 1
        if y:
            for x0, x1, rid in runs:
                for px0, px1, pid in runs_by_row[-1]:
                    if px0 < x1 and x0 < px1:      # overlap => 4-connected
                        union(rid, pid)
        runs_by_row.append(runs)

    out: dict[int, np.ndarray] = {}
    for y, runs in enumerate(runs_by_row):
        for x0, x1, rid in runs:
            r = find(rid)
            m = out.get(r)
            if m is None:
                m = out[r] = np.zeros((h, w), bool)
            m[y, x0:x1] = True

    keep = [m for m in out.values() if m.sum() >= min_px]
    keep.sort(key=lambda m: -m.sum())
    return keep


def enclosed_background(mask: np.ndarray) -> list[np.ndarray]:
    """The holes in *mask*: enclosed background regions, largest first.

    Background is 8-connected here while `components` makes the foreground
    4-connected, which is the standard pairing -- under one connectivity on both
    sides a diagonally pinched hole is simultaneously enclosed and outside.

    The region touching the 1px pad is the outside; everything else is a hole.
    Written out for the same reason `trace_outline` and `components` are: adding
    a compiled package to find a hole would put an install in front of a
    measurement.
    """
    h, w = mask.shape
    padded = np.zeros((h + 2, w + 2), bool)
    padded[1:-1, 1:-1] = mask
    bg = ~padded
    parent: dict[int, int] = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    runs_by_row: list[list[tuple[int, int, int]]] = []
    next_id = 0
    for y in range(bg.shape[0]):
        row = bg[y]
        idx = np.flatnonzero(np.diff(np.concatenate(([0], row.view(np.int8), [0]))))
        runs = []
        for x0, x1 in zip(idx[::2], idx[1::2]):
            parent[next_id] = next_id
            runs.append((int(x0), int(x1), next_id))
            next_id += 1
        if y:
            for x0, x1, rid in runs:
                for px0, px1, pid in runs_by_row[-1]:
                    if px0 <= x1 and x0 <= px1:      # touching or diagonal => 8-connected
                        union(rid, pid)
        runs_by_row.append(runs)

    out: dict[int, np.ndarray] = {}
    for y, runs in enumerate(runs_by_row):
        for x0, x1, rid in runs:
            r = find(rid)
            m = out.get(r)
            if m is None:
                m = out[r] = np.zeros(bg.shape, bool)
            m[y, x0:x1] = True

    holes = [m[1:-1, 1:-1] for m in out.values()
             if not (m[0].any() or m[-1].any() or m[:, 0].any() or m[:, -1].any())]
    holes.sort(key=lambda m: -m.sum())
    return holes


def trace_holes(part: np.ndarray, w: int, h: int, min_px: int, key: str,
                class_of: dict, cut_marks=frozenset()
                ) -> tuple[list[list], dict, list]:
    """A part's windows as simplified rings, a tally of what was not cut, and
    the approved MARK holes, which are cut and drawn together.

    Each ring is traced and simplified exactly as the outer one is, and through
    the same `_simplify_to_a_region`, because a hole that crosses itself is no
    more a region than an outline that does.

    `class_of` maps `role#i/hole#j` to the hand-made class. `window` is always
    cut -- see HOLE_CUT_CLASS. A hole the truth does not carry is a hard stop
    rather than a silent cut, the same rule the components follow.

    `cut_marks` is the set of `role#i/hole#j` keys the OWNER approved in
    `00_PROJECT_STATE/MARKS_DECISION.md`, and nothing else may be added to it
    here: a class is what a region IS and the decision is what may be done with
    it. An approved mark hole leaves in BOTH returns -- the ring so the field is
    cut, and the mask so the caller can measure the colour and emit the mark
    that fills it. They leave together because that is the file's own rule:
    cutting a mark hole while drawing nothing into it shows board through our
    field in the shape of another company's logo, which is the act contract 1.8
    already refuses for another company's lettering. Emitting them from one loop
    makes the unpaired case unreachable in the producer rather than merely
    caught later.
    """
    rings, kept, marks = [], {}, []
    for j, hole in enumerate(enclosed_background(part)):
        if hole.sum() < min_px:
            continue
        hkey = f"{key}/hole#{j}"
        cls = class_of.get(hkey)
        if cls is None:
            raise SystemExit(
                f"{hkey} has no label. Run scripts/label_print.py --init and "
                f"classify it; cutting an unlabelled hole is how the reference's "
                f"own dosage gets printed on our carton.")
        approved = hkey in cut_marks
        if cls != HOLE_CUT_CLASS and not approved:
            kept[cls] = kept.get(cls, 0) + 1
            continue
        outline = trace_outline(hole)
        if len(outline) < 8:
            continue
        pts, _used = _simplify_to_a_region(outline, w, h, SIMPLIFY_TOLERANCE)
        if len(pts) < 3:
            continue
        rings.append(pts)
        if approved:
            marks.append((hkey, pts, hole))
    return rings, kept, marks


def _perp(pt, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = pt, a, b
    dx, dy = x2 - x1, y2 - y1
    n = (dx * dx + dy * dy) ** 0.5
    if n == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / n


def simplify(points, tol):
    """Douglas-Peucker, iterative so a 20 000-point outline cannot blow the stack."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        worst, wi = -1.0, i
        for k in range(i + 1, j):
            d = _perp(points[k], points[i], points[j])
            if d > worst:
                worst, wi = d, k
        if worst > tol:
            keep[wi] = True
            stack.append((i, wi))
            stack.append((wi, j))
    return [p for p, k in zip(points, keep) if k]


def _simplify_to_a_region(outline, w, h, start):
    """Simplify as finely as this shape allows, and say when that was not finely.

    A tolerance FINER than a part is thick starts resolving the two sides of a
    strip separately, and they interleave: Ritalin's `highlight#1` is 2.7px wide
    and simplifies at 0.004 into a clean 7-vertex ring, while at 0.001 it becomes
    22 vertices crossing themselves six times -- a ring that describes no region
    at all. Coarser is SAFER for a strip, which is the opposite of the intuition
    a tolerance usually carries.

    There is no single tolerance that serves both: flooring it at each part's own
    width (2*area/perimeter) destroys the large fields, which have a large
    inradius -- measured, 16.567% of the printed area against 0.891%. The two
    requirements pull apart because a closed outline is the wrong primitive for a
    strip, and no choice of constant repairs that.

    So the tolerance is per part: start where the group is best served and back
    off, doubling, until the ring is a region. Across the 74 printed parts
    exactly ONE backs off -- Ritalin's strip, to 0.002 -- so this is a named
    exception rather than a policy of giving up.

    Returns (points, tolerance_used).
    """
    frac = start
    while True:
        pts = simplify(outline, frac * w)
        ring = [(x / w, y / h) for x, y in pts]
        if len(ring) < 4:
            return pts, frac
        try:
            simple_ring(ring)
            return pts, frac
        except RingRepairFailed:
            frac *= 2
            if frac > SIMPLIFY_BACKOFF_MAX:
                # Out of room. Return it anyway: `validate_manifest` rejects a
                # tangled outline by name on write, which is a better place to
                # stop than a silent shrug here.
                return pts, frac


def _area(points) -> float:
    if len(points) < 3:
        return 0.0
    p = np.asarray(points, dtype=float)
    x, y = p[:, 0], p[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2)


def _runs_off_face(outline, w, h) -> bool:
    """Does this outline reach the edge of the printed face?

    A colour field that enters from an edge is structural whatever its shape.
    Nothing printed as type does that.
    """
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    margin = 0.01 * max(w, h)
    return (min(xs) <= margin or min(ys) <= margin
            or max(xs) >= w - 1 - margin or max(ys) >= h - 1 - margin)


def _despeckle(mask: np.ndarray) -> np.ndarray:
    """The component with one-pixel filaments removed: erode 1px, dilate 1px.

    A morphological opening. A printed shape loses and regains its outline; a
    thread one pixel wide does not come back, because there was nothing left of
    it to dilate.
    """
    from PIL import ImageFilter
    img = Image.fromarray((mask * 255).astype("uint8"))
    return np.asarray(img.filter(ImageFilter.MinFilter(3))
                         .filter(ImageFilter.MaxFilter(3))) > 0


def fills_its_box(mask: np.ndarray) -> float:
    """Share of its own bounding box the component's pixels occupy.

    Taken after `_despeckle`, and that is the whole point of the function.
    Xanax Pfizer's magenta panel is a clean 138x160 pixel rectangle with a
    ONE-PIXEL thread running a fifth of the face down the carton's right edge --
    an artefact of rectifying a photograph, not something printed. The thread
    carries 1% of the component's pixels and stretches its bounding box by half,
    taking this ratio from 0.96 to 0.51 and dropping a plain colour panel below
    every rectangle test in this module.
    """
    m = _despeckle(mask)
    if not m.any():
        return 0.0
    ys, xs = np.nonzero(m)
    box = (ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1)
    return float(m.sum()) / box if box else 0.0


def regularize_rectilinear_edge_band(mask: np.ndarray):
    """Return a fold-anchored parallel-sided region for proven printed rule.

    Rectification removes camera perspective from the face, but segmentation
    still follows illumination and antialiasing along a pale narrow rule. A
    component is regularized only when its own geometry proves that it spans
    both horizontal face edges, stays narrow, has one filled run on virtually
    every row, has two nearly linear boundaries, keeps nearly constant width,
    and is only weakly tilted. The first five percent of rows own the U anchors
    because that is the physical front/top fold. No SKU, role or colour
    participates in this decision.
    """
    region = np.asarray(mask, dtype=bool)
    if region.ndim != 2 or not region.any():
        return None
    h, w = region.shape
    ys = np.flatnonzero(region.any(axis=1))
    xs = np.flatnonzero(region.any(axis=0))
    height_frac = len(ys) / float(h)
    width_frac = len(xs) / float(w)
    if (height_frac < 0.90 or width_frac < 0.015 or width_frac > 0.15
            or ys[0] > 0.01 * h or (h - 1 - ys[-1]) > 0.01 * h):
        return None
    if len(ys) / float(ys[-1] - ys[0] + 1) < 0.98:
        return None

    left = np.array([np.flatnonzero(region[y])[0] for y in ys], dtype=float)
    right = np.array([np.flatnonzero(region[y])[-1] for y in ys], dtype=float)
    row_fill = np.array([
        region[y].sum() / (right[i] - left[i] + 1.0)
        for i, y in enumerate(ys)
    ])
    if float(np.median(row_fill)) < 0.98:
        return None

    left_line = np.polyfit(ys, left, 1)
    right_line = np.polyfit(ys, right, 1)
    left_fit = np.polyval(left_line, ys)
    right_fit = np.polyval(right_line, ys)
    if (float(np.max(np.abs(left - left_fit))) / w > 0.008
            or float(np.max(np.abs(right - right_fit))) / w > 0.008):
        return None

    edge_rows = max(1, int(round(0.05 * len(ys))))
    top_left = float(np.median(left[:edge_rows]))
    top_right = float(np.median(right[:edge_rows]))
    bottom_left = float(np.median(left[-edge_rows:]))
    bottom_right = float(np.median(right[-edge_rows:]))
    if (abs((top_right - top_left) - (bottom_right - bottom_left)) / w
            > 0.02):
        return None
    if abs(0.5 * (top_left + top_right - bottom_left - bottom_right)) / w > 0.06:
        return None

    # Preserve the measured global slope: completeness must still compare the
    # emitted region with the reference, and a forced axis alignment discards a
    # large, connected triangular part of a mildly tilted band. Search only the
    # one-pixel fold-anchor neighbourhood and a six-per-mille slope window, then
    # select the constant-width parallelogram with maximum source-mask IoU.
    # This is an evidence fit, not a tolerance that grows until one SKU passes.
    slope = 0.5 * (float(left_line[0]) + float(right_line[0]))
    centre_shift = int(round(slope * (h - 1)))
    shift_radius = max(2, int(math.ceil(0.006 * w)))
    region_area = int(region.sum())
    best = None
    # Candidate anchors may retain or expand the observed top run by one pixel,
    # never shrink it. Besides improving completeness this keeps a recovered
    # front rule within one source pixel of an independently measured top wrap.
    for x0 in range(int(round(top_left)) - 1,
                    int(round(top_left)) + 1):
        for x1 in range(int(round(top_right)),
                        int(round(top_right)) + 2):
            if x1 <= x0:
                continue
            for shift in range(centre_shift - shift_radius,
                               centre_shift + shift_radius + 1):
                intersection = candidate_area = 0
                for y in range(h):
                    alpha = y / float(max(1, h - 1))
                    start = max(0, int(round(x0 + shift * alpha)))
                    stop = min(w - 1, int(round(x1 + shift * alpha)))
                    if start > stop:
                        continue
                    candidate_area += stop - start + 1
                    intersection += int(region[y, start:stop + 1].sum())
                union = region_area + candidate_area - intersection
                iou = intersection / union if union else 0.0
                score = (iou, -abs(shift - centre_shift), -x0, -x1)
                if best is None or score > best[0]:
                    best = (score, x0, x1, shift)
    if best is None:
        return None
    _score, x0, x1, shift = best
    return [(x0, 0), (x1, 0), (x1 + shift, h), (x0 + shift, h)]


def is_design_field(outline, w, h, mask=None) -> bool:
    """Is this component a colour field, or a letter that landed in one?

    Area alone cannot tell them apart -- Cialis's "C" and "a" are larger than its
    dosage block, and the case that settles it is Xanax, whose traced "XA" is
    LARGER than Xanax Pfizer's magenta panel: 3.4% of its face against 3.2%. Any
    threshold admitting the panel admits the letters. A component earns its place
    three ways instead:

    - it RUNS OFF THE FACE. The olive bands enter from the edges; nothing printed
      as type does that.
    - it reads as a BLOCK. `part_kind`'s polygon test, which encloses holes, and
      must: the four references that reverse the dosage out of a filled block
      leave letter-shaped holes in it, and Cialis's block fills only 0.70 of its
      box by pixels while its outline fills 0.95.
    - its PIXELS fill its own box, hairlines removed. This is what carries a
      plain colour panel that is not quite a rectangle, and it is what "XA" fails
      at 0.49.

    This matters more than tidiness. Type is drawn from the manifest's strings,
    and a spec carrying letter outlines prints the REFERENCE's words on every
    carton built from it -- the exact failure the text-as-geometry rule exists to
    prevent, arriving through the back door. Xanax shipped that way: the reader
    that measures our own type came back with "XAXa" off a carton printing
    "Xanax", because the wordmark was standing beside it as geometry.
    """
    if _runs_off_face(outline, w, h):
        return True
    if part_kind(outline) == "block":
        return True
    return mask is not None and fills_its_box(mask) >= BOX_FILL_MIN


def part_kind(outline, holes=()) -> str:
    """`block` for a printed colour block, `field` for everything else.

    Named in the spec rather than re-derived by the renderer. The driver runs
    inside Blender and reads only the manifest, so a shape it has to classify
    for itself is a second implementation of a rule that already exists here --
    and this project has twice paid for two copies of "the same" logic.

    The distinction earns its keep: four of the eleven references reverse the
    dosage out of a filled block (Cialis, Ativan, Imovane, Lexotanil). A block is
    a place to put type; a field is not.

    Holes count against the fill, and must: contract 1.8 makes a part a region
    rather than a ring, and a rectangle with a window cut out of it is no longer
    somewhere a string can be reversed out. Passed in the outline's own units.
    """
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    bbox = (max(xs) - min(xs)) * (max(ys) - min(ys))
    if bbox <= 0 or len(outline) > 12:
        return "field"
    solid = _area(outline) - sum(_area(ring) for ring in holes)
    return "block" if solid / bbox >= 0.85 else "field"


def _smoothness(points) -> float:
    """Share of vertices that turn by less than SMOOTH_TURN_DEG.

    A polygon approximating an arc turns a little at every vertex; one
    approximating a rectangle turns 90 degrees at four of them and nowhere else.
    The figure tells D-4 whether to fit a curve through these points or to build
    them as drawn.
    """
    if len(points) < 3:
        return 0.0
    pts = np.asarray(points, dtype=float)
    prev = pts - np.roll(pts, 1, axis=0)
    nxt = np.roll(pts, -1, axis=0) - pts
    dot = (prev * nxt).sum(1)
    norm = np.linalg.norm(prev, axis=1) * np.linalg.norm(nxt, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        ang = np.degrees(np.arccos(np.clip(dot / np.where(norm == 0, 1, norm), -1, 1)))
    return float(np.mean(ang < SMOOTH_TURN_DEG))


def _mark_entry(mask, raw, w, h, role, key, source, estimator,
                outline=None, min_hole=None):
    """One approved mark: the region it inks, in its own measured colour.

    **A mark carries its own holes, and the first version did not.** `holes: []`
    was written on the strength of `MARKS_EVIDENCE.md` measuring every approved
    HOLE solid — `islands = 0`, `solid_frac = 1.000`, `74_Viagra`'s mask 13 071
    px filled or unfilled. That is true of the eight holes and false of the
    components: measured over all 22 emitted marks, the eight holes fill 0.9-1.0
    times the ink they describe and **five components fill 2.4 to 9.5 times it**.
    `157_Valium`'s Roche mark is a hexagonal OUTLINE inking 1 977 px, and filled
    it covers 16 619. `272_Valium_Brand`'s is 9.0x, `230_Slimex`'s 9.5x.

    Painting those solid is a worse reproduction than the carton's own, not a
    lesser one: it invents a filled logo where the pack prints a line. It is also
    measurable as wrong — `157-min`'s mark region declared `#022E99` while the
    photograph inside that same region reads `#B8BEC3`, because most of what we
    filled is board.

    The holes are traced WITHOUT consulting `print_truth.json`, and that is not a
    relaxation of contract 1.8's rule. That rule protects a printed FIELD from
    showing board in the shape of the reference's own lettering. Here the ring is
    the mark's own interior, cutting it is what makes the mark the shape the
    carton prints, and leaving it filled is the invention.

    `key` travels with the entry so provenance survives into the manifest: a
    reader can put any drawn mark back against the row of the decision file that
    permitted it.
    """
    holes = []
    if outline is None:
        traced = trace_outline(mask)
        if len(traced) < 8:
            return None
        outline, _used = _simplify_to_a_region(traced, w, h, SIMPLIFY_TOLERANCE)
        floor = MIN_HOLE_FRAC * mask.size if min_hole is None else min_hole
        for ring in enclosed_background(mask):
            if ring.sum() < floor:
                continue
            r = trace_outline(ring)
            if len(r) < 8:
                continue
            pts, _u = _simplify_to_a_region(r, w, h, SIMPLIFY_TOLERANCE)
            if len(pts) >= 3:
                holes.append(pts)
    if len(outline) < 3:
        return None
    return {
        "role": role,
        "key": key,
        "source": source,
        # The same estimator a part's colour comes from, for the same reason: a
        # mark is a small region and its median carries its antialiased rim.
        "fill": _hex(estimator(mask, raw)),
        "area_pct": round(100 * float(mask.sum()) / (w * h), 3),
        "outline": [[round(x / w, 4), round(y / h, 4)] for x, y in outline],
        "holes": [[[round(x / w, 4), round(y / h, 4)] for x, y in ring]
                  for ring in holes],
        # Filled in once the field count is known; a mark is drawn in FRONT of
        # every field, because it is printed on top of the surface it sits on.
        "z": None,
    }


def _disconnected_mark_ink(container, group_mask, raw, w, h, estimator):
    """Retain same-cluster ink islands lost when a host-only hole is filled.

    The approved envelope remains the mark base. Each measured ink component
    is a colour overlay, including its own counters. No new approval key is
    inferred from segmentation and no ring is automatically repaired.
    """
    from src.design_group import ring_crossings

    def ring(mask):
        points = simplify(trace_outline(mask), .35)
        result = [[round(x/w, 8), round(y/h, 8)] for x,y in points]
        if len(result) < 3 or ring_crossings(result):
            raise SystemExit('mark ink component cannot be represented by a simple ring')
        return result

    parts = []
    # Match the existing component enumeration floor; within a confirmed ink
    # component every enclosed counter is retained, including the small e eye.
    for ink in components(container & group_mask, max(1,int(MIN_HOLE_FRAC*w*h))):
        parts.append({'outline': ring(ink),
                      'holes': [ring(counter) for counter in enclosed_background(ink)],
                      'fill': _hex(estimator(ink,raw))})
    return parts


def _part_fills(masks, raw, field_colour, others=()) -> list:
    """One colour per SURFACE within a field, not one per part.

    Contract 1.9. `field_colour` is `segment()`'s cluster median -- the value the
    field carries -- and a part is one region of that cluster. Measured over the
    group's 75 printed parts, 33 sit at or beyond `SAME_SURFACE_MAX` from it
    (00_PROJECT_STATE/FIT_COLOUR.md).

    Two rules, and both were measured before being chosen.

    **Merge first.** Parts whose own colours lie within `SAME_SURFACE_MAX` are
    one surface by this project's own definition -- it is the constant
    `segment()` merges two clusters at -- and they take one colour. Without this
    the threshold below splits a single surface in two, because two parts of it
    land on either side: measured over the group, ten pairs across four cartons,
    worst `64_Kamagra`'s `highlight#1` and `highlight#3` sitting **0.0039** apart
    in the photograph and painted differently. Merged colours are combined by
    area, a weighted mean of medians that are each already robust; re-estimating
    over the union is not the same thing, because the erosion asks the mask how
    thick it is and a union of scattered parts has no meaningful thickness.

    It takes those ten pairs to **two**, and the two that remain are honest
    disagreement rather than leakage: `59-min`'s `brand#1`/`brand#2` and
    `62-min`'s are within `SAME_SURFACE_MAX` by the FULL-region median and
    beyond it by the eroded estimate, which is the better of the two by a factor
    of four on a bench with known answers. Where the estimators disagree at the
    boundary this rule believes the one that was measured to be right.

    **Then threshold against the field.** A surface within `SAME_SURFACE_MAX` of
    its field takes the field's value EXACTLY rather than a near-duplicate of
    it. Emitting every part's own colour regardless is what the rolled-back
    attempt did, and it sends eight of the 28 cartons to "palette not separable"
    -- two paints a classifier cannot tell apart are not two paints. Thresholded
    it is two.

    **And never emit a colour the vocabulary cannot hold.** `others` is the
    substrate plus every OTHER field's colour, and a candidate landing within
    `SAME_SURFACE_MAX` of one of them is refused: the part keeps its field's
    value even though that value is known to be wrong for it. This is the
    `SEPARABLE_MIN` collapse `PART_FILL.md` asked for, it costs something real,
    and the price was measured before it was paid. It fires on exactly two
    cartons -- `59_Cialis`'s highlight lands 0.0761 from its own SUBSTRATE and
    `64_Kamagra`'s 0.0335 from its own brand -- and on Kamagra, emitting the
    colour anyway bought **0.0032** of `region_colour_gap` while taking that
    carton's `render~spec` IoU from 0.975 and 0.959 down to 0.633 and 0.340.

    Kamagra is also the case that says what the real defect is: its brand and
    highlight sit **0.0251** apart in the photograph and **0.1221** apart in the
    spec. By this project's own constant they are ONE surface, which the
    segmentation split and the spec inherited -- and no choice of fill repairs
    a partition.
    """
    from scripts.measure_part_colour import median_eroded_adaptive
    own = [median_eroded_adaptive(m, raw) for m in masks]
    areas = [float(m.sum()) for m in masks]
    groups = [[i] for i in range(len(masks))]
    cols = [c.astype(float).copy() for c in own]
    wts = list(areas)

    merged = True
    while merged and len(groups) > 1:
        merged = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if float(np.linalg.norm(cols[i] - cols[j])) >= SAME_SURFACE_MAX:
                    continue
                total = wts[i] + wts[j]
                cols[i] = ((cols[i] * wts[i] + cols[j] * wts[j]) / total
                           if total else cols[i])
                wts[i] = total
                groups[i] = groups[i] + groups[j]
                del groups[j], cols[j], wts[j]
                merged = True
                break
            if merged:
                break

    out = [None] * len(masks)
    for members, colour in zip(groups, cols):
        take_own = (
            float(np.linalg.norm(colour - field_colour)) >= SAME_SURFACE_MAX
            and all(float(np.linalg.norm(colour - o)) >= SAME_SURFACE_MAX
                    for o in others))
        value = _hex(colour) if take_own else _hex(field_colour)
        for k in members:
            out[k] = value
    return out


def fit(folder: Path, preview_dir: Path | None = None) -> dict:
    # Imported here, not at module scope: `measure_part_colour` imports
    # `components` and `load_truth` from THIS module, so a top-level import is a
    # cycle. The estimator has one implementation and it lives with the bench
    # that chose it over three others -- a second copy here is the defect this
    # project has already paid for at `part_region` and `narrow_to_string`.
    from scripts.measure_part_colour import median_eroded_adaptive
    # Lazy for the same reason: `src.design_group` is imported by the modules
    # that import this one. The decision loader is not circular but travels with
    # it, and both are needed only inside a fit.
    from src.design_group import FOLDER_BY_STEM
    from src.marks_decision import load as load_marks_decision

    # The owner's signed decision, and the only place it is read. It raises
    # rather than returning empty when the file's Purpose, Basis or Scope is
    # blank -- see 00_PROJECT_STATE/MARKS_DECISION.md, whose own rule that is.
    decision = load_marks_decision()
    stem = next((s for s, f in FOLDER_BY_STEM.items() if f == folder.name), None)
    cut_marks = frozenset(k for s, k in decision.holes if s == stem)
    draw_marks = frozenset(k for f, k in decision.components if f == folder.name)

    flat, labels, named, meta, source = segment(folder)
    w, h = flat.width, flat.height
    lab = labels.reshape(h, w)
    # The same pixels `segment()` takes a cluster's colour from, in the same
    # space: raw, not illumination-corrected. A part's colour has to be
    # comparable with its field's or the threshold below means nothing.
    raw = np.asarray(flat).astype(float) / 255.0

    substrate = named["substrate"]
    substrate_label = substrate.get("label")
    # Each group carries its own label. Recovering it by matching pixel counts --
    # what this did before -- breaks the moment segment() merges two clusters of
    # one surface: the merged-away label matches nothing, and a count that
    # happens to coincide matches the WRONG group. Modafinil went to 24.2% on
    # exactly that, with a spec that was otherwise correct.
    order = design_component_sources(raw, lab, named)

    fields = []
    # The labels of the fields ACTUALLY emitted, in the same order. verify() used
    # to index its ground truth by `order`, which lists every role considered --
    # so the moment a role was dropped the two indexings slid apart and each
    # field was scored against its neighbour's pixels. It showed up as IoU 0.0 on
    # roles that were plainly present.
    emitted = []
    dropped = 0
    dropped_by_class: dict[str, int] = {}
    kept_mask = np.zeros((h, w), bool)
    # PHASE B. Where a folder carries `print_truth.json`, the hand-made label is
    # the ONLY test, and every heuristic below it is bypassed.
    #
    # Those heuristics -- MIN_REGION_FRAC, MIN_FILL_CONTRAST, is_design_field's
    # three escapes, the stricter ink test on `type` and `secondary_*` -- exist
    # because nothing had ever stated, per component, what was printed on the
    # carton and what was lying in front of it. Each is a proxy for that
    # judgement, and each was measured failing: Kamagra's pouch entered through
    # "runs off the face", Xanax Pfizer's shaded board through a 0.090 contrast,
    # Provigil's box lid and the table under it through both.
    #
    # Size has to give way with the rest, and this is the case that proves it:
    # Imovane's ONLY printed field is a blue rule covering 0.67% of its face,
    # below MIN_REGION_FRAC's 0.8%. The threshold would keep that carton at zero
    # fields while the label says exactly what is there. Letting a labelled
    # component through is not tuning a threshold to chase a number -- it is a
    # measurement overruling a proxy for it.
    #
    # Indices line up because `components()` filters then sorts by descending
    # area, so the fitter's list is a PREFIX of the labeller's whenever its
    # floor is coarser. Reading the floor out of the truth file removes even
    # that: both sides enumerate identically, and a key the truth does not carry
    # is a hard stop rather than a silent skip.
    truth = load_truth(folder)
    if truth is None:
        raise SystemExit(
            f"{folder.name}: print_truth.json is absent. Run "
            f"scripts/label_print.py --folder {folder.name} --init, classify "
            f"every component, and check with --verify. Falling back to the "
            f"heuristics is what put a blister in this spec.")
    if truth.get("front_face_px") != meta.get("front_face_px"):
        raise SystemExit(
            f"{folder.name}: print_truth.json was made against different face "
            f"corners. Re-run --init and re-classify; a stale label puts the "
            f"dropped object back in the spec with nothing in the log to say so.")
    label_of = {c["key"]: c.get("class") for c in truth["components"]}
    min_region = int(float(truth["enumerate_min_frac"]) * w * h)
    min_hole = int(MIN_HOLE_FRAC * w * h)

    # Enumerated once and read twice. The second reader is the lettering map
    # below, and re-running `components` for it would be both slow and a second
    # chance for the two enumerations to drift apart -- the defect this fitter
    # has already been bitten by, when verify()'s ground truth was indexed by a
    # different list from the fields it scored.
    parts_by_role = {role: components(mask, min_region)
                     for role, mask, _g in order}

    # Which holes the label calls windows. Everything else stays filled.
    hole_class = {c["key"]: c.get("class") for c in (truth.get("holes") or [])}
    if "holes" not in truth:
        raise SystemExit(
            f"{folder.name}: print_truth.json carries no `holes` section. That "
            f"is contract 1.8 -- run scripts/label_print.py --folder "
            f"{folder.name} --init and classify them. Cutting every hole prints "
            f"the reference's own lettering through our field.")
    hole_min = float(truth.get("hole_min_frac", MIN_HOLE_FRAC))
    if abs(hole_min - MIN_HOLE_FRAC) > 1e-12:
        raise SystemExit(
            f"{folder.name}: labelled at hole_min_frac {hole_min} against this "
            f"fitter's {MIN_HOLE_FRAC}; the two sides would enumerate different "
            f"holes. Re-run --init.")

    holes_kept: dict[str, int] = {}
    marks: list[dict] = []
    geometry_evidence = []
    for role, group_mask, g in order:
        # Masks kept beside the emitted parts because contract 1.9's colour rule
        # is a statement about the field's parts TOGETHER -- two of them within
        # SAME_SURFACE_MAX are one surface -- and cannot be decided one at a
        # time. Assigned after this loop, into a key placed here so the emitted
        # order stays as it reads.
        parts, masks = [], []
        for i, part in enumerate(parts_by_role[role]):
            key = f"{role}#{i}"
            if key not in label_of:
                raise SystemExit(
                    f"{folder.name}: {key} has no label. The partition has moved "
                    f"under print_truth.json -- re-run --init.")
            if label_of[key] != "print":
                # A `mark` the owner approved is drawn, and nothing else here is.
                # The class says what the region IS; `draw_marks` says what may
                # be done with it, and the two are kept apart deliberately -- a
                # reclassification must not become a permission.
                if key in draw_marks:
                    entry = _mark_entry(part, raw, w, h, role, key, "component",
                                        median_eroded_adaptive,
                                        min_hole=min_hole)
                    if entry is not None:
                        marks.append(entry)
                        kept_mask |= part
                        continue
                # Everything not printed design: an object in the photograph, a
                # letterform, the board split off by a gradient, a logo the owner
                # excluded, or something this vocabulary cannot hold. All of it
                # leaves the spec, and all of it leaves the scored area too --
                # `verify()` reads `~dropped_mask`, so a photograph is neither
                # drawn nor counted as a miss.
                dropped += 1
                dropped_by_class[label_of[key]] = dropped_by_class.get(label_of[key], 0) + 1
                continue
            kept_mask |= part
            outline = trace_outline(part)
            if len(outline) < 8:
                continue
            pts, used = _simplify_to_a_region(outline, w, h, SIMPLIFY_TOLERANCE)
            holes, kept, hole_marks = trace_holes(
                part, w, h, min_hole, key, hole_class, cut_marks)
            source_kind = part_kind(pts, holes)
            regularized = regularize_rectilinear_edge_band(part)
            if regularized is not None:
                pts = regularized
            # Which of the CUT rings are marks, by index. Without it the pairing
            # rule is unverifiable on a manifest: a mark hole and a window are
            # both just rings, so "a mark hole was cut and nothing drawn into
            # it" -- the case MARKS_DECISION.md forbids -- would be
            # indistinguishable from an ordinary window.
            mark_hole_idx = [holes.index(pts) for _k, pts, _m in hole_marks
                             if pts in holes]
            for cls, n in kept.items():
                holes_kept[cls] = holes_kept.get(cls, 0) + n
            # Cut and drawn from one loop, so a cut without its mark cannot be
            # produced at all. `validate_manifest` still refuses one on write and
            # on read, because a manifest can be edited and this loop cannot
            # defend a file it did not write.
            # NOT `pts` and not `mask`: `pts` is the PART's simplified outline
            # and it is read below, after this loop. Shadowing it here overwrote
            # every part's outline with its hole's -- measured, `74_Viagra`'s
            # `brand#0` came out a 47-vertex ring enclosing zero pixels and its
            # IoU fell 0.942 to 0.088.
            for hkey, hole_pts, hole_mask in hole_marks:
                entry = _mark_entry(hole_mask, raw, w, h, role, hkey, "hole",
                                    median_eroded_adaptive, outline=hole_pts)
                if entry is not None:
                    ink_parts = _disconnected_mark_ink(
                        hole_mask, group_mask, raw, w, h, median_eroded_adaptive)
                    if ink_parts:
                        entry['parts'] = ink_parts
                    marks.append(entry)
                    kept_mask |= hole_mask
            parts.append({
                # Geometry regularization must not change layout semantics: a
                # narrow field does not become a text-hosting block merely
                # because its outline is now a perfect rectangle.
                "kind": source_kind,
                **({"simplify_tolerance": round(used, 5)}
                   if used != SIMPLIFY_TOLERANCE else {}),
                "area_pct": round(100 * part.sum() / (w * h), 1),
                "smoothness": round(_smoothness(pts), 2),
                # Contract 1.9. Required and often equal to the field's, which
                # is the point: a 1.8 part read as 1.9 is not a part painted its
                # field's colour, it is a part whose colour is unknown.
                #
                # The part's own colour is taken ONLY where it is at least
                # SAME_SURFACE_MAX from the field's, and this threshold is the
                # whole difference between this attempt and the one that was
                # rolled back. Emitting every part's own colour regardless sends
                # eight of the 28 cartons to "palette not separable" -- measured
                # both times -- because two parts of one surface then become two
                # vocabulary entries a thousandth apart, and every
                # classification-based figure stops meaning anything.
                # Thresholded it is one carton, and that one degenerates for a
                # real reason: `64_Kamagra`'s corrected highlight sits 0.026 from
                # its own brand, because the photograph separates those two teals
                # by less than the spec does.
                #
                # The estimator is not the median. A part's median carries its
                # antialiased rim, which is what moved `60_Cialis_Professional`'s
                # 0.16% part by 0.259 last time; eroding by 0.35 of the part's
                # OWN thickness scores 0.0020 mean error on a bench with known
                # answers against the median's 0.0076. See
                # 00_PROJECT_STATE/PART_COLOUR.md.
                "fill": None,
                "outline": [[round(x / w, 4), round(y / h, 4)] for x, y in pts],
                # Always present, empty where the part has none: contract 1.8
                # makes this required so a spec written before it fails loudly
                # rather than filling a shape's holes in silence.
                "holes": [[[round(x / w, 4), round(y / h, 4)] for x, y in ring]
                          for ring in holes],
                # Contract 1.10, required and usually empty: indices into
                # `holes` that are approved MARKS rather than windows.
                "mark_holes": mark_hole_idx,
            })
            geometry_evidence.append((parts[-1], part, regularized is not None))
            masks.append(part)
        if not parts:
            continue
        # Every other entry the carton's vocabulary will hold: the board, and
        # each other field's own colour. A part's colour has to be tellable from
        # all of them, not only from its own field's.
        others = ([substrate["colour"]]
                  + [g2["colour"] for r2, _mask2, g2 in order if r2 != role])
        for emitted_part, colour in zip(
                parts, _part_fills(masks, raw, g["colour"], others)):
            emitted_part["fill"] = colour
        emitted.append((role, group_mask, g))
        fields.append({
            "role": role,
            # Paint order, made explicit. The list has always BEEN ordered --
            # `rasterise()` fills it front to back and every `pixel_agreement`
            # was measured against that -- but the contract never said so, and
            # the driver read the same list into ONE plane where no order
            # exists. Two readings of one record, which is how Adderall's teal
            # block came to be erased in the target and to z-fight in the
            # render. Emitted as the index it already has, so nothing moves;
            # what changes is that the order is now a value the driver can obey
            # rather than a convention it cannot see.
            "z": len(fields),
            "fill": _hex(g["colour"]),
            "coverage_pct": round(100 * group_mask.sum() / (w * h), 1),
            "parts": parts,
        })

    # What `verify()` is entitled to score: the board, plus the components the
    # label calls print. Everything else in a non-substrate cluster leaves --
    # objects, letterforms, logos, photographs, the board split off by a
    # gradient, AND the residue below the enumeration floor.
    #
    # The residue is why this is computed from `kept_mask` rather than
    # accumulated as parts are dropped. `truth` in verify() marks a whole
    # CLUSTER as its field, so any pixel of that cluster which is neither
    # emitted nor explicitly dropped reads as "the spec should have drawn here"
    # and never can be. Imovane is the case: its blue rule emits correctly and
    # scored 0.145 against 2.7% of unenumerated highlight residue.
    candidate_mask = np.zeros((h, w), bool)
    for _role, group_mask, _group in order:
        candidate_mask |= group_mask
    dropped_mask = candidate_mask & ~kept_mask

    # In front of every field, in the order they were found. A mark is printed
    # ON a surface, so it can never be behind one; the driver reads this the same
    # way it reads a field's `z`.
    for n, mark in enumerate(marks):
        mark["z"] = len(fields) + n

    spec = {
        "spec_version": "0.1",
        "sku": meta.get("sku_id"),
        "source_image": source,
        "face_aspect": round(h / w, 4),
        "coordinates": "u across, v down, both 0..1 of the FRONT FACE",
        "substrate": _hex(substrate["colour"]),
        "fields": fields,
        # Contract 1.10. Required and USUALLY EMPTY: 15 of the 28 folders carry
        # none. A spec that omits the key is not a carton with no marks, it is a
        # carton whose marks were never decided -- and the decision is a person's
        # (00_PROJECT_STATE/MARKS_DECISION.md), not a default this fitter may
        # supply.
        "marks": marks,
        # What the LABEL dropped, by class. This replaces the three counters the
        # heuristics kept (`glyph_components_dropped`, `flat_fields_dropped`,
        # `ink_components_dropped`); those counted which proxy fired, and no
        # proxy fires any more. A spec written before Phase B still carries them,
        # which is the point of keeping `design_spec.v01.json` beside it.
        "components_dropped": dropped,
        "dropped_by_class": dropped_by_class,
        # Not silent, for the same reason `dropped_by_class` is not: a hole the
        # fitter declined to cut is a place where the spec deliberately draws
        # over the reference, and the reader is entitled to see how often and
        # on what grounds.
        "holes_filled_by_class": holes_kept,
        "truth": TRUTH_NAME,
        "excluded": ("manufacturer logos and holographic elements are not "
                     "represented: the owner's decision, so the substrate shows "
                     "through where they sit on the reference"),
    }

    # This module owns the FIELDS. `measure_type_rows` owns `type_rows`, writes
    # into the same file, and runs after -- so rewriting the file wholesale
    # silently deleted its work, and the eleven manifests came back carrying
    # `"type_rows": {}` the next time Stage 1 ran. Found by diffing the
    # manifests rather than by anything failing, which is the wrong way to find
    # it. Carried forward rather than re-measured: the rows are measured off the
    # same rectified face this fit reads, so re-fitting the fields cannot
    # invalidate them. Re-setting the face CORNERS invalidates both, and that is
    # a different operation.
    spec_path = folder / "design_spec.json"
    if spec_path.exists():
        previous = json.loads(spec_path.read_text(encoding="utf-8"))
        preserve_manual_design_extensions(spec, previous)

    join_measured_edge_band(spec, geometry_evidence)
    close_matching_front_top_fold(spec, w, h)
    verification_spec = dict(spec)
    verification_spec["fields"] = [
        field for field in spec["fields"]
        if field.get("surface", "front") == "front"
    ]
    agreement = verify(verification_spec, lab, substrate_label, emitted,
                       w, h, preview_dir, folder, dropped_mask)
    spec["verification"] = agreement

    write_complete_spec(spec_path, spec, np.asarray(flat.convert("RGB")), truth)
    return spec


def part_region(part: dict, w: int, h: int) -> Image.Image | None:
    """The pixels a part covers: its outline MINUS its holes.

    Contract 1.8. One place, because the alternative is what this project has
    already paid for twice -- the spec's own raster, the QA target, the coverage
    instrument and the driver each deciding for themselves what a part covers,
    and a hole existing in some of them.

    Returned as a 1-bit mask rather than drawn straight into the caller's image
    so the fields can be composited in z order: a hole is a window onto whatever
    was painted before it, which on these cartons is the board and on Adderall
    another field.

    EVERY VERTEX GOES BACK ON THE PIXEL IT WAS TRACED FROM, because otherwise
    this reconstruction is not the inverse of the normalisation. Every vertex in
    these specs is an integer pixel index out of `trace_outline` --
    Douglas-Peucker and `simple_ring` both DROP vertices rather than move them
    -- stored as `round(x / w, 4)`, so `u * w` comes back within 0.0826 px of
    that integer and lands on either side of it. And PIL TRUNCATES a float
    polygon coordinate: measured on Pillow 12.2.0, a vertex at x - 0.02 fills as
    though it were at x - 1. A fortieth of a pixel of storage error therefore
    became a WHOLE pixel of displacement, signed differently vertex by vertex,
    across 94.52% of the 9912 coordinates this group holds. Rounding the product
    recovers the traced integer exactly, with 0.417 px of margin before the
    choice could be ambiguous.

    It shipped for one reader first and for all three afterwards, and the second
    step is why this is a plain function again rather than a function with a
    switch. A default that reconstructs a region somewhere other than where it
    was measured is not a default anyone should be able to take by accident, and
    a reader choosing its own idea of what a part covers is the exact defect the
    paragraph above this one exists to prevent.

    What it is NOT: an exact copy of the component. Against the 37 printed fields
    a person labelled, the reconstruction means an IoU of 0.9184 and none of the
    37 reaches 1.0000. That residue belongs to Douglas-Peucker and `_despeckle`,
    both deliberate, and nothing here touches it.
    """
    def at(coords):
        # Rounded AFTER the multiply, never before: `round(u * w) / w * w` can
        # come back a hair under the integer, and PIL would truncate that back
        # down a whole pixel -- the very defect this removes.
        return [(round(u * w), round(v * h)) for u, v in coords]

    poly = at(part.get("outline") or [])
    if len(poly) < 3:
        return None
    region = Image.new("1", (w, h), 0)
    d = ImageDraw.Draw(region)
    d.polygon(poly, fill=1)
    for ring in part.get("holes") or []:
        hole = at(ring)
        if len(hole) >= 3:
            d.polygon(hole, fill=0)
    return region


def rasterise(spec: dict, w: int, h: int) -> Image.Image:
    """Draw the spec back out. This is what makes the spec checkable.

    Contract 1.9: the colour is the PART's, not its field's. There is no
    fallback to the field's fill -- a part with no `fill` is a part whose colour
    is unknown, and painting it the field's is precisely the guess the contract
    exists to stop. The driver raises `SystemExit` on the same condition.
    """
    img = Image.new("RGB", (w, h), spec["substrate"])
    for f in spec["fields"]:
        if f.get("surface", "front") != "front":
            continue
        for part in f["parts"]:
            region = part_region(part, w, h)
            if region is not None:
                img.paste(part["fill"], (0, 0), region)
    # Contract 1.10, after every field and in `z` order: a mark is printed ON a
    # surface. Drawn here as well as in the render because this raster IS what
    # `design_qa` scores the render against -- a mark the target did not carry
    # would read as our render inventing one.
    for mark in sorted(spec.get("marks") or [], key=lambda m: m.get("z", 0)):
        from src.mark_geometry import drawable_mark_parts
        for part in drawable_mark_parts(mark):
            region = part_region(part, w, h)
            if region is not None:
                img.paste(part["fill"], (0, 0), region)
    return img


def verify(spec, lab, substrate_label, emitted, w, h, preview_dir, folder,
           dropped_mask=None) -> dict:
    """Agreement between the spec's own rasterisation and the segmentation.

    Compared as REGIONS, not colours: each pixel's spec region is recovered by
    drawing the fields into an index image the same way rasterise() draws them,
    so a field whose fill happens to resemble its neighbour cannot score as a
    match it did not earn.
    """
    spec_idx = np.full((h, w), 255, dtype=int)
    for n, f in enumerate(spec["fields"]):
        for part in f["parts"]:
            region = part_region(part, w, h)
            if region is not None:
                spec_idx[np.asarray(region)] = n
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
    mark_mask = np.zeros((h, w), bool)
    for mark in sorted(spec.get("marks") or [], key=lambda m: m.get("z", 0)):
        region = part_region(mark, w, h)
        if region is not None:
            mark_mask |= np.asarray(region)

    truth = np.full((h, w), 255, dtype=int)
    for n, (_role, group_mask, _g) in enumerate(emitted):
        truth[group_mask] = n

    # Glyph pixels are excluded from the score. The spec deliberately does not
    # carry letterforms -- type is drawn from the manifest's strings -- so
    # counting them as disagreement would penalise the spec for being right, and
    # would reward a spec that traced the reference's words back into the fields.
    scored = np.ones((h, w), bool) if dropped_mask is None else ~dropped_mask
    # CONTRACT 1.10, and the same exclusion `design_coverage` makes for the same
    # reason: this compares the spec's FIELDS against the segmentation's
    # clusters by region identity, and a mark is deliberately neither. Scoring
    # one here is a category error -- measured, indexing marks instead cost
    # `74_Viagra` 99.7% -> 98.4% and the group's `pixel_agreement` 99.18% ->
    # 98.90%, for marks it draws exactly where they are.
    #
    # Excluded on both sides, so cutting a mark hole and drawing into it is
    # NEUTRAL here rather than banking the gain that cutting alone earns. What
    # judges a mark is the render.
    scored = scored & ~mark_mask
    match = float((spec_idx == truth)[scored].mean())
    per_field = {}
    for n, f in enumerate(spec["fields"]):
        t = (truth == n) & scored
        sp = (spec_idx == n) & scored
        union = (t | sp).sum()
        per_field[f["role"]] = round(float((t & sp).sum() / union), 3) if union else None

    if preview_dir is not None:
        preview_dir.mkdir(parents=True, exist_ok=True)
        rasterise(spec, w, h).save(preview_dir / f"{folder.name}.spec.png")

    return {"pixel_agreement": round(match, 4),
            "excluded_as_glyphs_pct": (round(100 * float(dropped_mask.mean()), 2)
                                       if dropped_mask is not None else 0.0),
            "iou_by_field": per_field,
            "vertices": sum(len(p["outline"]) + sum(len(r) for r in (p.get("holes") or []))
                            for f in spec["fields"] for p in f["parts"])}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--folder")
    p.add_argument("--all", action="store_true")
    p.add_argument("--preview", action="store_true")
    args = p.parse_args()

    preview = (PROJECT_ROOT / "02_processing" / "reference_measurement") if args.preview else None
    if args.folder:
        folders = [TEMPLATES_DIR / args.folder]
    elif args.all:
        from scripts.make_ocr_fixtures import TEMPLATE_SAMPLE
        folders = [TEMPLATES_DIR / n for n in sorted(TEMPLATE_SAMPLE)]
    else:
        p.error("pass --folder NAME or --all")

    print(f"{'folder':32s} {'fields':>7s} {'verts':>6s} {'agreement':>10s}  IoU by field")
    for folder in folders:
        if not (folder / "metadata.json").exists():
            continue
        spec = fit(folder, preview)
        v = spec["verification"]
        ious = " ".join(f"{k}={x}" for k, x in v["iou_by_field"].items())
        print(f"{folder.name:32s} {len(spec['fields']):7d} {v['vertices']:6d} "
              f"{100 * v['pixel_agreement']:9.1f}%  {ious}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
