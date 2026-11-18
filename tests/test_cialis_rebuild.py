"""Additive regression gates for the independent Cialis physical profile."""

import copy
import json
import math
from pathlib import Path
import subprocess
import tempfile
from typing import Any, cast
from src.carton_spec import CODE_ROOT, workspace_root
from src.carton_validate import inspect_scene, analytic_silhouette
import io
import unittest

import cairosvg
from PIL import Image

from src.carton_artwork import element_svg
from src.carton_spec import load_spec, validate_spec


class TestCialisExtensions(unittest.TestCase):
    def test_authored_bezier_has_real_curved_alpha(self):
        spec = load_spec()
        element = dict(
            id="curve",
            kind="path",
            bbox_mm=[0, 0, 20, 10],
            color="navy",
            path_mm="M0 0 H20 Q20 10 0 10 Z",
        )
        try:
            _, _, svg = element_svg(element, spec)
        except ValueError as exc:
            self.fail(f"Authored curves unavailable: {exc}")
        png = Image.open(
            io.BytesIO(
                cairosvg.svg2png(
                    bytestring=svg.encode(), output_width=200, output_height=100
                )
            )
        )
        self.assertGreater(cast(int, png.getchannel("A").getpixel((10, 50))), 250)
        self.assertEqual(png.getchannel("A").getpixel((199, 99)), 0)

    def test_oval_foil_does_not_print_rectangular_corners(self):
        spec = load_spec()
        foil = copy.deepcopy(next(e for e in spec["elements"] if e["kind"] == "foil"))
        foil["shape"] = "ellipse"
        _, _, svg = element_svg(foil, spec)
        png = Image.open(
            io.BytesIO(
                cairosvg.svg2png(
                    bytestring=svg.encode(), output_width=280, output_height=200
                )
            )
        )
        self.assertEqual(png.getchannel("A").getpixel((14, 10)), 0)
        self.assertEqual(png.getchannel("A").getpixel((140, 100)), 255)

    def test_unknown_brand_profile_is_rejected(self):
        spec = load_spec()
        spec["layout_profile"] = "unknown"
        with self.assertRaises(ValueError):
            validate_spec(spec)

    def test_cialis_contract_accepts_its_own_mandatory_elements(self):
        spec = copy.deepcopy(load_spec())
        spec["sku"] = "59-min"
        spec["layout_profile"] = "cialis"
        names = {
            "front_sildenafil": "front_tadalafil",
            "front_pfizer": "front_lilly",
            "front_band": "front_green",
            "front_transition": "front_cream",
        }
        for element in spec["elements"]:
            element["id"] = names.get(element["id"], element["id"])
        spec["elements"] = [e for e in spec["elements"] if e["id"] != "front_emboss"]
        # This synthetic spec tests required IDs; final asset/label identity has separate gates.
        try:
            validate_spec(spec)
        except ValueError as exc:
            self.fail(f"Cialis mandatory layout not accepted: {exc}")
        for identifier in (
            "front_tadalafil",
            "front_lilly",
            "front_braille",
            "front_foil",
        ):
            invalid = copy.deepcopy(spec)
            invalid["elements"] = [
                e for e in invalid["elements"] if e["id"] != identifier
            ]
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                validate_spec(invalid)


class TestCialisAssets(unittest.TestCase):
    spec: dict[str, Any]
    artwork: dict[str, Any]
    passport: dict[str, Any]

    @classmethod
    def setUpClass(cls):
        from src.carton_spec import CODE_ROOT, workspace_root
        import json

        cls.spec = load_spec(
            CODE_ROOT / "Reference Templates/59_Cialis/design_spec.json"
        )
        from src.carton_artwork import generate_artwork

        cls.artwork = generate_artwork(cls.spec)
        cls.passport = json.loads(
            (CODE_ROOT / "04_passports/passports_json/59-min.json").read_text("utf-8")
        )

    def test_layout_and_maps_use_cialis_assets(self):
        from src.carton_validate import layout_metrics, material_metrics

        self.assertTrue(
            all(r["pass_"] for r in layout_metrics(self.spec, self.artwork))
        )
        self.assertTrue(material_metrics(self.spec, self.artwork)["pass_"])
        for item in self.artwork["maps"].values():
            self.assertTrue(item["path"].startswith("assets/generated/59-min/"))
        elements = {e["id"]: e for e in self.spec["elements"]}
        self.assertEqual(elements["front_dose"]["text"], "20 mg")
        self.assertEqual(elements["front_count"]["text"], "30 film-coated tablets")
        self.assertEqual(elements["front_tadalafil"]["asset"], "ingredient")
        self.assertEqual(elements["front_braille"]["lines"], ["cialis", "20 mg"])
        self.assertEqual(elements["front_foil"]["shape"], "ellipse")
        self.assertNotIn("front_sildenafil", elements)
        self.assertNotIn("front_pfizer", elements)
        self.assertNotIn("front_emboss", elements)

    def test_manifest_rejects_another_sku_passport(self):
        from src.render_manifest import build_baseline_manifest

        wrong = copy.deepcopy(self.passport)
        wrong["sku_id"] = "74-min.jpg"
        with self.assertRaises(ValueError):
            build_baseline_manifest(wrong, self.spec, self.artwork)

    def test_manifest_rejects_artwork_from_a_different_spec(self):
        from src.render_manifest import build_baseline_manifest

        wrong = copy.deepcopy(self.spec)
        wrong["render"]["seed"] += 1
        with self.assertRaises(ValueError):
            build_baseline_manifest(self.passport, wrong, self.artwork)

    def test_estimated_shape_does_not_replace_passport_dimensions(self):
        from src.render_manifest import build_baseline_manifest
        result = build_baseline_manifest(self.passport, self.spec, self.artwork)
        self.assertEqual(result["carton"]["passport_dimensions"]["height_mm"], 50)
        self.assertEqual(result["carton"]["height_mm"], 69.201)

    def test_cialis_manifest_uses_cialis_palette_and_dimensions(self):
        from src.render_manifest import build_baseline_manifest

        result = build_baseline_manifest(self.passport, self.spec, self.artwork)
        self.assertEqual(result["product_code"], "59-min")
        self.assertEqual(
            result["palette"]["primary"], self.spec["colors"]["green"]["hex"]
        )
        self.assertEqual(result["carton"]["height_mm"], 69.201)
        self.assertNotIn("design", result)


class TestCialisBlender(unittest.TestCase):
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
            prefix="cialis-scene-test-", dir=workspace_root() / "assets/generated"
        )
        cls.addClassCleanup(cls.directory.cleanup)
        cls.spec = load_spec(
            CODE_ROOT / "Reference Templates/59_Cialis/design_spec.json"
        )
        cls.artwork = generate_artwork(cls.spec, Path(cls.directory.name))
        passport = json.loads(
            (CODE_ROOT / "04_passports/passports_json/59-min.json").read_text("utf-8")
        )
        manifest = build_baseline_manifest(passport, cls.spec, cls.artwork)
        directory = workspace_root() / "reports/59-min/test-temp"
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
        self.assertEqual(report["emboss_count"], 0)

    def test_validation_rejects_missing_required_relief_and_flaps(self):
        for kind in ("braille", "flap", "foil"):
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

    def test_foil_volume_is_elliptical_and_not_rectangular(self):
        foil = next(o for o in self.scene["objects"] if o["name"] == "front_foil")
        expected = math.pi * 22 * 11.5 / 4 * 0.04
        self.assertLess(abs(foil["signed_volume_mm3"] / expected - 1), 0.05)


if __name__ == "__main__":
    unittest.main()
