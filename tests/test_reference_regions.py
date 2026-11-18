"""Synthetic contract tests for substrate-region recovery."""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from scripts.label_print import enumerate_components
from scripts.measure_reference_face import SAME_SURFACE_MAX
from scripts.reference_regions import recover_substrate_regions


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestRecoverSubstrateRegions(unittest.TestCase):
    """Recovery sees print lost inside the base substrate cluster only."""

    H = W = 100

    def _canvas(self, colour):
        rgb = np.empty((self.H, self.W, 3), dtype=float)
        rgb[:] = colour
        return rgb, np.ones((self.H, self.W), dtype=bool)

    def test_recovers_cyan_stripe_from_white_substrate(self):
        """Removing chroma recovery would lose the printed cyan stripe."""
        rgb, substrate = self._canvas((0.96, 0.96, 0.95))
        stripe_x0, stripe_x1 = 38, 50
        rgb[:, stripe_x0:stripe_x1] = (0.27, 0.82, 0.91)

        got = recover_substrate_regions(
            rgb, substrate, np.array((0.96, 0.96, 0.95)), SAME_SURFACE_MAX)

        self.assertEqual([r.role for r in got], ["recovered_01"])
        self.assertTrue(got[0].mask[:, stripe_x0:stripe_x1].all())
        self.assertTrue(np.allclose(got[0].colour, (0.27, 0.82, 0.91)))

    def test_recovers_salmon_badge_from_coloured_substrate(self):
        """Always comparing only against white would miss a coloured board badge."""
        rgb, substrate = self._canvas((0.10, 0.43, 0.35))
        rgb[28:72, 32:68] = (0.93, 0.43, 0.34)

        got = recover_substrate_regions(
            rgb, substrate, np.array((0.10, 0.43, 0.35)), SAME_SURFACE_MAX)

        self.assertEqual([r.role for r in got], ["recovered_01"])
        self.assertTrue(got[0].mask[28:72, 32:68].all())

    def test_keeps_disconnected_equal_colour_regions_as_regions(self):
        """Collapsing disconnected print into one mask would invent bridging paint."""
        rgb, substrate = self._canvas((0.94, 0.94, 0.93))
        cyan = (0.22, 0.78, 0.90)
        rgb[20:40, 15:35] = cyan
        rgb[60:80, 65:85] = cyan

        got = recover_substrate_regions(
            rgb, substrate, np.array((0.94, 0.94, 0.93)), SAME_SURFACE_MAX)

        self.assertEqual([r.role for r in got], ["recovered_01", "recovered_02"])
        self.assertTrue(got[0].mask[20:40, 15:35].all())
        self.assertTrue(got[1].mask[60:80, 65:85].all())

    def test_ignores_low_chroma_white_lighting_gradient(self):
        """Treating luminance shading as print would create a false field."""
        ramp = np.linspace(0.80, 0.98, self.W)
        rgb = np.repeat(ramp[None, :, None], self.H, axis=0)
        rgb = np.repeat(rgb, 3, axis=2)
        substrate = np.ones((self.H, self.W), dtype=bool)

        got = recover_substrate_regions(
            rgb, substrate, np.array((0.89, 0.89, 0.89)), SAME_SURFACE_MAX)

        self.assertEqual(got, [])

    def test_recovers_print_touching_face_edges(self):
        rgb, substrate = self._canvas((0.96, 0.96, 0.95))
        rgb[:, 42:49] = (0.32, 0.79, 0.91)

        got = recover_substrate_regions(
            rgb, substrate, np.array((0.96, 0.96, 0.95)), SAME_SURFACE_MAX)

        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].mask[0, 45])
        self.assertTrue(got[0].mask[-1, 45])

    def test_viagra_light_blue_stripe_is_not_substrate(self):
        folder = PROJECT_ROOT / "Reference Templates" / "74_Viagra"
        self._require_photography(folder)

        _flat, records, _residue, _named, _meta, _source = enumerate_components(folder)

        recovered = [r for r in records if r["key"].startswith("recovered_")]
        self.assertTrue(recovered, "74_Viagra cyan stripe stayed inside substrate")
        stripe = max(recovered, key=lambda r: r["area_pct"])
        self.assertGreater(stripe["bbox_uv"][3] - stripe["bbox_uv"][1], 0.85)
        self.assertGreater(stripe["bbox_uv"][2] - stripe["bbox_uv"][0], 0.01)
        self.assertLess(stripe["bbox_uv"][2] - stripe["bbox_uv"][0], 0.20)

    def test_fitter_and_labeller_receive_the_same_recovered_mask(self):
        from scripts.fit_design_spec import design_component_sources
        from scripts.measure_reference_face import segment

        folder = PROJECT_ROOT / "Reference Templates" / "74_Viagra"
        self._require_photography(folder)
        flat, labels, named, _meta, _source = segment(folder)
        lab = labels.reshape(flat.height, flat.width)
        sources = design_component_sources(np.asarray(flat), lab, named)
        fitter_stripe = next(mask for role, mask, _group in sources
                             if role == "recovered_01")
        _flat, records, _residue, _named, _meta, _source = enumerate_components(folder)
        labelled_stripe = next(r["_mask"] for r in records
                               if r["key"] == "recovered_01#0")

        self.assertTrue(np.array_equal(fitter_stripe, labelled_stripe))

    def test_design_coverage_indexes_the_recovered_print_region(self):
        from scripts.design_coverage import truth_from_labels
        from scripts.fit_design_spec import design_component_sources
        from scripts.measure_reference_face import segment

        folder = PROJECT_ROOT / "Reference Templates" / "74_Viagra"
        self._require_photography(folder)
        flat, labels, named, _meta, _source = segment(folder)
        lab = labels.reshape(flat.height, flat.width)
        sources = design_component_sources(np.asarray(flat), lab, named)
        stripe = next(mask for role, mask, _group in sources
                      if role == "recovered_01")

        truth, _scored, missing = truth_from_labels(
            folder, np.asarray(flat), lab, named,
            ["brand", "recovered_01"])

        self.assertEqual(missing, [])
        self.assertGreater(float((truth[stripe] == 1).mean()), 0.98)

    def _require_photography(self, folder):
        if not any(p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                   for p in folder.iterdir()):
            self.skipTest("NOT VERIFIED: optional reference photography is not installed")


