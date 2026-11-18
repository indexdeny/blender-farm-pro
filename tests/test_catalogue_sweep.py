"""Shadow-aware contracts for the diagnostic catalogue sweep."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from scripts import catalogue_sweep


class TestShadowAwareSweepMeasurement(unittest.TestCase):
    def test_measure_uses_the_carton_mask_instead_of_the_contact_shadow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            png = root / "74-min.png"
            mask_path = root / "74-min.object.png"
            manifest = root / "74-min.json"
            rgb = np.full((40, 60, 3), 255, np.uint8)
            rgb[8:28, 10:40] = 180
            rgb[28:35, 10:40] = 235
            mask = np.zeros((40, 60), np.uint8)
            mask[8:28, 10:40] = 255
            Image.fromarray(rgb).save(png)
            Image.fromarray(mask).save(mask_path)
            manifest.write_text(json.dumps({
                "palette": {"accent": "#123456"}
            }), encoding="utf-8")

            got = catalogue_sweep.measure(
                png, manifest, object_mask_path=mask_path)

            self.assertTrue(got["measured"])
            self.assertEqual(got["margins_px"], {
                "top": 8, "bottom": 12, "left": 10, "right": 20})

    def test_render_command_requests_object_and_shadow_outputs(self):
        command = catalogue_sweep.render_command("74-min")
        self.assertEqual(
            Path(command[command.index("--job") + 1]),
            catalogue_sweep.MANIFEST_DIR / "74-min.json")
        self.assertEqual(
            Path(command[command.index("--object-mask") + 1]),
            catalogue_sweep.OUT_DIR / "74-min.object.png")
        self.assertEqual(
            Path(command[command.index("--shadow-mask") + 1]),
            catalogue_sweep.OUT_DIR / "74-min.shadow.png")


if __name__ == "__main__":
    unittest.main()
