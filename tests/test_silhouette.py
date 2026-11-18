"""The analytic silhouette model, checked against Blender's own arithmetic.

This model exists because the project's only measure of "how much of the frame
does the carton fill" was pixel measurement of a rendered image, and a white
carton on a 255 backdrop is precisely the case that defeats it: the brightly lit
top face blends into the background, so a landscape carton reads shorter than it
is. Every landscape row of the measured table in CURRENT_STATE.md is 5-9 points
low on height as a result.

So the model has to be trustworthy before anything is built on it, and the only
trustworthy check is Blender's own output. `05_assets/blender/render_driver.py`
projects the carton's printed faces itself and writes the result beside each
render as `{stem}.view.json`; one of those is committed as a fixture. If the
model reproduces those pixels, it is doing the same arithmetic Blender is.
"""
import json
import math
import re
import tempfile
import unittest
from pathlib import Path

from src import silhouette
from src.utils import PROJECT_ROOT

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "ocr" / "1-min.view.json"
DRIVER = PROJECT_ROOT / "05_assets" / "blender" / "render_driver.py"

# 1-min: T1, the catalogue's modal carton. Dimensions read from its manifest
# rather than hardcoded, so the fixture and the test cannot drift apart.
FIXTURE_MANIFEST = PROJECT_ROOT / "tests" / "fixtures" / "ocr" / "1-min.manifest.json"


class TestModelMatchesBlender(unittest.TestCase):
    """The model must agree with the renderer, not merely look plausible."""

    @classmethod
    def setUpClass(cls):
        cls.view = json.loads(FIXTURE.read_text(encoding="utf-8"))
        manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
        c = manifest["carton"]
        cls.dims = (c["width_mm"], c["height_mm"], c["depth_mm"])
        cls.template = manifest["template_id"]
        cls.res = cls.view["resolution"]

    def test_front_face_corners_match_the_renderers_own_projection(self):
        got = silhouette.front_face_px(self.dims, self.template, self.res)
        want = self.view["front_face_px"]
        self.assertEqual(len(got), 4)
        for label, g, w in zip(("TL", "TR", "BR", "BL"), got, want):
            delta = math.hypot(g[0] - w[0], g[1] - w[1])
            self.assertLess(
                delta, 0.1,
                f"{label}: model says {g[0]:.1f},{g[1]:.1f} but the driver "
                f"wrote {w[0]:.1f},{w[1]:.1f} ({delta:.2f} px apart). The "
                f"model is not doing the same arithmetic as the renderer.")

    def test_side_panel_corners_match_too(self):
        got = silhouette.side_panel_px(self.dims, self.template, self.res)
        want = self.view["side_panel_px"]
        for label, g, w in zip(("TL", "TR", "BR", "BL"), got, want):
            delta = math.hypot(g[0] - w[0], g[1] - w[1])
            self.assertLess(delta, 0.1, f"side {label}: {delta:.2f} px apart")

    def test_the_silhouette_encloses_both_printed_faces(self):
        # Weak on its own, but it catches a silhouette computed from the wrong
        # corner set -- the printed faces are part of the carton, so whatever
        # bounds the carton must bound them.
        x0, y0, x1, y1 = silhouette.silhouette_px(self.dims, self.template, self.res)
        for quad in (self.view["front_face_px"], self.view["side_panel_px"]):
            for x, y in quad:
                self.assertGreaterEqual(x, x0 - 0.1)
                self.assertLessEqual(x, x1 + 0.1)
                self.assertGreaterEqual(y, y0 - 0.1)
                self.assertLessEqual(y, y1 + 0.1)