class TestRectilinearEdgeBandRegularizer(unittest.TestCase):
    def test_nearly_vertical_connected_edge_band_gets_parallel_edges(self):
        from scripts.fit_design_spec import regularize_rectilinear_edge_band

        mask = np.zeros((100, 100), dtype=bool)
        for y in range(100):
            left = 40 - round(3 * y / 99)
            mask[y, left:left + 10] = True

        self.assertEqual(
            regularize_rectilinear_edge_band(mask),
            [(40, 0), (49, 0), (46, 100), (37, 100)])

    def test_wide_or_strongly_diagonal_regions_are_not_rewritten(self):
        from scripts.fit_design_spec import regularize_rectilinear_edge_band

        wide = np.zeros((100, 100), dtype=bool)
        wide[:, 10:40] = True
        diagonal = np.zeros((100, 100), dtype=bool)
        for y in range(100):
            left = 40 - round(20 * y / 99)
            diagonal[y, left:left + 10] = True

        self.assertIsNone(regularize_rectilinear_edge_band(wide))
        self.assertIsNone(regularize_rectilinear_edge_band(diagonal))

    def test_wavy_boundary_is_not_mistaken_for_printed_rule(self):
        from scripts.fit_design_spec import regularize_rectilinear_edge_band

        mask = np.zeros((100, 100), dtype=bool)
        for y in range(100):
            left = 40 + round(4 * np.sin(y / 5.0))
            mask[y, left:left + 10] = True

        self.assertIsNone(regularize_rectilinear_edge_band(mask))


class TestCrossSurfaceFoldClosure(unittest.TestCase):
    def test_matching_front_and_top_ink_close_the_fold_gap(self):
        from scripts.fit_design_spec import close_matching_front_top_fold

        spec = {"fields": [
            {"surface": "front", "fill": "#012958", "parts": [{
                "fill": "#012958", "outline": [
                    [0.0, 0.01], [0.2, 0.01], [0.18, 1.0], [0.0, 1.0]],
                "holes": [],
            }]},
            {"surface": "top", "fill": "#012958", "parts": [{
                "fill": "#012958", "outline": [
                    [0.0, 0.0], [0.2, 0.0], [0.2, 1.0], [0.0, 1.0]],
                "holes": [],
            }]},
        ]}

        changed = close_matching_front_top_fold(spec, 1000, 800)

        self.assertEqual(changed, 1)
        front = spec["fields"][0]["parts"][0]["outline"]
        fold = sorted(point[0] for point in front if point[1] == 0.0)
        self.assertEqual(fold, [0.0, 0.2])

    def test_different_ink_does_not_authorize_cross_surface_paint(self):
        from scripts.fit_design_spec import close_matching_front_top_fold

        outline = [[0.0, 0.01], [0.2, 0.01], [0.18, 1.0], [0.0, 1.0]]
        spec = {"fields": [
            {"surface": "front", "fill": "#012958", "parts": [{
                "fill": "#012958", "outline": [point[:] for point in outline],
                "holes": [],
            }]},
            {"surface": "top", "fill": "#AAC1DB", "parts": [{
                "fill": "#AAC1DB", "outline": [
                    [0.0, 0.0], [0.2, 0.0], [0.2, 1.0], [0.0, 1.0]],
                "holes": [],
            }]},
        ]}

        self.assertEqual(close_matching_front_top_fold(spec, 1000, 800), 0)
        self.assertEqual(spec["fields"][0]["parts"][0]["outline"], outline)


if __name__ == "__main__":
    unittest.main()
