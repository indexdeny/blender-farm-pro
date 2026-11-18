"""Physical output isolation must preserve source ownership and containment."""

import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from src import carton_spec


class TestOutputRootCLI(unittest.TestCase):
    def test_runner_exposes_output_root(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(carton_spec.CODE_ROOT / "scripts/rebuild_carton.py"),
                "--help",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("--output-root", result.stdout)


class TestPhysicalOutputRoot(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.env = patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("BFP_PHYSICAL_OUTPUT_ROOT", None)
        self.code = patch.object(carton_spec, "CODE_ROOT", self.root)
        self.code.start()
        self.addCleanup(self.code.stop)

    def test_default_root_preserves_checkout_and_worktree_behavior(self):
        self.assertEqual(carton_spec.workspace_root(), self.root)
        with patch.object(carton_spec, "CODE_ROOT", self.root / ".worktrees" / "code"):
            self.assertEqual(carton_spec.workspace_root(), self.root)

    def test_output_root_is_resolved_descendant_of_reports(self):
        target = self.root / "reports" / "run" / "child" / ".."
        os.environ["BFP_PHYSICAL_OUTPUT_ROOT"] = str(target)
        self.assertEqual(carton_spec.workspace_root(), target.resolve())

    def test_rejects_reports_itself_and_escaping_paths(self):
        for target in (
            self.root,
            self.root / "reports",
            self.root / "reports-other" / "run",
            self.root / "reports" / ".." / "assets",
            Path(""),
        ):
            with self.subTest(target=target):
                os.environ["BFP_PHYSICAL_OUTPUT_ROOT"] = str(target)
                with self.assertRaises(ValueError):
                    carton_spec.workspace_root()

    def test_sources_stay_original_and_generated_assets_stay_isolated(self):
        target = self.root / "reports" / "run"
        source = self.root / "assets/sources/font.ttf"
        generated = target / "assets/generated/map.png"
        for path in (source, generated):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        os.environ["BFP_PHYSICAL_OUTPUT_ROOT"] = str(target)
        self.assertEqual(carton_spec.resolve_asset("assets/sources/font.ttf"), source)
        self.assertEqual(
            carton_spec.resolve_asset("assets/generated/map.png", generated=True),
            generated,
        )
        for asset_path, generated_flag in (
            (str(source), True),
            (str(generated), False),
            (str(self.root / "assets/generated/map.png"), True),
        ):
            with self.subTest(path=asset_path, generated=generated_flag):
                with self.assertRaises(ValueError):
                    carton_spec.resolve_asset(asset_path, generated=generated_flag)


if __name__ == "__main__":
    unittest.main()
