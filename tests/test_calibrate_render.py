"""The chart is only worth anything if it stays independent of the answers.

`calibrate_render.py` renders a chart of known patches on each design carton's
own geometry and reads the rig's paint-to-pixel transfer off it. That curve then
decides how the classifier reads every field, so the two ways it could quietly
stop being a measurement are worth pinning: the chart drifting toward the
palettes it will be used to judge, and a stale curve being applied to output a
different driver produced.
"""
import json
import unittest
from unittest import mock

import numpy as np

from scripts import calibrate_render as cr


class TestTheCurveIsRead(unittest.TestCase):
    XS = np.array([0.0, 0.25, 0.50, 1.0])
    YS = np.array([0.13, 0.25, 0.42, 0.80])

    def test_a_paint_lands_where_the_ramp_puts_it(self):
        got = cr.appearance(np.array([[0.0, 0.25, 0.50]]), self.XS, self.YS)
        np.testing.assert_allclose(got, [[0.13, 0.25, 0.42]])

    def test_between_two_steps_it_interpolates(self):
        got = cr.appearance(np.array([0.375]), self.XS, self.YS)
        self.assertAlmostEqual(float(got[0]), 0.335, places=6)

    def test_each_channel_goes_through_the_same_curve(self):
        """Measured, not assumed: `#400000` renders (0.251, 0.133, 0.133) --
        its red where the ramp puts 0.251, its empty channels where it puts 0.
        One curve is enough only because that is true."""
        got = cr.appearance(np.array([[0.25, 0.0, 0.0]]), self.XS, self.YS)
        np.testing.assert_allclose(got, [[0.25, 0.13, 0.13]])

    def test_the_ramp_reaches_white(self):
        """Xanax Pfizer's substrate is `#F9F6F4`, above every other step. With
        the ramp stopping short, `np.interp` clamps and predicts it a quarter of
        a level too dark -- silently, since a clamp is not an error."""
        self.assertIn(0xFF, cr.STEPS)
        self.assertIn(0x00, cr.STEPS)


class TestTheChartStaysIndependentOfWhatItJudges(unittest.TestCase):
    def test_no_patch_is_a_colour_from_a_palette_it_will_be_used_on(self):
        """The NEUTRAL ramp is exempt, and only the neutral ramp.

        `230_Slimex`'s board is pure white and that is a measurement, not a
        blown highlight: 48.4% of its rectified face is exactly (255,255,255)
        on a flat studio shot of a white carton. So its substrate is
        `#FFFFFF`, which is also the ramp's top anchor -- an anchor
        `test_the_ramp_reaches_white` requires, since without it `np.interp`
        clamps and reads Xanax Pfizer's `#F9F6F4` a quarter of a level dark.

        The circularity this guards against is CHROMATIC: a chart carrying the
        hues it will be asked to tell apart is a chart made of the answers. A
        grey step carries no hue to lend, and it is the axis the transfer is
        read ALONG rather than a candidate answer. `221-min` shows what the
        bare hex test was actually measuring -- its board is `#FEFEFE` on a
        visually identical white carton and collides with nothing, so two
        identical cases were separated by one code level.

        The twelve chromatic patches stay strictly excluded.
        """
        from src.design_group import FOLDER_BY_STEM, load_design
        chart = {f"#{r:02X}{g:02X}{b:02X}"
                 for r, g, b in cr.PATCHES if not r == g == b}
        self.assertEqual(len(chart), 12, "the neutral ramp is 7 of 19 patches")
        for stem in FOLDER_BY_STEM:
            with self.subTest(sku=stem):
                spec = load_design(stem)
                palette = {spec["substrate"].upper()} | {
                    f["fill"].upper() for f in spec["fields"]}
                self.assertEqual(
                    chart & palette, set(),
                    "a chart made of the answers is the circularity this exists "
                    "to avoid")

    def test_the_chart_carries_no_type(self):
        """A label crossing a patch is ink, not paint, and the driver reverses
        it against whatever it lands on -- which on the chart is a patch."""
        # Viagra carries an allowed reference_aux_text row, so it exercises the
        # auxiliary geometry channel as well as the four core label rows.
        job, _fills = cr.chart_manifest("74-min")
        self.assertEqual(job["design"]["type_rows"], {})
        self.assertEqual(job["design"].get("reference_aux_text"), [])
        self.assertEqual(set(job["label_content"].values()), {""})

    def test_no_two_patches_share_an_edge(self):
        """Two abutting fills put each one's lit fringe inside the other."""
        boxes = [(min(u for u, _ in o), max(u for u, _ in o),
                  min(v for _, v in o), max(v for _, v in o))
                 for o in cr._grid(len(cr.PATCHES))]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                overlap = (min(a[1], b[1]) - max(a[0], b[0]) > -1e-9
                           and min(a[3], b[3]) - max(a[2], b[2]) > -1e-9)
                self.assertFalse(overlap, f"{a} touches {b}")


class TestAStaleCalibrationIsRefused(unittest.TestCase):
    """A classifier quietly running on the wrong transfer is the failure this
    was built to remove, and it would surface as a plausible number rather than
    as an error."""

    def test_a_missing_calibration_is_fatal_rather_than_a_fallback(self):
        with mock.patch.object(cr, "OUT", cr.PROJECT_ROOT / "no-such-file.json"):
            with self.assertRaises(SystemExit):
                cr.load_curve("64-min")

    def test_a_calibration_from_another_driver_is_fatal(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cal.json"
            p.write_text(json.dumps({
                "driver": "0" * 16,
                "rows": {"64-min": {"ramp": [[0.0, 0.1], [1.0, 0.8]]}}}),
                encoding="utf-8")
            with mock.patch.object(cr, "OUT", p):
                with self.assertRaises(SystemExit):
                    cr.load_curve("64-min")

    def test_the_matching_driver_is_accepted(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cal.json"
            p.write_text(json.dumps({
                "driver": cr.driver_fingerprint(),
                "rows": {"64-min": {"ramp": [[0.0, 0.1], [1.0, 0.8]]}}}),
                encoding="utf-8")
            with mock.patch.object(cr, "OUT", p):
                xs, ys = cr.load_curve("64-min")
        np.testing.assert_allclose(xs, [0.0, 1.0])
        np.testing.assert_allclose(ys, [0.1, 0.8])


def _design_stems():
    from src.design_group import FOLDER_BY_STEM
    return sorted(FOLDER_BY_STEM, key=lambda s: int(s.split("-")[0]))


if __name__ == "__main__":
    unittest.main()


class TestTheChartSpeaksTheCurrentContract(unittest.TestCase):
    """The chart is a design like any other and the driver validates it as one.

    It is only ever built inside a Blender render, so a contract bump that the
    chart does not follow fails where nothing is watching: `chart_manifest` went
    on emitting fields with no `z` from contract 1.7 until 1.8, and the driver
    had been refusing the whole run with SystemExit the entire time. Validating
    the job against the schema costs a millisecond and would have caught it the
    day it happened.
    """

    def test_the_chart_job_validates_against_the_manifest_schema(self):
        from src.design_group import FOLDER_BY_STEM
        from src.render_manifest import validate_manifest
        for stem in sorted(FOLDER_BY_STEM, key=lambda s: int(s.split("-")[0]))[:3]:
            with self.subTest(sku=stem):
                job, _fills = cr.chart_manifest(stem)
                validate_manifest(job)
