"""Tests for src/vectorise.py — the tracer, and the two ways of reading it wrong.

Every failure this file pins produces a ring that LOOKS like geometry. None of
them raises, none of them returns an empty list, and each one scores near zero
against the mask it came from. That is why they are tested by construction here
rather than left to be noticed as a bad number on one carton.
"""
import unittest

import numpy as np

from src.vectorise import (
    FLATTEN_TOLERANCE_PX, Ring, VectoriseFailed, outer_ring, parse_svg_rings,
    vectorise,
)


def _fill(points, w, h) -> np.ndarray:
    """Even-odd raster of a polygon, the same rule the rest of the project fills by."""
    from PIL import Image, ImageDraw
    img = Image.new("1", (w, h), 0)
    ImageDraw.Draw(img).polygon([(float(x), float(y)) for x, y in points], fill=1)
    return np.asarray(img)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    union = (a | b).sum()
    return float((a & b).sum() / union) if union else 0.0


class TestTheSvgTrapsThatGiveAPlausibleWrongRing(unittest.TestCase):
    """Both were named in the brief as having already produced an IoU near zero."""

    def test_a_command_repeats_implicitly_so_twelve_numbers_are_two_cubics(self):
        """`C` with twelve numbers is TWO curves. Reading six drops half the ring.

        The SVG grammar repeats the last command for as long as its arguments
        last. A parser that consumes one command's worth and discards the rest
        loses geometry silently -- the ring still closes, because closure is
        implied, so what comes back is a smaller shape that raises nothing.
        """
        one_at_a_time = ('<path d="M0 0 C10 0 20 0 30 0 C30 10 30 20 30 30 '
                         'C20 30 10 30 0 30 C0 20 0 10 0 0 Z"/>')
        run_together = ('<path d="M0 0 C10 0 20 0 30 0 30 10 30 20 30 30 '
                        '20 30 10 30 0 30 0 20 0 10 0 0 Z"/>')
        a, = parse_svg_rings(one_at_a_time)
        b, = parse_svg_rings(run_together)
        self.assertEqual(len(a.segments), 4)
        self.assertEqual(
            len(b.segments), 4,
            "the run-together form was read as one curve, so three of the "
            "square's four sides were dropped")
        self.assertEqual([tuple(map(tuple, s)) for s in a.segments],
                         [tuple(map(tuple, s)) for s in b.segments])

    def test_the_transform_is_after_the_d_attribute_and_must_still_be_applied(self):
        """vtracer writes `d` from the origin and carries position in `translate`.

        All 75 of the group's printed components come back with one. The
        attribute sits AFTER `d`, so a reader that finds `d` and stops returns
        the right shape at the origin -- which for a component anywhere but the
        top-left corner of the face has almost no overlap with itself.
        """
        tag = ('<path d="M0 0 C10 0 20 0 30 0 C30 10 30 20 30 30 '
               'C20 30 10 30 0 30 C0 20 0 10 0 0 Z" '
               'transform="translate(400,250)"/>')
        ring, = parse_svg_rings(tag)
        x0, y0, x1, y1 = ring.bbox()
        self.assertAlmostEqual(x0, 400.0, places=6)
        self.assertAlmostEqual(y0, 250.0, places=6)
        self.assertAlmostEqual(x1, 430.0, places=6)
        self.assertAlmostEqual(y1, 280.0, places=6)

    def test_ignoring_the_transform_would_have_scored_near_zero(self):
        """The failure mode, made a number rather than an assertion about a string.

        Same ring parsed with and without its translate, rasterised and compared
        the way every other region in this project is compared.
        """
        d = ('M0 0 C40 0 80 0 120 0 C120 40 120 80 120 120 '
             'C80 120 40 120 0 120 C0 80 0 40 0 0 Z')
        placed, = parse_svg_rings(f'<path d="{d}" transform="translate(300,300)"/>')
        at_origin, = parse_svg_rings(f'<path d="{d}"/>')
        got = _iou(_fill(placed.flatten(), 512, 512),
                   _fill(at_origin.flatten(), 512, 512))
        self.assertEqual(
            got, 0.0,
            "these two rings overlap, so this test is no longer demonstrating "
            "the failure it was written for")

    def test_an_unsupported_command_stops_rather_than_being_approximated(self):
        """`A` as a line would be a ring that looks right and is not."""
        with self.assertRaises(VectoriseFailed):
            parse_svg_rings('<path d="M0 0 A5 5 0 0 1 10 10 Z"/>')