class TestCameraConstantsAgreeWithTheDriver(unittest.TestCase):
    """`render_driver.py` cannot be imported outside Blender -- it does
    `import bpy` at module scope -- so its camera constants are duplicated here.
    Duplication without a check is how two sources of truth start disagreeing,
    so this reads the driver as text and fails the moment they part company.
    """

    @classmethod
    def setUpClass(cls):
        cls.source = DRIVER.read_text(encoding="utf-8")

    def _literal(self, name):
        m = re.search(rf"^{name}\s*=\s*([0-9.]+)", self.source, re.M)
        self.assertIsNotNone(m, f"{name} not found as a module-level constant "
                                f"in render_driver.py; the model can no longer "
                                f"verify it and must be updated deliberately")
        return float(m.group(1))

    def test_lens_and_sensor_match(self):
        self.assertEqual(silhouette.LENS_MM, self._literal("LENS_MM"))
        self.assertEqual(silhouette.SENSOR_MM, self._literal("SENSOR_MM"))

    def test_sphere_fill_matches(self):
        self.assertEqual(silhouette.SPHERE_FILL, self._literal("SPHERE_FILL"))

    def test_both_camera_families_match(self):
        # The driver assigns PITCH_DEG/ROTATION_DEG in two branches, one per
        # family. Both pairs must be found and both must match.
        pairs = re.findall(
            r"PITCH_DEG,\s*ROTATION_DEG\s*=\s*([0-9.]+),\s*([0-9.]+)", self.source)
        self.assertEqual(len(pairs), 2,
                         "expected exactly two camera branches in the driver")
        found = {(float(p), float(r)) for p, r in pairs}
        self.assertIn(silhouette.CAMERA_VERTICAL, found)
        self.assertIn(silhouette.CAMERA_DEFAULT, found)

    def test_the_camera_family_is_the_drivers_not_the_manifests(self):
        # A trap worth pinning: render_manifest.py also defines VERTICAL_FAMILY,
        # and it is a DIFFERENT set -- it includes T_BOTTLE_BOX because that
        # carton stands upright, while the driver's set governs which CAMERA is
        # used and excludes it. Taking the manifest's set here would silently
        # shoot T_BOTTLE_BOX with the wrong pitch and rotation.
        from src.render_manifest import VERTICAL_FAMILY as orientation_family
        self.assertNotEqual(silhouette.CAMERA_VERTICAL_TEMPLATES, orientation_family)
        self.assertIn("T_BOTTLE_BOX", orientation_family)
        self.assertNotIn("T_BOTTLE_BOX", silhouette.CAMERA_VERTICAL_TEMPLATES)

        m = re.search(r"^VERTICAL_FAMILY\s*=\s*\{([^}]*)\}", self.source, re.M)
        self.assertIsNotNone(m, "driver's VERTICAL_FAMILY not found")
        in_driver = {t.strip().strip('"\'') for t in m.group(1).split(",") if t.strip()}
        self.assertEqual(silhouette.CAMERA_VERTICAL_TEMPLATES, in_driver)


class TestFrameFill(unittest.TestCase):
    def test_fill_is_a_percentage_of_the_frame(self):
        w, h = silhouette.frame_fill((115.0, 55.0, 48.0), "T1")
        for v in (w, h):
            self.assertGreater(v, 0.0)
            self.assertLessEqual(v, 100.0)

    def test_aspect_is_width_over_height(self):
        dims, tpl = (115.0, 55.0, 48.0), "T1"
        w, h = silhouette.frame_fill(dims, tpl)
        self.assertAlmostEqual(silhouette.silhouette_aspect(dims, tpl), w / h, places=6)

    def test_a_wider_carton_has_a_wider_silhouette(self):
        narrow = silhouette.silhouette_aspect((80.0, 170.0, 35.0), "T_VERT_VIAL")
        wide = silhouette.silhouette_aspect((150.0, 170.0, 35.0), "T_VERT_VIAL")
        self.assertGreater(wide, narrow)

    def test_scale_alone_does_not_change_the_silhouette(self):
        # Framing is solved from the bounding sphere, so doubling every edge
        # doubles the distance too and the picture is identical. This is why
        # only proportions can be art-directed, not size.
        a = silhouette.frame_fill((115.0, 55.0, 48.0), "T1")
        b = silhouette.frame_fill((230.0, 110.0, 96.0), "T1")
        self.assertAlmostEqual(a[0], b[0], places=6)
        self.assertAlmostEqual(a[1], b[1], places=6)


REFERENCES = PROJECT_ROOT / "01_input_raster" / "reference"
RENDERS = PROJECT_ROOT / "02_processing" / "blender_test_renders"

# The seven renders predating the emissive backdrop. Their whole frame border
# sits below 250, so they are not measurements of current code and must not be
# calibrated against a model that describes it. Identified by the border test
# in the same 2026-08-09 pass, not by filename.
STALE_RENDERS = {"4-min", "5-min", "6-min", "8-min", "9-min", "11-min", "12-min"}


