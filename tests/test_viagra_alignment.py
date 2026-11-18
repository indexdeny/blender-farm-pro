"""Ruler gates for the three user-marked Viagra problem zones."""
import json
import unittest
from pathlib import Path

from tests.test_blender_carton import BLENDER_EXE, PROJECT_ROOT, build_scene


SPEC_PATH = PROJECT_ROOT / "Reference Templates/74_Viagra/design_spec.json"


class TestBandRuler(unittest.TestCase):
    """A narrow colour band has two linear edges and stable width."""

    def test_an_exact_rectangle_passes_the_ruler(self):
        from scripts.shadow_alignment_qa import band_metrics

        outline = [[0.23, 0.0], [0.2691, 0.0], [0.2691, 1.0],
                   [0.23, 1.0]]
        got = band_metrics(outline)
        self.assertLessEqual(got["left_max_residual"], 1e-12)
        self.assertLessEqual(got["right_max_residual"], 1e-12)
        self.assertLessEqual(got["width_drift"], 1e-12)

    def test_current_viagra_band_obeys_the_approved_ruler(self):
        from scripts.shadow_alignment_qa import band_metrics

        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        field = next(row for row in spec["fields"]
                     if row["role"] == "recovered_01")
        got = band_metrics(field["parts"][0]["outline"])
        self.assertLessEqual(got["left_max_residual"], 0.0025)
        self.assertLessEqual(got["right_max_residual"], 0.0025)
        self.assertLessEqual(got["width_drift"], 0.0020)

    def test_front_and_top_light_blue_endpoints_share_the_fold(self):
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        front = next(row for row in spec["fields"]
                     if row["role"] == "recovered_01")["parts"][0]["outline"]
        top = next(row for row in spec["fields"]
                   if row["role"] == "light_blue_top_wrap")["parts"][0]["outline"]
        front_fold = sorted(point[0] for point in front if point[1] == 0.0)
        top_fold = sorted({point[0] for point in top})
        self.assertEqual(len(front_fold), 2)
        self.assertEqual(len(top_fold), 2)
        for front_u, top_u in zip(front_fold, top_fold):
            self.assertLessEqual(abs(front_u - top_u), 0.0010)

    def test_navy_front_and_top_fields_have_no_substrate_fold_gap(self):
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        front = next(row for row in spec["fields"]
                     if row["role"] == "brand")["parts"][0]["outline"]
        top = next(row for row in spec["fields"]
                   if row["role"] == "brand_top_wrap")["parts"][0]["outline"]
        front_fold = sorted(point[0] for point in front if point[1] == 0.0)
        top_fold = sorted({point[0] for point in top})
        self.assertEqual(len(front_fold), 2)
        self.assertEqual(len(top_fold), 2)
        for front_u, top_u in zip(front_fold, top_fold):
            self.assertLessEqual(abs(front_u - top_u), 0.0010)


class TestMeasuredSeam(unittest.TestCase):
    def test_left_seam_endpoints_have_one_object_space_height(self):
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        seam = spec["carton_profile"]["visible_seams"][0]
        self.assertEqual(seam["surface"], "left")
        self.assertAlmostEqual(
            seam["polyline"][0][1], seam["polyline"][1][1], delta=1e-6)

    def test_pfizer_mark_uses_the_exact_host_hole_boundary(self):
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        mark = spec["marks"][0]
        role, hole_key = mark["key"].split("/")
        part_index = int(role.rsplit("#", 1)[1])
        hole_index = int(hole_key.rsplit("#", 1)[1])
        host = next(field for field in spec["fields"]
                    if field["role"] == mark["role"])
        self.assertEqual(mark["source"], "hole")
        self.assertEqual(
            mark["outline"], host["parts"][part_index]["holes"][hole_index])


@unittest.skipUnless(Path(BLENDER_EXE).exists(),
                     f"Blender not installed at {BLENDER_EXE}")
class TestMeasuredMarkAttachment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.render_manifest import build_manifest

        passport = json.loads((
            PROJECT_ROOT / "04_passports/passports_json/74-min.json"
        ).read_text(encoding="utf-8"))
        cls.scene = build_scene(build_manifest(passport))
        cls.spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    def test_scene_dump_exposes_the_real_mark_attachment(self):
        source = self.spec["marks"][0]
        expected = [source, *source.get("parts", [])]
        marks = sorted(self.scene["design_marks"], key=lambda row: row["mark_part_index"])
        self.assertEqual(len(marks), len(expected))
        self.assertEqual([row["mark_part_index"] for row in marks], list(range(-1, len(expected) - 1)))
        for mark, part in zip(marks, expected):
            with self.subTest(part=mark["mark_part_index"]):
                self.assertEqual(mark["surface"], "front")
                self.assertEqual(mark["splines"], 1 + len(part["holes"]))
                self.assertEqual(mark["fill"], part["fill"])
                self.assertGreater(mark["fill_area_m2"], 0.0)
                self.assertLessEqual(
                    abs(mark["normal_offset_m"]), mark["ink_budget_m"])

    def test_core_passport_text_is_unchanged_in_scene_geometry(self):
        rows = {row["name"]: row["body"] for row in self.scene["label"]}
        self.assertEqual(rows["label_brand"], "Viagra")
        self.assertEqual(rows["label_ingredient"], "Sildenafil")
        self.assertEqual(rows["label_dosage"], "100mg")
        self.assertEqual(rows["label_unit_count"], "30 Pills")
