"""Additive acceptance tests for the photograph-free physical baseline."""

import copy
import json
from pathlib import Path
import unittest
import ast
import subprocess
import tempfile
from typing import Any

from src.carton_spec import load_spec, validate_spec, workspace_root
from src.carton_dieline import build_dieline
from src.carton_spec import CODE_ROOT, verify_generated
from src.carton_validate import (
    delta_e00,
    layout_metrics,
    inspect_scene,
    analytic_silhouette,
    material_metrics,
)


class TestPhysicalSpec(unittest.TestCase):
    def test_invalid_physical_parameters_and_unknown_keys_are_rejected(self):
        for section, key, value in [
            ("geometry", "board_thickness_mm", -1),
            ("geometry", "crease_depth_mm", 1),
            ("render", "samples", 0),
            ("atlas", "dpi", 300),
            ("geometry", "unknown_parameter", 2),
        ]:
            spec = copy.deepcopy(load_spec())
            spec[section][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_spec(spec)

    def test_mm_dimensions_are_template_dimensions(self):
        spec = load_spec()
        self.assertEqual(
            [spec["dimensions_mm"][k] for k in ("width", "height", "depth")],
            [110, 50, 18],
        )

    def test_missing_geometry_parameter_fails_without_defaults(self):
        spec = copy.deepcopy(load_spec())
        del spec["geometry"]["board_thickness_mm"]
        with self.assertRaises((ValueError, KeyError)):
            validate_spec(spec)

    def test_projection_and_photo_assets_are_rejected(self):
        spec = copy.deepcopy(load_spec())
        spec["assets"]["pfizer"]["path"] = (
            "Reference Templates/74_Viagra/raw_viagra_front.png"
        )
        with self.assertRaises(ValueError):
            validate_spec(spec)

    def test_required_elements_are_not_optional(self):
        spec = copy.deepcopy(load_spec())
        spec["elements"] = [e for e in spec["elements"] if e["id"] != "front_braille"]
        with self.assertRaises(ValueError):
            validate_spec(spec)


class TestPhysicalDieline(unittest.TestCase):
    def test_six_panels_and_structural_flaps(self):
        result = build_dieline(load_spec())
        self.assertEqual(
            {p["name"] for p in result["panels"]},
            {"front", "back", "left", "right", "top", "bottom"},
        )
        self.assertGreaterEqual(len(result["flaps"]), 5)
        self.assertTrue(any(p["name"] == "glue_seam" for p in result["flaps"]))

    def test_panel_atlas_regions_do_not_overlap(self):
        result = build_dieline(load_spec())
        regions = list(result["atlas"]["regions"].values())
        for i, a in enumerate(regions):
            for b in regions[i + 1 :]:
                overlap_x = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
                overlap_y = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
                self.assertFalse(overlap_x > 1e-8 and overlap_y > 1e-8)


class TestPhysicalPNG(unittest.TestCase):
    def test_all_views_must_use_the_same_unchanged_scene_snapshot(self):
        import hashlib
        from src.carton_validate import validate_render_snapshot

        (workspace_root() / "renders").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workspace_root() / "renders") as folder:
            path = Path(folder) / "stage.blend"
            path.write_bytes(b"scene snapshot fixture")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            evidence: dict[str, Any] = {
                "render_snapshot": {"path": str(path), "sha256": digest},
                "render_runs": [{"scene_snapshot_sha256": digest}] * 4,
            }
            validate_render_snapshot(evidence)
            altered = copy.deepcopy(evidence)
            altered["render_runs"][0] = {"scene_snapshot_sha256": "0" * 64}
            with self.assertRaises(ValueError):
                validate_render_snapshot(altered)
            path.write_bytes(b"different scene")
            with self.assertRaises(ValueError):
                validate_render_snapshot(evidence)

    def test_volatile_metadata_is_removed_without_changing_encoded_pixels(self):
        import struct
        import zlib
        from src.carton_stage import stable_png_bytes

        def chunk(kind, payload):
            return (
                struct.pack(">I", len(payload))
                + kind
                + payload
                + struct.pack(">I", zlib.crc32(kind + payload))
            )

        header = b"\x89PNG\r\n\x1a\n"
        ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        color = chunk(b"sRGB", b"\x00")
        pixels = chunk(b"IDAT", zlib.compress(b"\x00\x12\x34\x56\xff"))
        end = chunk(b"IEND", b"")
        expected = header + ihdr + color + pixels + end
        for timestamp in (b"first", b"second"):
            original = (
                header
                + ihdr
                + color
                + chunk(b"tEXt", b"Date\x00" + timestamp)
                + pixels
                + chunk(b"tEXt", b"cycles.ViewLayer.total_time\x001.25")
                + end
            )
            self.assertEqual(stable_png_bytes(original), expected)
        self.assertEqual(stable_png_bytes(expected), expected)
        with self.assertRaises(ValueError):
            stable_png_bytes(expected[:-1])