class TestFlattening(unittest.TestCase):
    def test_a_straight_edge_costs_one_point_however_fine_the_tolerance(self):
        """vtracer emits a straight edge as a cubic with collinear controls.

        Spending a fixed number of points per segment would have inflated every
        rectangle in the catalogue for nothing; the tolerance is adaptive so it
        does not.
        """
        square, = parse_svg_rings(
            '<path d="M0 0 C10 0 20 0 30 0 C30 10 30 20 30 30 '
            'C20 30 10 30 0 30 C0 20 0 10 0 0 Z"/>')
        self.assertEqual(len(square.flatten(0.25)), 4)
        self.assertEqual(len(square.flatten(0.001)), 4)

    def test_a_curve_is_never_further_from_its_flattening_than_the_tolerance(self):
        """The property the manifest's stated resolution will rest on."""
        ring, = parse_svg_rings(
            '<path d="M0 100 C0 44.77 44.77 0 100 0 C155.23 0 200 44.77 200 100 '
            'C200 155.23 155.23 200 100 200 C44.77 200 0 155.23 0 100 Z"/>')
        for tol in (1.0, 0.25, 0.05):
            pts = np.asarray(ring.flatten(tol), dtype=float)
            # Every flattened vertex is ON the curve, so measure the other way:
            # the chord midpoints must not depart from the circle further than
            # the tolerance allows.
            mid = (pts + np.roll(pts, -1, axis=0)) / 2.0
            r = np.hypot(mid[:, 0] - 100.0, mid[:, 1] - 100.0)
            with self.subTest(tolerance=tol):
                self.assertLess(float(np.abs(r - 100.0).max()), tol + 1e-9)

    def test_a_finer_tolerance_never_costs_fewer_points(self):
        ring, = parse_svg_rings(
            '<path d="M0 100 C0 44.77 44.77 0 100 0 C155.23 0 200 44.77 200 100 '
            'C200 155.23 155.23 200 100 200 C44.77 200 0 155.23 0 100 Z"/>')
        counts = [len(ring.flatten(t)) for t in (2.0, 1.0, 0.5, 0.25, 0.1)]
        self.assertEqual(counts, sorted(counts))


class TestASyntheticShapeWithKnownGeometry(unittest.TestCase):
    """Step 14 of the migration brief: a disc of radius 150 with a 60x60 square
    hole, in a 400x400 field. The reference run this was specified against gave
    an IoU of 0.9909 at 33 control points.
    """

    W = H = 400
    RADIUS = 150
    HOLE = 60

    @classmethod
    def setUpClass(cls):
        yy, xx = np.mgrid[0:cls.H, 0:cls.W]
        cy = cx = 200
        disc = (xx - cx) ** 2 + (yy - cy) ** 2 <= cls.RADIUS ** 2
        half = cls.HOLE // 2
        hole = ((np.abs(xx - cx) < half) & (np.abs(yy - cy) < half))
        cls.mask = disc & ~hole
        cls.rings = vectorise(cls.mask)

    def test_the_disc_and_its_hole_both_come_back(self):
        self.assertEqual(len(self.rings), 2,
                         "expected the outer ring and one hole")

    def test_the_region_is_recovered_to_better_than_a_hundredth(self):
        outer = _fill(self.rings[0].flatten(), self.W, self.H)
        hole = _fill(self.rings[1].flatten(), self.W, self.H)
        got = _iou(outer & ~hole, self.mask)
        self.assertGreaterEqual(
            got, 0.99,
            f"IoU {got:.4f} against a shape with an exact answer; the brief's "
            f"reference run reached 0.9909")

    def test_it_costs_no_more_than_forty_control_points(self):
        """A curve that needs a point per pixel is a polyline with extra steps.

        Counted as THREE per segment -- the two handles and the on-curve end --
        which is how the brief's reference run reached 33. Counting segments
        instead would make this assert a third of what it says.
        """
        n = 3 * sum(len(r.segments) for r in self.rings)
        self.assertLessEqual(
            n, 40,
            f"{n} control points for a disc with a square hole; the brief's "
            f"reference run used 33")

    def test_the_hole_is_the_square_and_not_a_second_blob(self):
        x0, y0, x1, y1 = self.rings[1].bbox()
        for got, want in ((x1 - x0, self.HOLE), (y1 - y0, self.HOLE)):
            self.assertAlmostEqual(got, want, delta=3.0)

    def test_the_same_mask_gives_the_same_rings_every_time(self):
        """Determinism is a project invariant and vtracer takes no seed."""
        again = vectorise(self.mask)
        self.assertEqual(
            [[tuple(map(tuple, s)) for s in r.segments] for r in again],
            [[tuple(map(tuple, s)) for s in r.segments] for r in self.rings])


class TestAnEmptyAnswerIsNotAnAnswer(unittest.TestCase):
    def test_a_mask_with_nothing_in_it_raises(self):
        with self.assertRaises(VectoriseFailed):
            outer_ring(np.zeros((64, 64), bool))


class TestPolarity(unittest.TestCase):
    def test_the_outer_ring_is_the_component_and_not_the_frame(self):
        """`binary` traces the DARK pixels, which is not documented anywhere.

        Painted the other way round the first ring comes back as the whole
        image, and every measurement after it describes the background.
        """
        mask = np.zeros((200, 200), bool)
        mask[60:140, 40:120] = True
        ring = outer_ring(mask)
        x0, y0, x1, y1 = ring.bbox()
        self.assertGreater(x0, 5.0, "the outer ring starts at the image edge, "
                                    "so it is the frame, not the component")
        self.assertLess(x1, 195.0)
        got = _iou(_fill(ring.flatten(), 200, 200), mask)
        self.assertGreater(got, 0.97, f"IoU {got:.4f} against a plain rectangle")


