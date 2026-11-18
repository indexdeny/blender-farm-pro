"""D-6's instrument has to be able to see a design failing.

`design_qa.py` is the one place the design channel is read from, and it had no
tests. The defect that made the case: agreement is area-weighted and a substrate
is 55-99.9% of these faces, so the headline figure moves very little whatever
happens to a field -- and the per-field IoU column, which is where a failure
would show, was being computed over a mask that dropped every dark field
*exactly where our render painted it correctly*.

The result was a report whose ranking was inverted. Ritalin held the group's
BEST agreement, 99.87%, with an IoU of 0.043 on its only field; Cialis, the
worst agreement in the group, had the third-best fields. Both figures were
honest arithmetic over the wrong set of pixels.

These are synthetic: the properties are about masks and index maps, and stating
them in pixels is clearer and faster than rendering a carton to demonstrate one.
"""
import json
import unittest
from pathlib import Path

import numpy as np

from scripts.design_qa import (
    DARK_V, LUMA, _agreement, _front_palette_entries, scored_mask,
)
from src.utils import PROJECT_ROOT


def _hex(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])


class TestFrontPaletteBoundary(unittest.TestCase):
    def test_top_and_left_fields_do_not_enter_front_face_scoring(self):
        spec = {
            "substrate": "#FFFFFF",
            "fields": [
                {"role": "front", "surface": "front",
                 "parts": [{"fill": "#001122"}]},
                {"role": "top_duplicate", "surface": "top",
                 "parts": [{"fill": "#001122"}]},
                {"role": "left", "surface": "left",
                 "parts": [{"fill": "#AABBCC"}]},
            ],
        }
        fields, entries, to_field = _front_palette_entries(spec)
        self.assertEqual([field["role"] for field in fields], ["front"])
        self.assertEqual(entries, [("substrate", "#FFFFFF"),
                                   ("front", "#001122")])
        self.assertEqual(to_field, [0, 1])


