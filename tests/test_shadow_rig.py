"""Common contact-shadow contracts for the procedural carton rig."""
import json
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.test_blender_carton import (
    BLENDER_EXE, DRIVER_SCRIPT, PROJECT_ROOT, build_scene,
)


@unittest.skipUnless(Path(BLENDER_EXE).exists(),
                     f"Blender not installed at {BLENDER_EXE}")
class TestCommonShadowRig(unittest.TestCase):
    """A missing common rig must fail before a beauty render can look right."""

    @classmethod
    def setUpClass(cls):
        from src.render_manifest import build_manifest

        passport = json.loads((
            PROJECT_ROOT / "04_passports/passports_json/74-min.json"
        ).read_text(encoding="utf-8"))
        cls.scene = build_scene(build_manifest(passport))

    def test_scene_dump_reports_the_built_shadow_rig(self):
        rig = self.scene["shadow_rig"]
        self.assertTrue(rig["enabled"])
        self.assertEqual(rig["scope"], "common_carton_rig")
        self.assertIn(rig["method"], {"physical_receiver", "shadow_catcher"})
        self.assertGreater(rig["receiver_scale"], 1.0)
        self.assertGreaterEqual(rig["receiver_offset_frac"], 0.0)

    def test_shadow_settings_do_not_enter_the_manifest_contract(self):
        from src.render_manifest import build_manifest

        passport = json.loads((
            PROJECT_ROOT / "04_passports/passports_json/74-min.json"
        ).read_text(encoding="utf-8"))
        manifest = build_manifest(passport)
        self.assertNotIn("shadow", manifest)
        self.assertNotIn("shadow_rig", manifest)


class TestShadowMeasurement(unittest.TestCase):
    """The derived shadow never becomes part of the carton silhouette."""

    def _fixture(self):
        off = np.full((100, 120, 3), 255, np.uint8)
        on = off.copy()
        object_mask = np.zeros(off.shape[:2], bool)
        object_mask[20:76, 25:85] = True
        off[object_mask] = (150, 150, 150)
        on[object_mask] = (150, 150, 150)
        # Attached, soft six-pixel penumbra with literal luminance deficits.
        for y, deficit in enumerate((12, 10, 8, 6, 4, 2), start=76):
            on[y, 25:85] = 255 - deficit
        return on, off, object_mask

    def test_object_bbox_is_independent_of_the_attached_shadow(self):
        from scripts.shadow_alignment_qa import bbox_from_mask, shadow_mask

        on, off, object_mask = self._fixture()
        shadow = shadow_mask(on, off, object_mask, min_deficit=1.5)
        self.assertEqual(bbox_from_mask(object_mask), (25, 20, 85, 76))
        self.assertTrue(shadow[77:82, 25:85].all())
        self.assertFalse(shadow[76, 25:85].any())
        self.assertFalse(np.logical_and(shadow, object_mask).any())

    def test_metrics_measure_contact_area_and_deficit(self):
        from scripts.shadow_alignment_qa import shadow_metrics

        on, off, object_mask = self._fixture()
        got = shadow_metrics(on, off, object_mask, min_deficit=1.5)
        self.assertEqual(got["contact_distance_px"], 2)
        self.assertAlmostEqual(got["shadow_area_pct"], 300 / 3360 * 100)
        self.assertAlmostEqual(got["mean_luminance_deficit"], 6.0)
        self.assertAlmostEqual(got["minimum_shadow_luminance"], 245.0)
        self.assertAlmostEqual(got["penumbra_width_px"], 4.0)
        self.assertEqual(got["lower_edge_coverage"], 1.0)

    def test_turning_the_shadow_off_proves_instrument_sensitivity(self):
        from scripts.shadow_alignment_qa import shadow_metrics

        _on, off, object_mask = self._fixture()
        got = shadow_metrics(off, off, object_mask, min_deficit=1.5)
        self.assertEqual(got["shadow_area_px"], 0)
        self.assertIsNone(got["contact_distance_px"])


class TestResumableReferenceBatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _seed_completed(self, stem, driver_hash, manifest_hash, content):
        suffixes = (".png", ".scene.json", ".object.png", ".shadow.png")
        hashes = {}
        for suffix in suffixes:
            path = self.out / f"{stem}{suffix}"
            path.write_bytes(content + suffix.encode("ascii"))
            hashes[suffix] = self._digest(path)
        (self.out / f"{stem}.measurements.json").write_text(json.dumps({
            "status": "complete",
            "stem": stem,
            "driver_sha256": driver_hash,
            "manifest_sha256": manifest_hash,
            "artifact_sha256": hashes,
        }), encoding="utf-8")

    def test_numeric_folder_order_is_not_lexical(self):
        from scripts.shadow_alignment_qa import numeric_reference_stems

        self.assertEqual(
            numeric_reference_stems(["107_Tramadol", "10_Ten", "2_Two"]),
            ["2-min", "10-min", "107-min"])

    def test_resume_skips_current_rerenders_stale_and_preserves_failed(self):
        from scripts.shadow_alignment_qa import run_resumable_batch

        manifests = {"2-min": "m2", "10-min": "m10", "107-min": "m107"}
        self._seed_completed("2-min", "driver-current", "m2", b"current")
        self._seed_completed("10-min", "driver-old", "m10", b"stale")
        self._seed_completed("107-min", "driver-old", "m107", b"preserve")
        old_failed_png = (self.out / "107-min.png").read_bytes()
        calls = []

        def render_one(stem, staging):
            calls.append(stem)
            if stem == "107-min":
                (staging / f"{stem}.png").write_bytes(b"partial")
                raise RuntimeError("synthetic render failure")
            for suffix in (".png", ".scene.json", ".object.png", ".shadow.png"):
                (staging / f"{stem}{suffix}").write_bytes(b"fresh" + suffix.encode())
            return {"gates": {"all_pass": True}}

        report = run_resumable_batch(
            ["2-min", "10-min", "107-min"], self.out,
            "driver-current", manifests, render_one)

        self.assertEqual(calls, ["10-min", "107-min"])
        self.assertEqual(report["skipped"], ["2-min"])
        self.assertEqual(report["completed"], ["10-min"])
        self.assertEqual([row["stem"] for row in report["failed"]], ["107-min"])
        self.assertEqual((self.out / "107-min.png").read_bytes(), old_failed_png)
        fresh = json.loads((self.out / "10-min.measurements.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(fresh["driver_sha256"], "driver-current")
        self.assertEqual(fresh["manifest_sha256"], "m10")
        self.assertTrue(fresh["artifact_sha256"])

    def test_batch_summary_requires_one_rig_and_exact_artifact_counts(self):
        from scripts.shadow_alignment_qa import summarise_reference_batch

        rig = {
            "scope": "common_carton_rig",
            "receiver_scale": 1.5,
            "receiver_offset_frac": 0.0005,
            "feather_start": 0.4,
            "ao_distance_frac": 0.04,
            "ao_samples": 4,
            "shadow_floor_linear": 0.78,
        }
        for stem, candidate, baseline in (
                ("2-min", 12.0, 10.0), ("10-min", 11.0, 10.0)):
            for suffix in (".png", ".object.png", ".shadow.png"):
                (self.out / f"{stem}{suffix}").write_bytes(b"pixel")
            (self.out / f"{stem}.scene.json").write_text(
                json.dumps({"shadow_rig": rig}), encoding="utf-8")
            (self.out / f"{stem}.measurements.json").write_text(json.dumps({
                "stem": stem,
                "driver_sha256": "one-driver",
                "candidate_seconds": candidate,
                "baseline_seconds": baseline,
                "gates": {"all_pass": True},
            }), encoding="utf-8")

        summary = summarise_reference_batch(
            self.out, ["2-min", "10-min"])

        self.assertTrue(summary["all_pass"])
        self.assertEqual(summary["artifact_counts"], {
            ".png": 2, ".scene.json": 2, ".object.png": 2,
            ".shadow.png": 2, ".measurements.json": 2,
        })
        self.assertEqual(summary["driver_fingerprint_count"], 1)
        self.assertEqual(summary["shadow_formula_count"], 1)
        self.assertAlmostEqual(summary["median_render_time_delta"], 0.15)


@unittest.skipUnless(Path(BLENDER_EXE).exists(),
                     f"Blender not installed at {BLENDER_EXE}")
class TestRenderedDiagnosticPasses(unittest.TestCase):
    """Scene projection and the existing beauty produce both masks."""

    @classmethod
    def setUpClass(cls):
        from src.render_manifest import build_manifest
        from PIL import Image

        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        passport = json.loads((
            PROJECT_ROOT / "04_passports/passports_json/74-min.json"
        ).read_text(encoding="utf-8"))
        job = root / "job.json"
        job.write_text(json.dumps(build_manifest(passport)), encoding="utf-8")
        cls.beauty = root / "beauty.png"
        cls.object_mask = root / "object.png"
        cls.shadow_mask = root / "shadow.png"
        cls.proc = subprocess.run(
            [BLENDER_EXE, "--background", "--factory-startup",
             "--python", DRIVER_SCRIPT, "--", "--job", str(job),
             "--out", str(cls.beauty), "--object-mask", str(cls.object_mask),
             "--shadow-mask", str(cls.shadow_mask), "--engine-type", "CYCLES",
             "--samples", "4", "--res-x", "256", "--res-y", "256",
             "--device", "CPU"],
            capture_output=True, text=True, timeout=300,
        )
        cls.images = Image

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_driver_writes_both_masks_without_a_second_render(self):
        self.assertEqual(
            self.proc.returncode, 0, self.proc.stdout + self.proc.stderr)
        self.assertTrue(self.beauty.is_file())
        self.assertTrue(self.object_mask.is_file())
        self.assertTrue(self.shadow_mask.is_file())

    def test_masks_are_nonempty_disjoint_and_frame_aligned(self):
        self.assertTrue(self.object_mask.is_file())
        self.assertTrue(self.shadow_mask.is_file())
        beauty = np.asarray(self.images.open(self.beauty).convert("RGB"))
        object_mask = np.asarray(
            self.images.open(self.object_mask).convert("L")) > 127
        shadow_mask = np.asarray(
            self.images.open(self.shadow_mask).convert("L")) > 1
        self.assertEqual(object_mask.shape, beauty.shape[:2])
        self.assertEqual(shadow_mask.shape, beauty.shape[:2])
        self.assertTrue(object_mask.any())
        self.assertTrue(shadow_mask.any())
        self.assertFalse(np.logical_and(object_mask, shadow_mask).any())

    def test_saved_object_mask_uses_png_top_down_coordinates(self):
        from scripts.shadow_alignment_qa import bbox_from_mask

        beauty = np.asarray(self.images.open(self.beauty).convert("RGB"))
        object_mask = np.asarray(
            self.images.open(self.object_mask).convert("L")) > 127
        # The navy face and grey lid form a conservative beauty silhouette;
        # the receiver never reaches this darkness.  A vertically flipped
        # Blender image buffer shifts the projected mask by several pixels even
        # at 256px and this ruler catches that convention error directly.
        beauty_silhouette = np.any(beauty < 240, axis=2)
        measured = bbox_from_mask(object_mask)
        visible = bbox_from_mask(beauty_silhouette)
        self.assertTrue(all(abs(a - b) <= 3
                            for a, b in zip(measured, visible)),
                        (measured, visible))

    def test_shadow_off_can_export_the_same_independent_object_pass(self):
        root = Path(self.tmp.name)
        off_beauty = root / "off.png"
        off_object = root / "off-object.png"
        proc = subprocess.run(
            [BLENDER_EXE, "--background", "--factory-startup",
             "--python", DRIVER_SCRIPT, "--", "--job", str(root / "job.json"),
             "--out", str(off_beauty), "--object-mask", str(off_object),
             "--shadow-off", "--engine-type", "CYCLES", "--samples", "1",
             "--res-x", "64", "--res-y", "64", "--device", "CPU"],
            capture_output=True, text=True, timeout=300,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(off_object.is_file())
