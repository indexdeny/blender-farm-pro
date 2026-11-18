"""Independent completeness gate for reference design specs."""
from __future__ import annotations

import inspect
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np

from scripts import design_completeness
from scripts.design_completeness import (
    check_design, design_exclusion_mask, main_for_sku, unexplained_regions,
)
from src.design_group import load_design


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _is_light_blue(fill: str) -> bool:
    rgb = tuple(int(fill[i:i + 2], 16) for i in (1, 3, 5))
    red, green, blue = rgb
    return blue > red and blue > green and red > 120 and green > 140


class TestUnexplainedRegions(unittest.TestCase):
    H = W = 100

    def _white(self, value=245):
        return np.full((self.H, self.W, 3), value, dtype=np.uint8)

    def test_missing_connected_cyan_region_fails(self):
        reference = self._white()
        reference[:, 35:44] = (105, 195, 225)
        spec = self._white()

        got = unexplained_regions(reference, spec)

        self.assertEqual(len(got), 1)
        self.assertGreater(got[0].bbox_uv[3] - got[0].bbox_uv[1], 0.99)
        self.assertGreater(got[0].chroma_delta, 0.10)

    def test_region_drawn_by_spec_is_explained(self):
        reference = self._white()
        reference[:, 35:44] = (105, 195, 225)
        spec = reference.copy()

        self.assertEqual(unexplained_regions(reference, spec), [])

    def test_neutral_shading_does_not_fail(self):
        ramp = np.linspace(225, 250, self.W, dtype=np.uint8)
        reference = np.repeat(ramp[None, :, None], self.H, axis=0)
        reference = np.repeat(reference, 3, axis=2)
        spec = self._white(240)

        self.assertEqual(unexplained_regions(reference, spec), [])

    def test_disconnected_equal_colour_regions_remain_independent(self):
        reference = self._white()
        reference[15:35, 15:35] = (105, 195, 225)
        reference[65:85, 65:85] = (105, 195, 225)
        spec = self._white()

        got = unexplained_regions(reference, spec)

        self.assertEqual(len(got), 2)

    def test_gate_does_not_import_producer_segmentation(self):
        source = inspect.getsource(design_completeness)
        for forbidden in (
                "from scripts.measure_reference_face import segment",
                "recover_substrate_regions",
                "enumerate_components"):
            self.assertNotIn(forbidden, source)

    def test_owner_excluded_object_bbox_is_not_a_residual(self):
        reference = self._white()
        reference[60:85, 60:85] = (40, 120, 180)
        spec_rgb = self._white()
        truth = {
            "components": [{
                "key": "brand#2", "class": "object",
                "bbox_uv": [0.60, 0.60, 0.85, 0.85],
            }],
        }
        excluded = design_exclusion_mask(truth, {}, self.W, self.H)

        self.assertEqual(unexplained_regions(reference, spec_rgb, excluded), [])

    def test_print_component_is_never_excluded(self):
        truth = {
            "components": [{
                "key": "recovered_01#0", "class": "print",
                "bbox_uv": [0.35, 0.0, 0.44, 1.0],
            }],
        }

        excluded = design_exclusion_mask(truth, {}, self.W, self.H)

        self.assertFalse(excluded[:, 35:44].any())

    def test_reference_type_row_is_excluded_from_field_completeness(self):
        design = {
            "type_rows": {
                "brand_name_display": {
                    "u0": 0.20, "u1": 0.80, "v0": 0.10, "v1": 0.25,
                },
            },
        }

        excluded = design_exclusion_mask({"components": []}, design, self.W, self.H)

        self.assertTrue(excluded[10:25, 20:80].all())

    def test_deleting_a_declared_colour_field_makes_the_gate_fail(self):
        reference = self._white()
        reference[:, 35:44] = (105, 195, 225)
        field = {
            "role": "cyan", "z": 0, "fill": "#69C3E1",
            "parts": [{
                "outline": [[0.35, 0.0], [0.43, 0.0],
                            [0.43, 1.0], [0.35, 1.0]],
                "holes": [], "mark_holes": [], "fill": "#69C3E1",
            }],
        }
        design = {
            "substrate": "#F5F5F5", "fields": [field],
            "marks": [], "type_rows": {},
        }
        truth = {"components": [{
            "key": "recovered_01#0", "class": "print",
            "bbox_uv": [0.35, 0.0, 0.44, 1.0],
        }]}

        self.assertEqual(check_design(reference, design, truth), [])
        mutated = {**design, "fields": []}
        self.assertEqual(len(check_design(reference, mutated, truth)), 1)

    def test_declared_geometry_is_complete_even_when_colour_qa_would_fail(self):
        reference = self._white()
        reference[:, 35:44] = (105, 195, 225)
        design = {
            "substrate": "#F5F5F5",
            "fields": [{
                "role": "wrong_colour", "z": 0, "fill": "#7A40D0",
                "parts": [{
                    "outline": [[0.35, 0.0], [0.43, 0.0],
                                [0.43, 1.0], [0.35, 1.0]],
                    "holes": [], "mark_holes": [], "fill": "#7A40D0",
                }],
            }],
            "marks": [], "type_rows": {},
        }
        truth = {"components": [{
            "key": "recovered_01#0", "class": "print",
            "bbox_uv": [0.35, 0.0, 0.44, 1.0],
        }]}

        self.assertEqual(check_design(reference, design, truth), [])

    def test_unknown_sku_is_a_usage_failure(self):
        output = io.StringIO()

        with redirect_stdout(output):
            result = main_for_sku("not-a-reference-sku")

        self.assertEqual(result, 2)
        self.assertIn("not in the reference design group", output.getvalue())

    def test_front_raster_ignores_fields_declared_on_other_surfaces(self):
        from scripts.fit_design_spec import rasterise

        design = {
            "substrate": "#F5F5F5",
            "fields": [{
                "role": "top_wrap", "surface": "top", "z": 0,
                "fill": "#69C3E1",
                "parts": [{
                    "outline": [[0.0, 0.0], [1.0, 0.0],
                                [1.0, 1.0], [0.0, 1.0]],
                    "holes": [], "mark_holes": [], "fill": "#69C3E1",
                }],
            }],
            "marks": [],
        }

        pixels = np.asarray(rasterise(design, 20, 20))

        self.assertTrue((pixels == (245, 245, 245)).all())

    def test_direct_cli_bootstraps_the_project_root(self):
        proc = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "design_completeness.py"),
             "--sku", "not-a-reference-sku"],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
        )

        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("not in the reference design group", proc.stdout)