class TestADarkFieldIsScoredWhereTheSpecExpectsOne(unittest.TestCase):
    """The dark cut keeps printed TYPE out of the figures, not dark FIELDS.

    Ritalin's `#2E1D3C` is its only field. Under the bare brightness cut its own
    pixels were dropped, so the field was scored only over the pixels our render
    got WRONG, and reported 0.043 against a render that places it correctly.
    """

    SUBSTRATE, FIELD = "#C0C0C0", "#2E1D3C"
    N, LO, HI, SHIFT = 100, 20, 80, 2

    def setUp(self):
        self.palette = np.stack([_hex(self.SUBSTRATE), _hex(self.FIELD)])
        # The spec draws one dark panel; our render places it two pixels off.
        self.spec = np.zeros((self.N, self.N), dtype=int)
        self.spec[self.LO:self.HI, self.LO:self.HI] = 1
        self.ours = np.zeros((self.N, self.N), dtype=int)
        self.ours[self.LO + self.SHIFT:self.HI + self.SHIFT,
                  self.LO + self.SHIFT:self.HI + self.SHIFT] = 1
        self.frame = self.palette[self.ours]

    def test_the_bare_brightness_cut_scores_only_our_mistakes(self):
        """The defect, stated so it cannot come back unnoticed."""
        bare = self.frame.max(-1) >= DARK_V
        self.assertFalse(bare[self.ours == 1].any(),
                         "the field our render painted is dropped entirely")
        self.assertEqual(_agreement(self.ours, self.spec, bare, 2)["iou"][1], 0.0,
                         "leaving the field scored over the misses alone")

    def test_the_field_is_scored_on_what_the_spec_expects_there(self):
        m = scored_mask(self.frame, self.palette, self.spec)
        interior = np.zeros_like(self.spec, dtype=bool)
        interior[self.LO + 1:self.HI - 1, self.LO + 1:self.HI - 1] = True
        self.assertTrue(m[interior].all(), "the field's interior must be scored")
        # The seam takes a pixel off each edge, leaving this much of the field
        # scored; our field is offset by SHIFT, and one of those pixels was
        # already gone with the seam.
        side = self.HI - self.LO - 2
        overlap = side - (self.SHIFT - 1)
        self.assertAlmostEqual(_agreement(self.ours, self.spec, m, 2)["iou"][1],
                               round(overlap ** 2 / side ** 2, 3), places=3)

    def test_on_a_dark_field_the_figure_reads_as_recall(self):
        """What the cut still cannot answer, stated rather than left implied.

        A dark pixel where the spec draws the light substrate is either this
        field overrunning its outline or the printed type the spec does not
        carry, and no rule over colour alone separates them. The cut drops it,
        so a dark field's overspill costs nothing and its IoU degenerates to
        recall -- the figure catches a field placed short, not one placed wide.
        """
        m = scored_mask(self.frame, self.palette, self.spec)
        got, want = (self.ours == 1) & m, (self.spec == 1) & m
        self.assertEqual((got & ~want).sum(), 0, "no overspill survives the cut")
        self.assertAlmostEqual(_agreement(self.ours, self.spec, m, 2)["iou"][1],
                               round(float((got & want).sum() / want.sum()), 3),
                               places=3)

    def test_a_correctly_placed_dark_field_scores_one(self):
        frame = self.palette[self.spec]
        m = scored_mask(frame, self.palette, self.spec)
        self.assertEqual(_agreement(self.spec, self.spec, m, 2)["iou"][1], 1.0)

    def test_the_seam_between_two_regions_is_not_scored(self):
        """A pixel straddling a boundary is a mixture of both regions and is
        evidence about neither. Ativan's `#8E9DA0` is a 42% blend of its
        substrate and secondary_1, so its boundaries collected the field."""
        m = scored_mask(self.palette[self.spec], self.palette, self.spec)
        self.assertFalse(m[self.LO, self.LO:self.HI].any())
        self.assertFalse(m[self.LO - 1, self.LO:self.HI].any())
        self.assertTrue(m[self.LO + 1, self.LO + 1:self.HI - 1].all(),
                        "one pixel in, and only one")

    def test_a_field_placed_two_pixels_out_still_fails(self):
        """The check before throwing pixels away: a one-pixel exclusion must not
        hide a two-pixel error. On the group it does not -- Ativan 94.4% ->
        59.5%, Modafinil 100.0% -> 65.2% when the classification is shifted.

        A THIN field, because that is the geometry where it matters and where
        every one of those cartons sits. On a 58-pixel square a two-pixel offset
        genuinely is a 3% error and the figure is right to say so; on a bar
        twelve pixels deep it is a fifth of the field.
        """
        spec = np.zeros((self.N, self.N), dtype=int)
        spec[40:52, 20:80] = 1                       # a bar, as type-shaped as this gets
        ours = np.zeros_like(spec)
        ours[42:54, 20:80] = 1
        m = scored_mask(self.palette[ours], self.palette, spec)
        self.assertEqual(_agreement(spec, spec, m, 2)["iou"][1], 1.0)
        # Twelve rows, less one to the seam at each edge, leaves ten; our bar
        # is two rows down, so nine of them agree. Exact rather than a bound:
        # widen the exclusion to three pixels and this reads 1.0, which is the
        # failure the test is here to catch.
        self.assertAlmostEqual(_agreement(ours, spec, m, 2)["iou"][1],
                               round(9 / 10, 3), places=3)

    def test_type_the_spec_does_not_carry_is_still_cut(self):
        """The reason the cut exists at all: our render prints type, the spec
        does not, and scoring it would measure the type grid."""
        frame = self.palette[self.spec].copy()
        frame[5:9, 5:40] = 0.02                      # a printed row on the board
        m = scored_mask(frame, self.palette, self.spec)
        self.assertFalse(m[5:9, 5:40].any())

    def test_the_ink_s_rim_goes_with_it(self):
        """A pixel straddling a glyph edge is a mixture of ink and board and is
        evidence about neither -- and where some entry sits on the line between
        them, it is evidence FOR that entry. Xanax's `#968974` is a 44% blend of
        its substrate and brand, so every glyph edge on the carton read as that
        field: 0.80% of the face against a field that is 0.93% of it."""
        frame = self.palette[self.spec].copy()
        frame[5:9, 5:40] = 0.02
        frame[4, 5:40] = frame[9, 5:40] = 0.5        # the antialiased rim
        m = scored_mask(frame, self.palette, self.spec)
        self.assertFalse(m[4, 5:40].any())
        self.assertFalse(m[9, 5:40].any())
        self.assertTrue(m[2, 5:40].all(), "two pixels away is board, and stays")

    def test_the_rim_never_eats_a_field_the_spec_asks_for(self):
        """Our ink lands on dark fields too, and there the rim is the field."""
        frame = self.palette[self.spec].copy()
        mid = (self.LO + self.HI) // 2
        frame[mid - 2:mid + 2, self.LO + 5:self.HI - 5] = 0.02   # type on the field
        m = scored_mask(frame, self.palette, self.spec)
        interior = np.zeros_like(self.spec, dtype=bool)
        interior[self.LO + 1:self.HI - 1, self.LO + 1:self.HI - 1] = True
        self.assertTrue(m[interior].all())