def _current_era_renders():
    """Renders whose backdrop matches current code, with their manifests.

    Design-group cartons are left out, and counted where they are left out. Their
    proportions come from a measured photograph rather than from a template's
    silhouette target, which puts several of them on the far side of the very
    switch this class documents -- Lexotanil is a portrait carton in a landscape
    template. The bracket below would then be asserted about a shape it was never
    calibrated on, and it fails by 6.9% on exactly that.

    The models themselves are not in question for those cartons: the driver's
    projection is still checked against them by
    TestSilhouetteModelAcrossFamilies, which reads the built scene rather than
    measuring pixels.
    """
    import numpy as np
    from PIL import Image
    from src.design_group import is_design_sku

    out, skipped_design = [], []
    for job in sorted(RENDERS.glob("*.job.json")):
        stem = job.name[:-len(".job.json")]
        png = job.with_name(stem + ".png")
        if stem in STALE_RENDERS or not png.exists():
            continue
        if is_design_sku(stem):
            skipped_design.append(stem)
            continue
        grey = np.asarray(Image.open(png).convert("RGB")).astype(float).mean(axis=2)
        border = np.concatenate([grey[0], grey[-1], grey[:, 0], grey[:, -1]])
        if (border < 250.0).mean() >= 0.01:
            continue
        out.append((stem, json.loads(job.read_text(encoding="utf-8")), png, grey))
    _current_era_renders.skipped_design = skipped_design
    return out