class TestNothingInThePipelineUsesThisModule(unittest.TestCase):
    """This module is an INSTRUMENT, not a stage, and the difference must hold.

    Replacing the Moore-walk tracer with a curve fit was built, measured against
    all 75 printed components of the design group, and rejected. Like for like
    against each component's own pixels the spline scores 0.8649 where the
    shipped polyline scores 0.8855, and no setting of `filter_speckle`,
    `corner_threshold` or `length_threshold` reaches the polyline at all -- the
    whole parameter space runs 0.8588 to 0.8649. Wired into `fit()` it took the
    group's `truth_agreement` from 95.36% to 94.19%.

    THE FIGURE THAT MOTIVATED IT WAS NOT ABOUT THE TRACER. "0.954 against 0.888"
    is the same polyline scored two ways -- every hole cut against the outer ring
    alone (0.9536 and 0.8855). The gain belonged to the holes, and cutting every
    hole is what contract 1.8 forbids: `404_Ritalin`'s 72 holes spell another
    package's brand and dose.

    WHY IT IS KEPT ANYWAY. It is the only implementation in the tree of the two
    SVG traps -- a path command repeating implicitly, and `transform="translate"`
    written AFTER the `d` attribute -- and those cost three earlier runs of this
    experiment before they were understood. Deleting it means the next attempt
    derives them again. The cost is one declared dependency.

    WHAT THIS TEST IS FOR. A module that sits in `src/` beside the real stages,
    carries no warning at its import site, and is one line away from being used,
    is a module that gets used. This makes that line fail.
    """

    #: The files that may import it. Everything else in the tree may not.
    ALLOWED = {"tests/test_vectorise.py"}

    def _roots(self):
        from src.utils import PROJECT_ROOT
        for sub in ("src", "scripts", "05_assets/blender", "tests"):
            root = PROJECT_ROOT / sub
            if root.exists():
                yield PROJECT_ROOT, root

    def test_no_file_outside_its_own_test_imports_it(self):
        import re
        pattern = re.compile(r"^\s*(?:from\s+src\.vectorise\b|import\s+src\.vectorise\b"
                             r"|from\s+\.vectorise\b|import\s+vectorise\b)", re.M)
        offenders = []
        for project_root, root in self._roots():
            for path in sorted(root.rglob("*.py")):
                rel = path.relative_to(project_root).as_posix()
                if rel == "src/vectorise.py" or rel in self.ALLOWED:
                    continue
                if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                    offenders.append(rel)
        self.assertEqual(
            offenders, [],
            f"{offenders} import src.vectorise. It is a measured and REJECTED "
            f"alternative tracer kept as an instrument -- see "
            f"00_PROJECT_STATE/TOOLING_MIGRATION.md section 2. Wiring it in "
            f"costs the group 1.17 points of truth_agreement.")

    def test_importing_the_pipeline_does_not_pull_it_in(self):
        """The static check above misses a dynamic import; this one does not."""
        import subprocess
        import sys as _sys
        from src.utils import PROJECT_ROOT
        code = (
            "import sys;"
            "import src.design_group, src.render_manifest;"
            "import scripts.fit_design_spec, scripts.measure_reference_face;"
            "import scripts.design_coverage;"
            "print('src.vectorise' in sys.modules)"
        )
        out = subprocess.run([_sys.executable, "-c", code], cwd=str(PROJECT_ROOT),
                             capture_output=True, text=True, timeout=300)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertEqual(
            out.stdout.strip().splitlines()[-1], "False",
            "importing the design pipeline pulled src.vectorise in with it")


class TestConstantsAreFixedAndNotTuned(unittest.TestCase):
    """The brief forbids tuning a vectoriser parameter for one carton's number.

    Pinned so that doing it requires editing a test that says not to.
    """

    def test_the_parameters_are_module_constants(self):
        import src.vectorise as v
        self.assertEqual(v.COLORMODE, "binary")
        self.assertEqual(v.MODE, "spline")
        self.assertEqual(v.HIERARCHICAL, "stacked")
        self.assertEqual(v.FILTER_SPECKLE, 4)
        self.assertEqual(v.CORNER_THRESHOLD, 60)
        self.assertEqual(v.LENGTH_THRESHOLD, 4.0)
        self.assertEqual(v.PATH_PRECISION, 8)
        self.assertEqual(FLATTEN_TOLERANCE_PX, 0.25)

    def test_a_ring_is_immutable(self):
        ring = Ring((((0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)),))
        with self.assertRaises(Exception):
            ring.segments = ()


if __name__ == "__main__":
    unittest.main()