class TestTheTwoDarknessTestsAgreeInTheDirectionThatMatters(unittest.TestCase):
    """The cut is on the pixel's MAX channel and the restore on the fill's LUMA.

    Different tests, deliberately -- but the asymmetry is only safe one way
    round. Luma is a weighted mean of the channels, so luma <= max always, and
    no fill the cut can reach is left unrestored. Reversing them would drop
    fields silently again, which is why this is asserted rather than assumed.
    """

    def test_every_fill_the_cut_reaches_is_restored(self):
        rng = np.random.default_rng(0)
        colours = np.concatenate([rng.random((4000, 3)), rng.random((4000, 3)) * 0.4])
        cut = colours.max(-1) < DARK_V
        self.assertTrue(cut.any(), "the sample must contain fills the cut reaches")
        self.assertTrue(((colours * LUMA).sum(1) < DARK_V)[cut].all())


class TestTheDesignQAReportCarriesEveryFigureItClaims(unittest.TestCase):
    """A figure that was never taken must not read as a figure that came out zero.

    `render_vs_reference` needs the rectified photograph on disk, under the
    folder's CURRENT name. `aa28834` renamed `64_Kamagra_Template_Reference` and
    `74_Viagra_Template_Reference`, which orphaned two previews keyed by folder
    name, and the report went on printing `0.0%` for both -- a render matching
    its own photograph on nothing at all, which is a startling number that
    nothing was startled by. The key is now always present and null when absent,
    and this reads the committed report to make sure the null is not what got
    committed.

    Reads the artefact rather than re-running the instrument: `design_qa` renders
    28 cartons, and the question here is whether the REPORT is complete.
    """

    @classmethod
    def setUpClass(cls):
        path = PROJECT_ROOT / "00_PROJECT_STATE" / "design_qa.json"
        if not path.exists():
            raise unittest.SkipTest("design_qa.json absent; run scripts/design_qa.py")
        cls.rows = json.loads(path.read_text(encoding="utf-8"))["rows"]

    def test_the_report_covers_the_whole_design_group(self):
        from src.design_group import FOLDER_BY_STEM
        self.assertEqual(sorted(r["sku"] for r in self.rows),
                         sorted(FOLDER_BY_STEM),
                         "the report and the design group disagree about who is in it")

    def test_every_carton_was_measured_against_its_own_photograph(self):
        missing = [r["sku"] for r in self.rows
                   if (r.get("render_vs_reference") or {}).get("agreement") is None]
        self.assertEqual(
            missing, [],
            f"no render~ref for {missing}: the rectified face is not in "
            f"02_processing/reference_measurement/ under the folder's current "
            f"name. Run `python scripts/measure_reference_face.py --all "
            f"--preview`, then `python scripts/design_qa.py`.")

    def test_a_missing_figure_is_null_and_never_zero(self):
        """The shape of the record, not its contents.

        Every optional figure has to be able to say 'not measured' in a way that
        cannot be read as a measurement. `field_iou_worst` is the one that is
        legitimately absent -- three cartons carry no field at all -- so it is
        the one worth pinning: null, not 0.0.
        """
        no_field = [r for r in self.rows if r["field_iou_worst"] is None]
        self.assertTrue(no_field, "expected some carton to carry no field")
        for r in no_field:
            self.assertIsNone(r["field_iou_worst"])
            self.assertNotEqual(r["field_iou_worst"], 0.0)