class TestMeasuredSilhouette(unittest.TestCase):
    """The pixel instrument, and the size of its own error.

    The model above is exact; this is not, and the project needs it anyway
    because the nine curated references carry no dimensions to project. What
    matters is that its error is known and does not quietly grow.
    """

    def setUp(self):
        try:
            import numpy  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError as e:  # pragma: no cover - environment, not logic
            self.skipTest(f"Pillow/numpy unavailable: {e}")

    def test_own_render_can_use_an_independent_object_mask(self):
        import numpy as np
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rgb = np.full((40, 60, 3), 255, np.uint8)
            rgb[8:28, 10:40] = 180
            rgb[28:34, 10:40] = 238  # contact shadow, not carton
            mask = np.zeros((40, 60), np.uint8)
            mask[8:28, 10:40] = 255
            image_path = root / "render.png"
            mask_path = root / "render.object.png"
            Image.fromarray(rgb).save(image_path)
            Image.fromarray(mask).save(mask_path)

            self.assertEqual(
                silhouette.measured_silhouette_px(
                    image_path, threshold=250, erode_r=0,
                    object_mask_path=mask_path),
                (10.0, 8.0, 39.0, 27.0))
            self.assertEqual(
                silhouette.measured_silhouette_px(
                    image_path, threshold=250, erode_r=0),
                (10.0, 8.0, 39.0, 33.0))

    def test_object_mask_dimensions_must_match_its_render(self):
        import numpy as np
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "render.png"
            mask_path = root / "render.object.png"
            Image.fromarray(np.full((20, 30, 3), 255, np.uint8)).save(image_path)
            Image.fromarray(np.full((10, 30), 255, np.uint8)).save(mask_path)
            with self.assertRaisesRegex(ValueError, "dimensions"):
                silhouette.measured_silhouette_px(
                    image_path, object_mask_path=mask_path)

    def test_erosion_is_what_makes_the_measurement_possible_at_all(self):
        # Without it the backdrop's own Cycles noise -- individual pixels down to
        # 244.7 -- puts subject pixels on all four frame edges, and a bounding box
        # of extremes becomes the whole frame. This is not a refinement worth 1%;
        # drop it and every measurement reads exactly 1.0.
        renders = _current_era_renders() if RENDERS.exists() else []
        if not renders:
            self.skipTest(f"{RENDERS.name}/ holds no current-era render to measure")
        stem, _, png, grey = renders[0]
        res_y, res_x = grey.shape
        naive = silhouette.measured_silhouette_px(png, erode_r=0)
        self.assertAlmostEqual((naive[2] - naive[0]) / (naive[3] - naive[1]), 1.0,
                               places=3,
                               msg=f"{stem}: without erosion the bbox should span the "
                                   f"frame; if it no longer does, the backdrop changed "
                                   f"and the note in silhouette.py is out of date")
        eroded = silhouette.measured_silhouette_px(png)
        self.assertLess(eroded[2] - eroded[0], 0.95 * res_x)
        self.assertLess(eroded[3] - eroded[1], 0.95 * res_y)

    def test_the_references_measure_stably_across_thresholds(self):
        # They are the only images this instrument is FOR, so their stability is
        # what licenses using it. Anything outside this band means the reference
        # set changed and the uncertainty figure needs re-deriving.
        if not REFERENCES.exists():
            self.skipTest("reference renders are not in this checkout")
        images = sorted(REFERENCES.glob("*.webp"))
        self.assertTrue(images, "reference directory exists but holds no .webp")
        for path in images:
            with self.subTest(reference=path.name):
                values = [silhouette.measured_silhouette_aspect(path, threshold=t)
                          for t in (248.0, 250.0, 252.0, 253.0)]
                spread = 100.0 * (max(values) - min(values)) / (sum(values) / len(values))
                # 7.6% is T_VERT_DROPPER, the worst of the nine as measured
                # 2026-08-09; 8.5 leaves it a little room without admitting a
                # different order of magnitude.
                self.assertLess(spread, 8.5,
                                f"{path.name} moves {spread:.2f}% across thresholds")

    def _render_errors(self, model_fn):
        renders = _current_era_renders() if RENDERS.exists() else []
        if not renders:
            self.skipTest(f"{RENDERS.name}/ holds no current-era render to measure")
        errors = []
        for stem, manifest, png, grey in renders:
            carton = manifest["carton"]
            dims = (carton["width_mm"], carton["height_mm"], carton["depth_mm"])
            res = (grey.shape[1], grey.shape[0])
            x0, y0, x1, y1 = model_fn(dims, manifest["template_id"], res)
            model = (x1 - x0) / (y1 - y0)
            errors.append(100.0 * (silhouette.measured_silhouette_aspect(png) / model - 1.0))
        return errors

    def test_the_measurement_is_bracketed_by_the_two_models(self):
        """Neither model predicts it; both bound it, and that is the whole story.

        Whether the carton's far top edge falls below the threshold depends on
        the carton's shape, so the same call returns the vertical faces on one
        geometry and the full silhouette on another. Measured on 1-min at five
        heights, holding width and depth: 56.4mm and 60mm render to 1.5347 and
        1.4736, tracking the VISIBLE model; 64mm, 67mm and 70.8mm render to
        1.2021, 1.1710 and 1.1351, tracking the FULL one. The switch happens
        somewhere between 60 and 64 and it is a jump, not a slope.

        So the honest claim is a bracket. Asserting either edge as "the" answer
        is what an earlier version of this test did, and it passed only because
        every render in the set happened to sit on the same side.
        """
        full = self._render_errors(silhouette.silhouette_px)
        visible = self._render_errors(silhouette.visible_faces_px)
        # Counted, not silently dropped: an exemption that can grow without
        # anyone noticing is how a bracket ends up asserted about nothing.
        from src.design_group import TEMPLATE_SAMPLE
        self.assertLessEqual(
            len(getattr(_current_era_renders, "skipped_design", [])),
            len(TEMPLATE_SAMPLE),
            "more renders were exempted as design-group than the group holds")
        for f, v in zip(full, visible):
            # full model is the taller box, so its aspect is the smaller number:
            # a measurement between the two reads as >= 0 against full and <= 0
            # against visible, with a tolerance for the instrument's own noise.
            self.assertGreater(f, -silhouette.MEASURE_UNCERTAINTY_PCT)
            self.assertLess(v, silhouette.MEASURE_UNCERTAINTY_PCT)

    def test_the_two_models_are_far_enough_apart_to_matter(self):
        # If they ever converge, the bracket above becomes a point and the
        # ambiguity this module documents has gone away -- which would be good
        # news, and would mean the notes here need rewriting rather than trusting.
        gaps = []
        for dims, tid in (((115.0, 55.0, 48.0), "T1"),
                          ((140.0, 35.0, 25.0), "T3"),
                          ((80.0, 170.0, 35.0), "T_VERT_VIAL")):
            a = silhouette.silhouette_aspect(dims, tid)
            b = silhouette.visible_faces_aspect(dims, tid)
            gaps.append(100.0 * (b / a - 1.0))
        self.assertGreater(min(gaps), 3.0,
                           f"model gap has closed to {min(gaps):.1f}%: {gaps}")

    def test_the_stated_uncertainty_is_not_smaller_than_the_error(self):
        # The constant exists to stop geometry being tuned against noise. It is
        # only worth anything if it is at least as large as the noise.
        self.assertGreaterEqual(silhouette.MEASURE_UNCERTAINTY_PCT, 2.9)


if __name__ == "__main__":
    unittest.main()
