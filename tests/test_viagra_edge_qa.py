"""Sensitivity tests for the independent final-outline and pixel ruler."""
import copy
import unittest

import numpy as np

from scripts.viagra_edge_qa import geometry_metrics, locate_edge, homography, project


def simple_spec():
    return {"fields": [
        {"role": "brand", "parts": [{"outline": [[0, 0], [.23, 0], [.20, 1], [0, 1]], "holes": []}]},
        {"role": "recovered_01", "parts": [{"outline": [[.23, 0], [.27, 0], [.24, 1], [.20, 1]], "holes": []}]},
    ]}


class TestGeometry(unittest.TestCase):
    def test_shared_slanted_edges_pass(self):
        m = geometry_metrics(simple_spec())
        self.assertTrue(m["pass"])
        self.assertLess(m["max_boundary_disagreement_uv"], 1e-12)

    def test_gap_and_overlap_both_fail(self):
        for delta in [.0037, -.0037]:
            s = simple_spec()
            for vertex in s["fields"][1]["parts"][0]["outline"]:
                vertex[0] += delta
            m = geometry_metrics(s)
            self.assertFalse(m["pass"])
            self.assertAlmostEqual(m["max_boundary_disagreement_uv"], abs(delta))

    def test_shared_bend_is_not_straight(self):
        s = simple_spec()
        s["fields"][0]["parts"][0]["outline"].insert(2, [.220, .5])
        s["fields"][1]["parts"][0]["outline"].append([.220, .5])
        m = geometry_metrics(s)
        self.assertLess(m["max_boundary_disagreement_uv"], 1e-12)
        self.assertFalse(m["pass"])
        self.assertGreater(m["edges"]["cyan_left"]["max_chord_residual_uv"], .004)

    def test_input_unchanged(self):
        s = simple_spec()
        before = copy.deepcopy(s)
        geometry_metrics(s)
        self.assertEqual(s, before)

    def test_short_seam_cannot_pass_by_intersecting_extents(self):
        s = simple_spec()
        s["fields"][1]["parts"][0]["outline"] = [[.23, 0], [.27, 0], [.243, .9], [.203, .9]]
        m = geometry_metrics(s)
        self.assertFalse(m["pass"])
        self.assertAlmostEqual(m["v_extent_disagreement_uv"], .1)

    def test_multivalued_outline_refuses_envelope_shortcut(self):
        s = simple_spec()
        s["fields"][0]["parts"][0]["outline"] = [[0, 0], [.23, 0], [.23, 1], [.15, 1], [.15, .4], [.1, .4], [.1, 1], [0, 1]]
        m = geometry_metrics(s)
        self.assertFalse(m["pass"])
        self.assertTrue(m["multiple_interval_slices"]["navy"])


class TestPixels(unittest.TestCase):
    def test_perspective_corner_mapping(self):
        corners = [[10, 20], [150, 5], [140, 180], [20, 170]]
        h = homography(corners)
        self.assertTrue(np.allclose(project(h, [[0, 0], [1, 0], [1, 1], [0, 1]]), corners))

    def test_straight_and_bent_synthetic_edges(self):
        offsets = np.arange(-12, 12.01, .25)
        for shift in [0, .6, 3.0]:
            # Antialiased analytic edge sampled at the same subpixel grid.
            t = np.clip((offsets-shift)+.5, 0, 1)
            rgb = (np.array([20, 35, 80])[None, :] * (1-t[:, None])
                   + np.array([145, 177, 208])[None, :] * t[:, None])
            got = locate_edge(offsets, rgb)
            self.assertEqual(got["status"], "measured")
            self.assertAlmostEqual(got["offset_px"], shift, places=8)

    def test_missing_contrast_is_unknown(self):
        offsets = np.arange(-12, 12.01, .25)
        self.assertEqual(locate_edge(offsets, np.ones((len(offsets), 3))*100)["status"], "unknown")

    def test_light_spike_is_ambiguous_not_substrate(self):
        offsets = np.arange(-12, 12.01, .25)
        rgb = np.where((offsets > 0)[:, None], [145, 177, 208], [20, 35, 80]).astype(float)
        rgb[(offsets > -4) & (offsets < -2)] = 245
        self.assertEqual(locate_edge(offsets, rgb)["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
