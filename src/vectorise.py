"""The one place this project calls a vectoriser, and the one place it parses SVG.

`trace_outline` in `scripts/fit_design_spec.py` walks the Moore neighbourhood of
a mask and returns a closed ring of INTEGER PIXEL INDICES. That is a correct
boundary and a poor description: a printed curve comes back as a staircase, and
Douglas-Peucker then throws away the staircase's steps at a tolerance measured to
cost 0.891% of the printed area. The loss is not the simplifier's -- it is the
primitive's. A polyline has no way to say "this edge is an arc".

vtracer fits cubic Béziers to the same mask. Measured over the group's 75 printed
components, against the component's own pixels: **0.954 mean IoU against 0.888**
for the shipped polyline path.

WHY IT IS CALLED PER COMPONENT AND NEVER ON THE FACE. Running a vectoriser over
the whole rectified face would enumerate regions by colour, which is a second
opinion about what is printed on this carton -- and this project already decided,
twice and with measurements, that the opinion which counts is a person's. The
caller selects a component through `components()` and `print_truth.json` first;
this module is handed a mask and asked only what shape it is.

TWO PROPERTIES OF vtracer'S OUTPUT THAT ARE NOT DOCUMENTED AND BOTH BITE.

*Polarity.* `colormode="binary"` traces the DARK pixels. Painted white-on-black,
the first path comes back as the whole image rectangle with the component as an
inner subpath, followed by one path per island -- the inverse of what was asked
for, and it fills as the complement. Painted black-on-white it returns one path
whose first subpath is the component. Measured on all 75: one `<path>` element
every time, outer ring first, holes after.

*Placement.* Every path's `d` is written from the ORIGIN and its position is
carried in `transform="translate(dx, dy)"`, which appears AFTER the `d`
attribute. All 75 carry one. A reader that takes `d` and stops gets a ring of the
right shape in the wrong place, which scores an IoU near zero against the mask it
came from.

AND ONE PROPERTY OF SVG ITSELF, which did not fire here and is handled anyway.
A path command repeats implicitly: `C` followed by twelve numbers is TWO cubics,
not one cubic and some noise. vtracer 0.6.12 (the core this 0.6.15 wheel bundles)
writes one command per segment, so **0 of the group's 75 components exercise it**
-- but the guarantee wanted here is about the parser, not about the version that
happens to be installed, and a parser that reads six numbers and discards the
rest drops half of every long command in silence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

#: vtracer's own parameters, fixed as constants so a run is reproducible.
#: DETERMINISM IS A PROJECT INVARIANT: vtracer takes no seed and none of these
#: is adaptive, so the same mask gives the same rings on every run and on every
#: machine. Nothing here may become "whatever looks best on this carton" -- the
#: brief forbids tuning a parameter for one folder's number, and these were
#: chosen once, against the group.
#:
#: binary, because the input is a mask. `stacked` rather than `cutout` so the
#: holes arrive as subpaths of the component's own path instead of as separate
#: shapes that would then have to be matched back to it.
COLORMODE = "binary"
HIERARCHICAL = "stacked"
#: spline is the whole point. `polygon` would return the staircase this module
#: exists to stop storing.
MODE = "spline"
#: Islands below this many pixels are dropped. 4 is vtracer's own default and it
#: is left there deliberately: raising it starts deleting real holes, and the
#: holes this project cuts are chosen by a person, not by area -- the smallest
#: window in the group is Kamagra's at 0.053% of the face. Lowering it fits
#: splines to single-pixel speckle.
FILTER_SPECKLE = 4
#: Degrees. Below this a corner is fitted as a smooth join, above it as a corner.
#: 60 is vtracer's default; the printed shapes here are a mix of true arcs (the
#: Cialis swoosh) and true rectangles (every dosage block), and the default
#: separates them without preferring either.
CORNER_THRESHOLD = 60
#: Segments shorter than this are spliced out rather than fitted.
LENGTH_THRESHOLD = 4.0
#: Decimal places vtracer prints. High, because the coordinates are divided by
#: the face width before storage and the spec keeps four decimals of THAT --
#: rounding twice is how a fortieth of a pixel became a whole one the last time
#: this project looked (see `part_region`).
PATH_PRECISION = 8

#: How far a flattening may depart from the curve it describes, in pixels of the
#: rectified face. A QUARTER PIXEL, and the number is chosen against what reads
#: the flattening rather than against the eye: the face is rectified to 1100px
#: and rasterised at that size, so anything under half a pixel cannot move a
#: filled pixel. A quarter leaves margin for the two roundings between here and
#: `part_region`.
#:
#: Adaptive rather than a fixed number of points per segment, and that is what
#: keeps the vertex count sane: vtracer emits a straight edge as a cubic with
#: collinear controls, which subdivides to ONE point at any tolerance, while a
#: tight arc gets as many as it needs. A flat 8-per-segment would have inflated
#: every rectangle eightfold for nothing.
FLATTEN_TOLERANCE_PX = 0.25

_NUM = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_PATH = re.compile(r"<path\b[^>]*?/?>")
_D_ATTR = re.compile(r'\sd="([^"]*)"')
_TRANSLATE = re.compile(r'transform="translate\(([^)]*)\)"')
_COMMAND = re.compile(r"([A-Za-z])([^A-Za-z]*)")

#: Numbers each SVG path command consumes before it repeats implicitly.
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}


class VectoriseFailed(RuntimeError):
    """The vectoriser could not describe this mask.

    Raised rather than returning an empty list, and the caller turns it into a
    `SystemExit` naming the part. A component a person classified as printed
    design that comes back as no shape at all is a contradiction between two
    instruments, not a part with nothing in it.
    """


@dataclass(frozen=True)
class Ring:
    """A closed cubic Bézier ring, in PIXELS of the rectified face.

    `segments` is a tuple of `(p0, c1, c2, p3)`, each point an `(x, y)` pair,
    with `p3 == segments[i + 1][0]` throughout and the last segment closing back
    onto the first's `p0`. A straight edge is a cubic whose controls lie on the
    chord, which is how vtracer emits one and how `flatten` recovers it as a
    single point.
    """

    segments: tuple[tuple[tuple[float, float], ...], ...]

    def anchors(self) -> list[tuple[float, float]]:
        """The on-curve points, one per segment. NOT a description of the ring.

        Useful for a bounding box or a centroid; useless as geometry, because
        the whole point of a spline is what happens between its anchors. Use
        `flatten` for anything that fills.
        """
        return [tuple(seg[0]) for seg in self.segments]

    def flatten(self, tolerance_px: float = FLATTEN_TOLERANCE_PX
                ) -> list[tuple[float, float]]:
        """The ring as a polyline that never departs from it by more than *tolerance_px*.

        Recursive midpoint subdivision against the flatness of each segment. The
        returned list is the ring's vertices in order, without repeating the
        first point at the end -- the closure is implied, the way every ring in
        this project is stored.
        """
        pts: list[tuple[float, float]] = []
        for p0, c1, c2, p3 in self.segments:
            pts.append(tuple(p0))
            _subdivide(p0, c1, c2, p3, tolerance_px, pts, depth=0)
        return pts

    def bbox(self, tolerance_px: float = FLATTEN_TOLERANCE_PX):
        xs = [p[0] for p in self.flatten(tolerance_px)]
        ys = [p[1] for p in self.flatten(tolerance_px)]
        return min(xs), min(ys), max(xs), max(ys)


#: Guard on the subdivision, so a degenerate control polygon cannot recurse
#: forever. 2**16 points per segment is far past anything a 1100px face can use.
_MAX_DEPTH = 16


def _subdivide(p0, c1, c2, p3, tol, out, depth):
    """Append the interior points of one cubic, coarsest that still fits *tol*."""
    if depth >= _MAX_DEPTH or _is_flat(p0, c1, c2, p3, tol):
        return
    # de Casteljau at t = 0.5
    def mid(a, b):
        return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)

    a, b, c = mid(p0, c1), mid(c1, c2), mid(c2, p3)
    d, e = mid(a, b), mid(b, c)
    m = mid(d, e)
    _subdivide(p0, a, d, m, tol, out, depth + 1)
    out.append(m)
    _subdivide(m, e, c, p3, tol, out, depth + 1)


def _is_flat(p0, c1, c2, p3, tol) -> bool:
    """Do both control points lie within *tol* of the chord?

    The standard bound: a cubic stays within the convex hull of its control
    polygon, so a control point close to the chord bounds the curve's own
    departure from it. Degenerate chord (a closed loop of zero length) is never
    flat, so it subdivides until the depth guard stops it rather than returning
    a single point for a shape with area.
    """
    dx, dy = p3[0] - p0[0], p3[1] - p0[1]
    n = (dx * dx + dy * dy) ** 0.5
    if n == 0.0:
        return (abs(c1[0] - p0[0]) <= tol and abs(c1[1] - p0[1]) <= tol
                and abs(c2[0] - p0[0]) <= tol and abs(c2[1] - p0[1]) <= tol)
    for c in (c1, c2):
        if abs(dy * c[0] - dx * c[1] + p3[0] * p0[1] - p3[1] * p0[0]) / n > tol:
            return False
    return True


def parse_svg_rings(svg: str) -> list[Ring]:
    """Every closed subpath in *svg*, in document order, as cubic Bézier rings.

    Both of the traps named in this module's docstring are handled here and both
    are pinned by tests, because each of them produces a plausible-looking ring
    that scores near zero against the mask it came from:

    - `transform="translate(dx, dy)"` is applied. It sits AFTER `d` in every path
      vtracer writes, so a reader that stops at `d` never sees it.
    - a command's arguments are consumed in groups of its arity until they run
      out, so `C` with twelve numbers becomes two cubics rather than one.

    Lines (`L`, `H`, `V`, and the implicit `L` after an `M`) become cubics with
    their controls on the chord, so a caller never has to ask which kind of
    segment it is holding.
    """
    rings: list[Ring] = []
    for tag in _PATH.findall(svg):
        d_match = _D_ATTR.search(tag)
        if d_match is None:
            continue
        dx = dy = 0.0
        tr = _TRANSLATE.search(tag)
        if tr is not None:
            vals = [float(v) for v in _NUM.findall(tr.group(1))]
            dx = vals[0] if vals else 0.0
            dy = vals[1] if len(vals) > 1 else 0.0

        segments: list = []
        pen = start = (0.0, 0.0)
        for cmd, raw in _COMMAND.findall(d_match.group(1)):
            up = cmd.upper()
            if up == "Z":
                if segments:
                    rings.append(_close(segments, start))
                    segments = []
                pen = start
                continue
            if up not in _ARITY:
                continue
            vals = [float(v) for v in _NUM.findall(raw)]
            arity = _ARITY[up]
            if not vals or len(vals) < arity:
                continue
            relative = cmd.islower()
            first = True
            for k in range(0, len(vals) - arity + 1, arity):
                a = vals[k:k + arity]
                if up == "M":
                    if first:
                        pen = start = _pt(a[0], a[1], pen, relative, dx, dy)
                        if segments:
                            rings.append(_close(segments, start))
                            segments = []
                    else:
                        # A second coordinate pair after M is an implicit L.
                        nxt = _pt(a[0], a[1], pen, relative, dx, dy)
                        segments.append(_line(pen, nxt))
                        pen = nxt
                elif up in ("L", "H", "V"):
                    if up == "H":
                        nxt = ((pen[0] + a[0]) if relative else (a[0] + dx), pen[1])
                    elif up == "V":
                        nxt = (pen[0], (pen[1] + a[0]) if relative else (a[0] + dy))
                    else:
                        nxt = _pt(a[0], a[1], pen, relative, dx, dy)
                    segments.append(_line(pen, nxt))
                    pen = nxt
                elif up == "C":
                    c1 = _pt(a[0], a[1], pen, relative, dx, dy)
                    c2 = _pt(a[2], a[3], pen, relative, dx, dy)
                    p3 = _pt(a[4], a[5], pen, relative, dx, dy)
                    segments.append((pen, c1, c2, p3))
                    pen = p3
                elif up == "Q":
                    q = _pt(a[0], a[1], pen, relative, dx, dy)
                    p3 = _pt(a[2], a[3], pen, relative, dx, dy)
                    segments.append(_from_quadratic(pen, q, p3))
                    pen = p3
                else:
                    # S, T and A are not emitted by vtracer in any mode this
                    # project uses. Silently approximating one as a line would
                    # be a ring that looks right and is not, so it stops.
                    raise VectoriseFailed(
                        f"SVG command {cmd!r} is not supported by this parser; "
                        f"the ring would be wrong in a way nothing downstream "
                        f"could detect.")
                first = False
        if segments:
            rings.append(_close(segments, start))
    return rings


def _pt(x, y, pen, relative, dx, dy):
    return (pen[0] + x, pen[1] + y) if relative else (x + dx, y + dy)


def _line(a, b):
    """A straight edge as a cubic, controls on the chord.

    So that every segment this module yields is the same kind of thing. `flatten`
    recognises it as flat at any tolerance and spends one point on it.
    """
    return (a, (a[0] + (b[0] - a[0]) / 3.0, a[1] + (b[1] - a[1]) / 3.0),
            (a[0] + 2 * (b[0] - a[0]) / 3.0, a[1] + 2 * (b[1] - a[1]) / 3.0), b)


def _from_quadratic(p0, q, p2):
    return (p0,
            (p0[0] + 2.0 / 3.0 * (q[0] - p0[0]), p0[1] + 2.0 / 3.0 * (q[1] - p0[1])),
            (p2[0] + 2.0 / 3.0 * (q[0] - p2[0]), p2[1] + 2.0 / 3.0 * (q[1] - p2[1])),
            p2)


def _close(segments: list, start) -> Ring:
    """Close the ring back onto its start if the path did not."""
    last = segments[-1][3]
    if abs(last[0] - start[0]) > 1e-9 or abs(last[1] - start[1]) > 1e-9:
        segments = segments + [_line(last, start)]
    return Ring(tuple(tuple(seg) for seg in segments))


def _svg_for(mask: np.ndarray) -> str:
    """Run vtracer over *mask*, painted the way `binary` mode expects.

    BLACK ON WHITE. `colormode="binary"` traces the dark pixels, so painting the
    component white returns its complement -- the frame with a hole in it -- and
    every ring after that is describing the background.
    """
    import vtracer

    h, w = mask.shape
    rgba = np.empty((h, w, 4), dtype=np.uint8)
    rgba[...] = (255, 255, 255, 255)
    rgba[mask] = (0, 0, 0, 255)
    pixels = [tuple(int(v) for v in px) for px in rgba.reshape(-1, 4)]
    return vtracer.convert_pixels_to_svg(
        pixels, size=(w, h),
        colormode=COLORMODE, hierarchical=HIERARCHICAL, mode=MODE,
        filter_speckle=FILTER_SPECKLE, corner_threshold=CORNER_THRESHOLD,
        length_threshold=LENGTH_THRESHOLD, path_precision=PATH_PRECISION,
    )


def vectorise(mask: np.ndarray) -> list[Ring]:
    """Every ring vtracer finds in *mask*, outer ring first.

    Measured over the group's 75 printed components: one `<path>` element per
    mask, its first subpath the outer boundary and the rest its holes.

    The holes are RETURNED but this project does not enumerate them from here --
    `enclosed_background()` does, because that is the enumerator
    `print_truth.json` was labelled against and a hole's identity has to come
    from the same place its class does. They are here so a caller can compare
    the two, which is what `hole_disagreement()` is for.
    """
    rings = parse_svg_rings(_svg_for(mask))
    if not rings:
        raise VectoriseFailed(
            f"vtracer returned no ring for a mask of {int(mask.sum())} pixels. "
            f"An empty list is not an answer here: a component a person "
            f"classified as printed design cannot have no shape.")
    return rings


def outer_ring(mask: np.ndarray) -> Ring:
    """The boundary of *mask*, as a cubic Bézier ring.

    The single entry point the fitter uses, for a component and for each hole it
    has already decided to cut. One mask in, one ring out: the caller has
    already decided WHICH region this is, and this module only says what shape
    it has.
    """
    return vectorise(mask)[0]


def hole_disagreement(mask: np.ndarray, enumerated: int) -> int:
    """How many rings vtracer found beyond the outer one, minus *enumerated*.

    Diagnostic only. The two enumerations do not have to agree and the project
    does not act on the difference -- `enclosed_background()` decides, because
    the labels are keyed to it -- but a widening gap is worth being able to see,
    since it means the two instruments are describing different regions.
    """
    return (len(vectorise(mask)) - 1) - enumerated