class TestPhysicalArtwork(unittest.TestCase):
    directory: tempfile.TemporaryDirectory[str]
    spec: dict[str, Any]
    artwork: dict[str, Any]

    @classmethod
    def setUpClass(cls):
        from src.carton_artwork import generate_artwork

        (workspace_root() / "assets/generated").mkdir(parents=True, exist_ok=True)
        cls.directory = tempfile.TemporaryDirectory(
            prefix="carton-test-", dir=workspace_root() / "assets/generated"
        )
        cls.addClassCleanup(cls.directory.cleanup)
        cls.spec = load_spec()
        cls.artwork = generate_artwork(cls.spec, Path(cls.directory.name))

    def test_all_raster_bboxes_within_one_point_five_mm(self):
        self.assertTrue(
            all(r["pass_"] for r in layout_metrics(self.spec, self.artwork))
        )

    def test_layout_instrument_detects_shifted_ink(self):
        altered = copy.deepcopy(self.artwork)
        next(e for e in altered["elements"] if e["id"] == "front_wordmark")[
            "atlas_origin_px"
        ][0] += 100
        result = next(
            r for r in layout_metrics(self.spec, altered) if r["id"] == "front_wordmark"
        )
        self.assertGreater(result["error_mm"], 1.5)
        self.assertFalse(result["pass_"])

    def test_provenance_rejects_reference_path_and_stale_hash(self):
        for key, value in [
            ("path", "Reference Templates/74_Viagra/raw_viagra_front.png"),
            ("sha256", "0" * 64),
        ]:
            altered = copy.deepcopy(self.artwork)
            altered["maps"]["base_color"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify_generated(altered)

    def test_missing_pbr_map_is_rejected(self):
        altered = copy.deepcopy(self.artwork)
        del altered["maps"]["metallic"]
        with self.assertRaises(ValueError):
            verify_generated(altered)

    def test_generated_maps_reproduce(self):
        from src.carton_artwork import generate_artwork

        repeated = generate_artwork(self.spec, Path(self.directory.name))
        self.assertEqual(
            {k: v["sha256"] for k, v in self.artwork["maps"].items()},
            {k: v["sha256"] for k, v in repeated["maps"].items()},
        )

    def test_real_map_pixels_zone_paper_foil_and_grain(self):
        self.assertTrue(material_metrics(self.spec, self.artwork)["pass_"])

    def test_isolated_production_import_graph(self):
        for name in (
            "carton_spec",
            "carton_dieline",
            "carton_artwork",
            "carton_mesh",
            "carton_materials",
            "carton_stage",
            "carton_scene",
        ):
            tree = ast.parse((CODE_ROOT / "src" / f"{name}.py").read_text("utf-8"))
            imports = [
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            ]
            imports += [
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            ]
            self.assertNotIn("src.reference_projection", imports)
            self.assertNotIn("src.carton_validate", imports)
            self.assertNotIn("scripts.fit_design_spec", imports)

    def test_physical_manifest_never_loads_photographic_design(self):
        from unittest.mock import patch
        from src.render_manifest import build_baseline_manifest

        passport = json.loads(
            (CODE_ROOT / "04_passports/passports_json/74-min.json").read_text("utf-8")
        )
        with patch(
            "src.render_manifest.load_design",
            side_effect=AssertionError("Legacy photo design read"),
        ):
            result = build_baseline_manifest(passport, self.spec, self.artwork)
        self.assertNotIn("design", result)
        self.assertEqual(result["manifest_version"], "1.13")


class TestPhysicalMetrics(unittest.TestCase):
    def test_ciede2000_published_reference_pairs(self):
        for a, b, expected in [
            ([50, 2.6772, -79.7751], [50, 0, -82.7485], 2.0425),
            ([50, 3.1571, -77.2803], [50, 0, -82.7485], 2.8615),
            ([50, 0, 0], [50, 0, 0], 0),
        ]:
            self.assertAlmostEqual(delta_e00(a, b), expected, places=4)


class TestPhysicalBlender(unittest.TestCase):
    directory: tempfile.TemporaryDirectory[str]
    spec: dict[str, Any]
    artwork: dict[str, Any]
    scene: dict[str, Any]
    repeat_scene: dict[str, Any]

    @classmethod
    def setUpClass(cls):
        from src.carton_artwork import generate_artwork
        from src.render_manifest import build_baseline_manifest, write_manifest
        import yaml

        (workspace_root() / "assets/generated").mkdir(parents=True, exist_ok=True)
        cls.directory = tempfile.TemporaryDirectory(
            prefix="carton-scene-test-", dir=workspace_root() / "assets/generated"
        )
        cls.addClassCleanup(cls.directory.cleanup)
        cls.spec = load_spec()
        cls.artwork = generate_artwork(cls.spec, Path(cls.directory.name))
        passport = json.loads(
            (CODE_ROOT / "04_passports/passports_json/74-min.json").read_text("utf-8")
        )
        manifest = build_baseline_manifest(passport, cls.spec, cls.artwork)
        directory = workspace_root() / "02_processing/rebuild-test-temp"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as tmp:
            job = Path(tmp) / "job.json"
            dump = Path(tmp) / "scene.json"
            write_manifest(manifest, job)
            exe = yaml.safe_load((CODE_ROOT / "config.yaml").read_text("utf-8"))[
                "blender"
            ]["executable"]
            command = [
                exe,
                "--background",
                "--factory-startup",
                "--python",
                str(CODE_ROOT / "05_assets/blender/render_driver.py"),
                "--",
                "--job",
                str(job),
                "--dump-scene",
                str(dump),
            ]
            result = subprocess.run(command, capture_output=True, timeout=60)
            if result.returncode or not dump.exists():
                raise AssertionError(result.stdout.decode("utf-8", errors="replace"))
            cls.scene = json.loads(dump.read_text("utf-8"))
            result = subprocess.run(command, capture_output=True, timeout=60)
            if result.returncode:
                raise AssertionError(result.stdout.decode("utf-8", errors="replace"))
            cls.repeat_scene = json.loads(dump.read_text("utf-8"))

    def test_independent_builds_have_identical_mesh_and_uv_data(self):
        def hashes(scene):
            return {
                o["name"]: (o["mesh_sha256"], o["uv_sha256"]) for o in scene["objects"]
            }

        self.assertEqual(hashes(self.scene), hashes(self.repeat_scene))

    def test_real_geometry_dimensions_normals_bevels_scale(self):
        report = inspect_scene(self.spec, self.scene)
        self.assertTrue(report["pass_"], report["issues"])
        self.assertGreater(report["braille_count"], 0)
        self.assertGreater(report["emboss_count"], 0)

    def test_validation_rejects_missing_required_relief_and_flaps(self):
        for kind in ("braille", "emboss", "flap", "foil"):
            scene = copy.deepcopy(self.scene)
            scene["objects"] = [o for o in scene["objects"] if o["kind"] != kind]
            with self.subTest(kind=kind):
                self.assertFalse(inspect_scene(self.spec, scene)["pass_"])

    def test_validation_rejects_stale_spec_and_missing_scene_maps(self):
        from src.carton_validate import evaluate

        changed = copy.deepcopy(self.spec)
        changed["render"]["seed"] += 1
        with self.assertRaises(ValueError):
            evaluate(changed, self.artwork, self.scene)
        scene = copy.deepcopy(self.scene)
        scene["images"] = []
        with self.assertRaises(ValueError):
            evaluate(self.spec, self.artwork, scene)

    def test_true_top_crease(self):
        top = next(o for o in self.scene["objects"] if o["name"] == "top")
        self.assertAlmostEqual(
            top["crease_depth_mm"], self.spec["geometry"]["crease_depth_mm"]
        )
        self.assertGreater(top["triangles"], 12)

    def test_one_material_and_verified_images(self):
        self.assertEqual(
            len({tuple(o["material_names"]) for o in self.scene["objects"]}), 1
        )
        expected = {r["sha256"] for r in self.artwork["maps"].values()}
        self.assertEqual({r["sha256"] for r in self.scene["images"]}, expected)
        self.assertTrue(all(r["packed"] for r in self.scene["images"]))
        self.assertTrue(
            all(r["packed_sha256"] == r["sha256"] for r in self.scene["images"])
        )
        self.assertTrue(all(r["linked"] for r in self.scene["shader_inputs"].values()))

    def test_actual_render_settings_match_declared_contract(self):
        runtime = self.scene["runtime_render"]
        self.assertFalse(runtime["animated_seed"])
        for key, value in runtime.items():
            if key == "animated_seed":
                continue
            expected = self.spec["render"][key]
            if isinstance(value, float):
                self.assertAlmostEqual(value, expected, places=5)
            else:
                self.assertEqual(value, expected, key)

    def test_all_four_cameras_frame_the_physical_carton(self):
        self.assertEqual(set(self.scene["views"]), {"front", "hero", "top", "end"})
        for name, view in self.scene["views"].items():
            mask, unclipped = analytic_silhouette(self.spec, view)
            self.assertTrue(unclipped, name)
            self.assertGreater(mask.sum(), 10000)


if __name__ == "__main__":
    unittest.main()
