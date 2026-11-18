"""Contract tests for the three additive physical layout profiles."""

import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from src.carton_spec import CODE_ROOT, PROFILE_POLICIES, load_spec, validate_spec
from src.carton_validate import inspect_scene, material_metrics, relief_contrast


NEW_REQUIRED = {
    "cialis_professional": {
        "front_wordmark", "front_professional", "front_tadalafil", "front_dose",
        "front_count", "front_emblem_gold", "front_emblem_green", "front_green_arc",
        "front_yellow_band", "back_batch", "back_expiry",
    },
    "cialis_super_active": {
        "front_wordmark", "front_super_active", "front_tadalafil", "front_dose",
        "front_count", "front_yellow_arcs", "back_batch", "back_expiry",
    },
    "kamagra": {
        "front_wordmark", "front_dose", "front_count", "front_green_stripes",
        "front_dose_patch", "front_mark_left", "front_mark_right",
        "front_mark_head_left", "front_mark_head_right", "back_batch", "back_expiry",
    },
}


def synthetic_spec(profile):
    """Synthetic contract fixture; it is not product artwork."""
    spec = copy.deepcopy(load_spec())
    spec["sku"] = "999-min"
    spec["layout_profile"] = profile
    spec["effects"] = {
        name: {
            "status": "absent", "source": "authored",
            "reason": "Synthetic fixture declares no physical effect.",
            "production_status": "unknown",
        }
        for name in ("foil", "braille", "emboss")
    }
    templates = {e["id"]: e for e in spec["elements"]}
    elements = []
    text_ids = {
        "front_professional", "front_super_active", "front_tadalafil",
        "front_dose", "front_count", "back_batch", "back_expiry",
    }
    for index, identifier in enumerate(sorted(NEW_REQUIRED[profile])):
        if identifier == "front_wordmark":
            element = copy.deepcopy(templates["front_wordmark"])
        elif identifier in text_ids:
            element = copy.deepcopy(templates["front_dose"])
            element["text"] = identifier.replace("front_", "").replace("back_", "")
        else:
            element = {
                "id": identifier, "panel": "front", "kind": "path",
                "bbox_mm": [2 + index, 2, 2, 2], "source": "authored",
                "color": "navy", "path_mm": "M0 0 H2 V2 H0 Z",
            }
        element["id"] = identifier
        elements.append(element)
    spec["elements"] = elements
    return spec


