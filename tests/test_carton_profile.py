"""Measured visible-carton profile and optional design-boundary contract."""
from __future__ import annotations

import unittest
from pathlib import Path

from src import design_group


PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SOURCE_SUFFIX = Path("Reference Templates/3d_ref_boxes/Viagra_3d_ref")
REFERENCE_ROOT = next((
    path for path in (
        PROJECT_ROOT / _SOURCE_SUFFIX,
        PROJECT_ROOT.parent.parent / _SOURCE_SUFFIX,
    )
    if path.is_dir()
), None)


def _profile() -> dict:
    return {
        "profile_version": "1.0",
        "edge_radius_frac": 0.0353,
        "board_thickness_frac": 0.0131,
        "visible_flaps": [{
            "surface": "left",
            "u0": 0.08, "u1": 0.92, "v0": 0.02, "v1": 0.16,
            "stand_off_frac": 0.012,
        }],
        "visible_seams": [{
            "surface": "left",
            "polyline": [[0.08, 0.16], [0.92, 0.16]],
            "width_frac": 0.006,
            "gap_frac": 0.004,
        }],
        "surface_finish": {
            "roughness": 0.58,
            "micro_bump": {
                "scale": 185.0,
                "strength": 0.22,
                "distance_frac": 0.0012,
                "seed": 7401,
            },
        },
        "measurement_ref": "carton_profile_measurement.json",
    }


def _aux_row() -> dict:
    return {
        "text": "film-coated tablets",
        "surface": "front",
        "bbox": [0.40, 0.22, 0.70, 0.29],
        "align": "LEFT",
        "font_role": "regular",
        "source_image": "bf1lzjn5.jpg",
        "source_sha256": "4" * 64,
        "confidence": 0.99,
        "conflict_check": "pass",
    }


class TestProfileBoundary(unittest.TestCase):
    def test_valid_profile_is_accepted(self):
        design_group.validate_carton_profile(_profile())

    def test_fraction_outside_unit_interval_is_rejected_with_path(self):
        profile = _profile()
        profile["visible_flaps"][0]["stand_off_frac"] = 1.01

        with self.assertRaisesRegex(
                design_group.MissingDesignSpec,
                r"carton_profile\.visible_flaps\[0\]\.stand_off_frac"):
            design_group.validate_carton_profile(profile)

    def test_micro_bump_seed_must_be_an_integer(self):
        profile = _profile()
        profile["surface_finish"]["micro_bump"]["seed"] = 7401.0

        with self.assertRaisesRegex(
                design_group.MissingDesignSpec,
                r"carton_profile\.surface_finish\.micro_bump\.seed"):
            design_group.validate_carton_profile(profile)

    def test_unsupported_surface_is_rejected(self):
        profile = _profile()
        profile["visible_seams"][0]["surface"] = "right"

        with self.assertRaisesRegex(
                design_group.MissingDesignSpec,
                r"carton_profile\.visible_seams\[0\]\.surface"):
            design_group.validate_carton_profile(profile)


class TestReferenceAuxTextBoundary(unittest.TestCase):
    def test_valid_auxiliary_row_is_accepted(self):
        design_group.validate_reference_aux_text([_aux_row()])

    def test_confidence_below_098_is_rejected(self):
        row = _aux_row()
        row["confidence"] = 0.97

        with self.assertRaisesRegex(
                design_group.MissingDesignSpec,
                r"reference_aux_text\[0\]\.confidence"):
            design_group.validate_reference_aux_text([row])

    def test_failed_conflict_check_is_rejected(self):
        row = _aux_row()
        row["conflict_check"] = "fail"

        with self.assertRaisesRegex(
                design_group.MissingDesignSpec,
                r"reference_aux_text\[0\]\.conflict_check"):
            design_group.validate_reference_aux_text([row])

    def test_sensitive_or_conflicting_reference_strings_are_rejected(self):
        forbidden = (
            "LOT ABC123",
            "EXP 10/2029",
            "50 mg",
            "4 film-coated tablets",
            "0123456789012",
        )
        for text in forbidden:
            row = _aux_row()
            row["text"] = text
            with self.subTest(text=text):
                with self.assertRaisesRegex(
                        design_group.MissingDesignSpec,
                        r"reference_aux_text\[0\]\.text"):
                    design_group.validate_reference_aux_text([row])


class TestProfileMeasurement(unittest.TestCase):
    def test_normalized_measurement_records_formula_and_value(self):
        from scripts.measure_carton_profile import normalized_measurement

        row = normalized_measurement(
            "edge_radius_frac", 30.0, 850.0, 0.92,
            "dtwcv6w1.jpg", "outer rounded corner",
        )

        self.assertEqual(row["formula"], "raw_px / normalizer_px")
        self.assertAlmostEqual(row["value"], 30.0 / 850.0)

    def test_invalid_measurement_is_rejected(self):
        from scripts.measure_carton_profile import normalized_measurement

        with self.assertRaises(ValueError):
            normalized_measurement("bad", 1.0, 0.0, 0.9, "x.jpg", "bad")

    def test_provenance_reads_exactly_the_seven_approved_carton_jpgs(self):
        from scripts.measure_carton_profile import APPROVED_SOURCES, source_records

        if REFERENCE_ROOT is None:
            self.skipTest("NOT VERIFIED: optional seven-photo carton dataset is not installed")
        records = source_records(REFERENCE_ROOT)

        self.assertEqual([row["filename"] for row in records], APPROVED_SOURCES)
        self.assertTrue(all(row["width_px"] == 1920 for row in records))
        self.assertTrue(all(row["height_px"] == 1080 for row in records))
        self.assertTrue(all(len(row["sha256"]) == 64 for row in records))


if __name__ == "__main__":
    unittest.main()
