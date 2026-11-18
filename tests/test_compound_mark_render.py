"""Compound approved marks: real Blender geometry and consumer paint order."""
import ast
import copy
import unittest
from pathlib import Path

import numpy as np

from tests.test_blender_carton import (
    BLENDER_EXE, DRIVER_SCRIPT, PROJECT_ROOT, build_scene, srgb_hex_to_linear,
)


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def mark_fixture():
    return {
        "role": "brand", "key": "brand#0/hole#0", "source": "hole", "z": 0,
        "fill": "#D8D9D5", "outline": rect(.65, .65, .95, .95), "holes": [],
        "parts": [{"fill": "#142F61", "outline": rect(.70, .70, .90, .90),
                   "holes": [rect(.76, .76, .84, .84)]}],
    }


def driver_readout():
    """Execute the driver's pure functions; never import bpy outside its owner."""
    tree = ast.parse(Path(DRIVER_SCRIPT).read_text(encoding="utf-8"))
    names = {"_point_in_polygon", "_drawable_mark_parts", "_prepared_parts",
             "_surface_fill"}
    module = ast.Module(body=[node for node in tree.body
                              if isinstance(node, ast.FunctionDef)
                              and node.name in names], type_ignores=[])
    namespace = {"_PART_CACHE": {}}
    exec(compile(module, DRIVER_SCRIPT, "exec"), namespace)
    return namespace["_surface_fill"]


class TestCompoundMarkReadout(unittest.TestCase):
    def test_ink_lookup_reads_overlay_and_sees_base_through_its_hole(self):
        mark = mark_fixture()
        design = {"fields": [], "marks": [mark]}
        fill_at = driver_readout()
        self.assertEqual(fill_at(design, .72, .72), "#142F61")
        self.assertEqual(fill_at(design, .80, .80), "#D8D9D5")
        self.assertEqual(fill_at(design, .66, .66), "#D8D9D5")
        self.assertIsNone(fill_at(design, .50, .50))

    def test_index_map_includes_a_part_painted_inside_a_base_hole(self):
        from scripts.design_coverage import MARK, SUBSTRATE, spec_index

        mark = mark_fixture()
        mark["holes"] = [rect(.68, .68, .92, .92)]
        idx = spec_index({"fields": [], "marks": [mark]}, 100, 100)
        self.assertEqual(idx[72, 72], MARK)
        self.assertEqual(idx[80, 80], SUBSTRATE)
        self.assertEqual(idx[66, 66], MARK)

    def test_legacy_readout_is_identical_when_parts_are_absent_or_empty(self):
        legacy = mark_fixture()
        legacy.pop("parts")
        empty = dict(legacy, parts=[])
        fill_at = driver_readout()
        left, right = {"marks": [legacy]}, {"marks": [empty]}
        for u in (.50, .66, .72, .80, .96):
            self.assertEqual(fill_at(left, u, .80), fill_at(right, u, .80))


