"""Regression tests for the render-device probe boundary."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import probe_render_device


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestBpyOwnership(unittest.TestCase):
    def test_render_driver_is_the_only_python_source_that_imports_bpy(self):
        """INV-001 is a source boundary, including generated script literals."""
        owners = set()
        for root_name in ("src", "scripts", "05_assets", "tests"):
            for path in (PROJECT_ROOT / root_name).rglob("*.py"):
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.lstrip().startswith("import " + "bpy"):
                        owners.add(path.relative_to(PROJECT_ROOT).as_posix())
        self.assertEqual(owners, {"05_assets/blender/render_driver.py"})


class TestProbeCommand(unittest.TestCase):
    def test_every_probe_configuration_is_expressed_as_driver_flags(self):
        expected = {
            "cpu": ("CPU", "OPTIX", "CPU"),
            "optix": ("GPU", "OPTIX", "CPU"),
            "optix+gpudenoise": ("GPU", "OPTIX", "GPU"),
            "cuda": ("GPU", "CUDA", "CPU"),
        }
        with tempfile.TemporaryDirectory() as td:
            for config, values in expected.items():
                with self.subTest(config=config):
                    cmd = probe_render_device.render_command(
                        "64-min", config, Path(td))
                    self.assertEqual(cmd.count("--python"), 1)
                    self.assertEqual(
                        cmd[cmd.index("--device") + 1], values[0])
                    self.assertEqual(
                        cmd[cmd.index("--device-backend") + 1], values[1])
                    self.assertEqual(
                        cmd[cmd.index("--denoising-device") + 1], values[2])


if __name__ == "__main__":
    unittest.main()