class TestTheReferenceFaceIsComputedAndNeverCached(unittest.TestCase):
    """The rectified photograph is a warp of one JPEG, so nothing may cache it.

    `design_qa` used to read it from
    `02_processing/reference_measurement/{folder}.flat.png`, a derived artefact
    keyed by folder name, and it went stale both ways such a thing can. A rename
    orphaned two of them and the report printed 0.0% agreement for two cartons
    rather than saying the file was gone. And `304_Sonata`'s corners were set six
    hours after that directory was last written, so its face was quietly out of
    date for five days with no name lost at all -- the failure that has no
    symptom until someone regenerates and watches a number move.

    `render_fresh` already applies this reasoning to our own side: it deletes and
    re-renders every run because a stale PNG makes the comparison worthless. The
    reference is the same comparison.
    """

    FOLDER = "133_Ambien"      # small face, so `segment` is quick

    def test_one_implementation_of_the_rectified_face(self):
        """`segment` and `rectified_face` must not drift apart.

        Two implementations of "the same" rectification is the shape of defect
        this project has been bitten by three times now, which is why `segment`
        calls this rather than repeating it.
        """
        from scripts.measure_reference_face import rectified_face, segment
        from src.design_group import TEMPLATES_DIR
        folder = TEMPLATES_DIR / self.FOLDER
        if not (folder / "metadata.json").exists():
            self.skipTest(f"{self.FOLDER} not on disk")
        if not any(p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                   for p in folder.iterdir()):
            self.skipTest("NOT VERIFIED: optional reference photography is not installed")
        direct = rectified_face(folder)[0]
        through_segment = segment(folder)[0]
        self.assertEqual(direct.size, through_segment.size)
        self.assertTrue(np.array_equal(np.asarray(direct),
                                       np.asarray(through_segment)))

    def test_design_qa_does_not_read_the_preview_directory(self):
        """Stated against the source, because the alternative costs 28 renders.

        A weak test on purpose, and it earns its place: what it forbids is the
        exact line that was there, and no reading of a `.flat.png` can come back
        without tripping it.
        """
        from scripts import design_qa
        src = Path(design_qa.__file__).read_text(encoding="utf-8")
        body = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        self.assertNotIn(".flat.png", body,
                         "design_qa is reading a cached rectified face again")
        self.assertIn("rectified_face(folder)", body)

    def test_a_folder_without_corners_is_refused_by_name(self):
        """Loud, not absent. The whole defect was a missing input reading as 0.0%."""
        import tempfile
        from scripts.measure_reference_face import rectified_face
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "999_Nothing"
            folder.mkdir()
            (folder / "metadata.json").write_text(
                json.dumps({"reference_images": []}), encoding="utf-8")
            with self.assertRaises(SystemExit) as caught:
                rectified_face(folder)
            self.assertIn("999_Nothing", str(caught.exception))
            self.assertIn("front_face_px", str(caught.exception))

if __name__ == "__main__":
    unittest.main()