class TestCompleteSpecWriteBarrier(unittest.TestCase):
    def _case(self):
        reference = np.full((100, 100, 3), 245, dtype=np.uint8)
        reference[:, 35:44] = (105, 195, 225)
        truth = {"components": [{
            "key": "recovered_01#0", "class": "print",
            "bbox_uv": [0.35, 0.0, 0.44, 1.0],
        }]}
        incomplete = {
            "substrate": "#F5F5F5", "fields": [],
            "marks": [], "type_rows": {},
        }
        complete = {
            **incomplete,
            "fields": [{
                "role": "cyan", "z": 0, "fill": "#69C3E1",
                "parts": [{
                    "outline": [[0.35, 0.0], [0.43, 0.0],
                                [0.43, 1.0], [0.35, 1.0]],
                    "holes": [], "mark_holes": [], "fill": "#69C3E1",
                }],
            }],
        }
        return reference, truth, incomplete, complete

    def test_incomplete_candidate_does_not_replace_existing_spec(self):
        from scripts.fit_design_spec import write_complete_spec

        reference, truth, incomplete, _complete = self._case()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design_spec.json"
            path.write_text("sentinel", encoding="utf-8")

            with self.assertRaises(SystemExit):
                write_complete_spec(path, incomplete, reference, truth)

            self.assertEqual(path.read_text(encoding="utf-8"), "sentinel")

    def test_complete_candidate_is_written(self):
        from scripts.fit_design_spec import write_complete_spec

        reference, truth, _incomplete, complete = self._case()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design_spec.json"

            write_complete_spec(path, complete, reference, truth)

            self.assertEqual(path.read_text(encoding="utf-8").strip()[0], "{")

    def test_refit_preserves_only_reviewed_non_front_extensions(self):
        from scripts.fit_design_spec import preserve_manual_design_extensions

        candidate = {"fields": [{"role": "new_front"}]}
        previous = {
            "fields": [
                {"role": "old_front", "surface": "front"},
                {"role": "top_wrap", "surface": "top"},
            ],
            "carton_profile": {"profile_version": "1.0"},
            "reference_aux_text": [],
            "verification": {"stale": True},
        }

        preserve_manual_design_extensions(candidate, previous)

        self.assertEqual([f["role"] for f in candidate["fields"]],
                         ["new_front", "top_wrap"])
        self.assertEqual(candidate["carton_profile"], {"profile_version": "1.0"})
        self.assertEqual(candidate["reference_aux_text"], [])
        self.assertNotEqual(candidate.get("verification"), {"stale": True})


class TestViagraCompleteDesign(unittest.TestCase):
    def test_74_spec_contains_the_recovered_light_blue_band(self):
        spec = load_design("74-min")
        tall_front_fields = [
            field for field in spec["fields"]
            if field.get("surface", "front") == "front"
            and any(
                max(point[1] for point in part["outline"])
                - min(point[1] for point in part["outline"]) > 0.85
                for part in field["parts"]
            )
        ]

        self.assertTrue(any(_is_light_blue(field["fill"])
                            for field in tall_front_fields))


if __name__ == "__main__":
    unittest.main()