@unittest.skipUnless(Path(BLENDER_EXE).exists(), "Blender executable unavailable")
class TestCompoundMarkGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_blender_carton import JOB

        job = copy.deepcopy(JOB)
        job["design"] = {
            "substrate": "#FFFFFF", "fields": [], "marks": [mark_fixture()],
        }
        cls.scene = build_scene(job)
        many = copy.deepcopy(job)
        many["design"]["marks"][0]["parts"] *= 130
        cls.many = build_scene(many)

    def test_base_and_overlay_are_real_separate_coloured_curves(self):
        marks = {obj["name"]: obj for obj in self.scene["design_marks"]}
        self.assertEqual(set(marks), {"mark_brand_0", "mark_brand_0_part_0"})
        for name, colour, holes in (("mark_brand_0", "#D8D9D5", 0),
                                    ("mark_brand_0_part_0", "#142F61", 1)):
            obj = marks[name]
            self.assertEqual(obj["fill"], colour)
            np.testing.assert_allclose(obj["base_color"][:3],
                                       srgb_hex_to_linear(colour)[:3], atol=1e-6)
            self.assertEqual(obj["splines"], holes + 1)
            self.assertEqual(obj["holes"], holes)

    def test_overlay_hole_is_absent_from_the_actual_tessellation(self):
        overlay = next((row for row in self.scene["design_marks"]
                        if row["name"] == "mark_brand_0_part_0"), None)
        self.assertIsNotNone(overlay, "overlay was silently dropped")
        bounds = self.scene["carton"]["self_bounds"]
        area = ((bounds["max"][0] - bounds["min"][0]) *
                (bounds["max"][2] - bounds["min"][2]))
        self.assertAlmostEqual(overlay["fill_area_m2"], (.20**2 - .08**2) * area,
                               delta=area * 1e-6)

    def test_many_overlays_stay_in_the_ink_budget_and_preserve_paint_order(self):
        objects = self.many["design_marks"]
        self.assertEqual(len(objects), 131)
        offsets = []
        for obj in objects:
            offset = obj["normal_offset_m"]
            self.assertLessEqual(offset, obj["ink_budget_m"])
            offsets.append(offset)
        self.assertEqual(len(set(offsets)), len(offsets))
        by_name = {obj["name"]: obj for obj in objects}
        self.assertLess(by_name["mark_brand_0"]["normal_offset_m"],
                        by_name["mark_brand_0_part_0"]["normal_offset_m"])
        self.assertLess(by_name["mark_brand_0_part_0"]["normal_offset_m"],
                        by_name["mark_brand_0_part_129"]["normal_offset_m"])

    def test_dump_projects_actual_curve_rings_into_the_printed_face(self):
        overlay = next(row for row in self.scene["design_marks"]
                       if row["name"] == "mark_brand_0_part_0")
        self.assertIn("projected_splines_px", overlay)
        self.assertEqual(overlay["projected_splines_basis"],
                         "curve_control_points_before_extrusion_and_bevel")
        rings = overlay["projected_splines_px"]
        self.assertEqual([len(ring) for ring in rings], [4, 4])
        # Independent homography from the carton's measured four front corners.
        rows, values = [], []
        for (u, v), (x, y) in zip(rect(0, 0, 1, 1), self.scene["front_face_px"]):
            rows.extend(([u, v, 1, 0, 0, 0, -u*x, -v*x],
                         [0, 0, 0, u, v, 1, -u*y, -v*y]))
            values.extend((x, y))
        matrix = np.r_[np.linalg.solve(rows, values), 1].reshape(3, 3)
        source = mark_fixture()["parts"][0]
        for actual, ring in zip(rings, [source["outline"], *source["holes"]]):
            uv = np.c_[np.asarray(ring), np.ones(len(ring))]
            expected = uv @ matrix.T
            expected = expected[:, :2] / expected[:, 2:]
            # The overlay's measured sub-ink normal offset changes projection
            # slightly relative to the bare carton plane.
            np.testing.assert_allclose(actual, expected, atol=.2)

    def test_projected_evaluated_triangles_cover_ink_but_leave_the_hole_open(self):
        overlay = next(row for row in self.scene["design_marks"]
                       if row["name"] == "mark_brand_0_part_0")
        self.assertIn("diagnostic_projection", overlay)
        mesh = overlay["diagnostic_projection"]
        vertices = np.asarray(mesh["projected_vertices_px_depth"])
        triangles = np.asarray(mesh["triangles"])
        self.assertEqual(vertices.shape[1], 3)
        self.assertTrue(np.isfinite(vertices).all())
        self.assertTrue((vertices[:, 2] > 0).all())
        self.assertGreater(len(triangles), 0)
        self.assertEqual(triangles.shape[1], 3)
        self.assertGreaterEqual(triangles.min(), 0)
        self.assertLess(triangles.max(), len(vertices))

        def covered(point):
            for triangle in vertices[triangles, :2]:
                edge = np.roll(triangle, -1, axis=0) - triangle
                delta = point - triangle
                cross = edge[:, 0] * delta[:, 1] - edge[:, 1] * delta[:, 0]
                if (cross > 1e-7).all() or (cross < -1e-7).all():
                    return True
            return False

        outer, hole = map(np.asarray, overlay["projected_splines_px"])
        self.assertFalse(covered(hole.mean(axis=0)))
        self.assertTrue(covered(.6 * outer[0] + .4 * hole[0]))


if __name__ == "__main__":
    unittest.main()
