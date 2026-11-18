"""Isolated white-carton blanks for measured 110 x 50 x 18 mm references."""
import copy
import json
import unittest
from pathlib import Path

from scripts.render_reference_blanks import (
    blank_job,
    matching_reference_stems,
    validate_blank_dump,
)
from src.render_manifest import load_manifest, manifest_path_for
from src.utils import PROJECT_ROOT


EXPECTED_STEMS = [
    "59-min", "60-min", "64-min", "74-min",
    "151-min", "304-min", "362-min", "404-min",
]
BLANK_STEMS = [stem for stem in EXPECTED_STEMS if stem != "74-min"]
BLANK_DIR = (
    PROJECT_ROOT / "02_processing" / "viagra_visible_carton" /
    "blanks_110x50x18"
)
MANIFESTS_DIR = PROJECT_ROOT / "04_passports" / "render_manifests"


def _stem_key(stem):
    return int(stem.split("-", 1)[0])


class TestReferenceBlankContract(unittest.TestCase):
    def test_matching_set_is_computed_inside_the_reference_sample(self):
        self.assertEqual(matching_reference_stems(), EXPECTED_STEMS)

    def test_blank_job_is_physical_white_shell_without_production_content(self):
        source = load_manifest(manifest_path_for("64-min", MANIFESTS_DIR))
        before = copy.deepcopy(source)

        job = blank_job(source, (110.0, 50.0, 18.0))

        self.assertEqual(source, before, "blank_job mutated the canonical manifest")
        self.assertEqual(
            [job["carton"][key] for key in
             ("width_mm", "height_mm", "depth_mm")],
            [110.0, 50.0, 18.0],
        )
        self.assertEqual(job["carton"]["features"], [])
        self.assertEqual(job["label_content"], {})
        self.assertEqual(job["design"]["substrate"], "#FFFFFF")
        self.assertEqual(job["design"]["fields"], [])
        self.assertEqual(job["design"]["marks"], [])
        self.assertEqual(job["design"]["reference_aux_text"], [])
        self.assertIn("carton_profile", job["design"])

    def test_validator_rejects_any_visible_design_or_text(self):
        clean = {
            "carton": {"base_color": [1.0, 1.0, 1.0, 1.0],
                       "material_finish": {"noise_scale": 185.0,
                                           "bump_strength": 0.22}},
            "carton_profile": {"profile_version": "1.0"},
            "visible_carton_geometry": [{"kind": "flap"}],
            "design_fields": [], "label": [], "side_panel": [],
            "reference_aux_text": [], "relief": [],
        }
        validate_blank_dump(clean)
        for key in ("design_fields", "label", "side_panel",
                    "reference_aux_text", "relief"):
            with self.subTest(key=key):
                dirty = copy.deepcopy(clean)
                dirty[key].append({"unexpected": True})
                with self.assertRaises(ValueError):
                    validate_blank_dump(dirty)


class TestGeneratedReferenceBlanks(unittest.TestCase):
    def test_exactly_seven_pngs_and_seven_scene_dumps_exist(self):
        pngs = sorted((path.stem.removesuffix("-blank")
                       for path in BLANK_DIR.glob("*-blank.png")), key=_stem_key)
        dumps = sorted((path.name.removesuffix("-blank.scene.json")
                        for path in BLANK_DIR.glob("*-blank.scene.json")), key=_stem_key)
        self.assertEqual(pngs, BLANK_STEMS)
        self.assertEqual(dumps, BLANK_STEMS)
        unexpected = sorted(
            path.name for path in BLANK_DIR.iterdir()
            if not (path.name.endswith("-blank.png") or
                    path.name.endswith("-blank.scene.json"))
        )
        self.assertEqual(unexpected, [])

    def test_every_dump_is_a_detailed_white_blank(self):
        for stem in BLANK_STEMS:
            with self.subTest(stem=stem):
                path = BLANK_DIR / f"{stem}-blank.scene.json"
                dump = json.loads(path.read_text(encoding="utf-8"))
                validate_blank_dump(dump)


if __name__ == "__main__":
    unittest.main()