class TestProfileContract(unittest.TestCase):
    def test_registry_is_canonical_and_preserves_legacy_required_sets(self):
        self.assertEqual(set(PROFILE_POLICIES), {"viagra", "cialis", *NEW_REQUIRED})
        self.assertIn("front_foil", PROFILE_POLICIES["viagra"]["required_element_ids"])
        self.assertIn("front_braille", PROFILE_POLICIES["cialis"]["required_element_ids"])
        for profile, required in NEW_REQUIRED.items():
            self.assertEqual(PROFILE_POLICIES[profile]["required_element_ids"], required)

    def test_new_profiles_accept_explicit_authored_absence(self):
        for profile in NEW_REQUIRED:
            with self.subTest(profile=profile):
                validate_spec(synthetic_spec(profile), check_files=False)

    def test_each_mandatory_id_is_enforced_for_each_new_profile(self):
        for profile, required in NEW_REQUIRED.items():
            for identifier in required:
                spec = synthetic_spec(profile)
                spec["elements"] = [e for e in spec["elements"] if e["id"] != identifier]
                with self.subTest(profile=profile, identifier=identifier), self.assertRaises(ValueError):
                    validate_spec(spec, check_files=False)

    def test_unknown_missing_duplicate_and_wrong_kind_are_rejected(self):
        spec = synthetic_spec("kamagra")
        mutations = []
        unknown = copy.deepcopy(spec)
        unknown["layout_profile"] = "unknown"
        mutations.append(unknown)
        missing = copy.deepcopy(spec)
        del missing["effects"]
        mutations.append(missing)
        duplicate = copy.deepcopy(spec)
        duplicate["elements"].append(copy.deepcopy(duplicate["elements"][0]))
        mutations.append(duplicate)
        fake = copy.deepcopy(spec)
        next(e for e in fake["elements"] if e["id"] == "front_mark_left")["kind"] = "text"
        mutations.append(fake)
        for changed in mutations:
            with self.subTest(case=len(changed.get("elements", []))), self.assertRaises(ValueError):
                validate_spec(changed, check_files=False)

    def test_effect_declaration_matches_actual_elements(self):
        spec = synthetic_spec("cialis_professional")
        forbidden = copy.deepcopy(spec)
        forbidden["elements"].append(copy.deepcopy(load_spec()["elements"][-15]))
        forbidden["elements"][-1]["id"] = "invented_foil"
        forbidden["elements"][-1]["kind"] = "foil"
        present_without_element = copy.deepcopy(spec)
        present_without_element["effects"]["foil"].update(status="present", source="measured")
        for changed in (forbidden, present_without_element):
            with self.assertRaises(ValueError):
                validate_spec(changed, check_files=False)

    def test_visible_text_and_independent_assets_cannot_be_dummy(self):
        spec = synthetic_spec("cialis_super_active")
        empty = copy.deepcopy(spec)
        next(e for e in empty["elements"] if e["id"] == "front_dose")["text"] = "  "
        missing_asset = copy.deepcopy(spec)
        next(e for e in missing_asset["elements"] if e["id"] == "front_wordmark")["asset"] = "missing"
        for changed in (empty, missing_asset):
            with self.assertRaises(ValueError):
                validate_spec(changed, check_files=False)

    def test_required_composite_vector_requires_an_independent_asset(self):
        spec = synthetic_spec("kamagra")
        mark = next(e for e in spec["elements"] if e["id"] == "front_mark_left")
        mark["kind"] = "vector"
        mark.pop("asset", None)
        with self.assertRaises(ValueError):
            validate_spec(spec, check_files=False)

        ttf_spec = synthetic_spec("kamagra")
        ttf_mark = next(e for e in ttf_spec["elements"] if e["id"] == "front_mark_left")
        ttf_mark["kind"] = "vector"
        ttf_mark["asset"] = "regular"
        with self.assertRaises(ValueError):
            validate_spec(ttf_spec, check_files=False)

    def test_required_path_must_have_positive_two_dimensional_area(self):
        for path_mm in (
            "M0 0 L1 0 Z",
            "M0 0 L1 1 Z",
            "M0 0 H1 V1 H0 Z M0 0 V1 H1 V0 Z",
        ):
            with self.subTest(path_mm=path_mm):
                spec = synthetic_spec("kamagra")
                mark = next(e for e in spec["elements"] if e["id"] == "front_mark_left")
                mark["path_mm"] = path_mm
                with self.assertRaises(ValueError):
                    validate_spec(spec, check_files=False)

    def test_required_path_accepts_opposite_winding_disjoint_contours(self):
        spec = synthetic_spec("kamagra")
        mark = next(e for e in spec["elements"] if e["id"] == "front_mark_left")
        mark["path_mm"] = "M0 0 H1 V1 H0 Z M1 1 V2 H2 V1 Z"
        validate_spec(spec, check_files=False)

    def test_wrong_asset_hash_is_rejected(self):
        spec = synthetic_spec("cialis_professional")
        spec["assets"]["wordmark"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_spec(spec)

    def test_new_profile_control_regions_are_nonempty_matching_and_in_bounds(self):
        cases = []
        empty_targets = synthetic_spec("kamagra")
        empty_targets["validation"]["reference_colors"] = {}
        cases.append(empty_targets)
        mismatch = synthetic_spec("kamagra")
        mismatch["validation"]["control_regions_mm"] = {"paper": [1, 1, 2, 2]}
        cases.append(mismatch)
        empty_patch = synthetic_spec("kamagra")
        empty_patch["validation"]["control_regions_mm"]["paper"] = [1, 1, 0, 2]
        cases.append(empty_patch)
        outside = synthetic_spec("kamagra")
        outside["validation"]["control_regions_mm"]["paper"] = [109, 49, 2, 2]
        cases.append(outside)
        for index, changed in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate_spec(changed, check_files=False)

    def test_declared_absence_rejects_injected_scene_relief(self):
        spec = synthetic_spec("cialis_professional")
        evidence_path = CODE_ROOT / "tests/fixtures/physical/59-min-closure.scene.json"
        evidence = json.loads(evidence_path.read_text("utf-8"))
        result = inspect_scene(spec, evidence)
        self.assertTrue(any("Declared absent" in issue for issue in result["issues"]))


class TestAbsentEffectMetrics(unittest.TestCase):
    @staticmethod
    def _artwork(root, metallic):
        maps = {}
        roughness = np.tile(np.arange(16, dtype=np.uint8), (16, 1)) + 160
        normal = np.zeros((16, 16, 3), dtype=np.uint8)
        normal[:, :, 0] = roughness
        for name, data in {
            "roughness": roughness, "metallic": metallic,
            "height": roughness, "normal": normal,
        }.items():
            path = root / f"{name}.png"
            Image.fromarray(data).save(path)
            maps[name] = {"path": str(path)}
        return {"dpi": 25.4, "maps": maps, "atlas": {"regions": {"front": [0, 0, 16, 16]}}}

    def test_zero_foil_map_has_finite_explicit_absence_metrics(self):
        spec = synthetic_spec("kamagra")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artwork = self._artwork(root, np.zeros((16, 16), dtype=np.uint8))
            spec["validation"]["control_regions_mm"] = {"paper": [0, 0, 8, 8]}
            metrics = material_metrics(spec, artwork, root=root)
            self.assertTrue(metrics["pass_"])
            self.assertEqual(metrics["foil_pixels"], 0)
            self.assertTrue(metrics["absence_verified"])
            self.assertTrue(all(math.isfinite(v) for v in metrics.values() if isinstance(v, float)))

    def test_absent_foil_rejects_one_nonzero_metallic_pixel(self):
        spec = synthetic_spec("kamagra")
        for value in (1, 127, 255):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                metallic = np.zeros((16, 16), dtype=np.uint8)
                metallic[0, 0] = value
                spec["validation"]["control_regions_mm"] = {"paper": [0, 0, 8, 8]}
                metrics = material_metrics(spec, self._artwork(root, metallic), root=root)
                self.assertFalse(metrics["pass_"])
                self.assertFalse(metrics["absence_verified"])

    def test_present_foil_pixel_count_keeps_existing_threshold(self):
        spec = synthetic_spec("kamagra")
        spec["elements"].append({
            "id": "front_foil",
            "panel": "front",
            "kind": "foil",
            "bbox_mm": [0, 0, 1, 1],
            "source": "authored",
        })
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            metallic = np.zeros((16, 16), dtype=np.uint8)
            metallic[0, 0] = 1
            metallic[0, 1] = 255
            spec["validation"]["control_regions_mm"] = {"paper": [0, 0, 8, 8]}
            metrics = material_metrics(spec, self._artwork(root, metallic), root=root)
            self.assertEqual(metrics["foil_pixels"], 1)
            self.assertEqual(metrics["metallic_nonzero_pixels"], 2)

    def test_absent_braille_returns_explicit_not_applicable(self):
        spec = synthetic_spec("cialis_professional")
        result = relief_contrast(spec, {}, {})
        self.assertEqual(result["status"], "not_applicable")
        self.assertEqual(result["dot_count"], 0)
        self.assertEqual(result["production_status"], "unknown")


if __name__ == "__main__":
    unittest.main()
