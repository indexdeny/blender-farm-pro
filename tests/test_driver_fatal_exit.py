"""A failed sidecar write must never look like a successful Blender job."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_blender_carton import BLENDER_EXE, PROJECT_ROOT


@unittest.skipUnless(Path(BLENDER_EXE).exists(), 'Blender is not installed')
class TestFatalOutputWrite(unittest.TestCase):
    def test_unwritable_sidecar_returns_nonzero_without_render(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'absent' / '74-min.png'
            result = subprocess.run([
                str(BLENDER_EXE), '--background', '--factory-startup',
                '--python', str(PROJECT_ROOT / '05_assets/blender/render_driver.py'),
                '--', '--job', str(PROJECT_ROOT / '04_passports/render_manifests/74-min.json'),
                '--out', str(output), '--engine-type', 'CYCLES',
                '--samples', '1', '--res-x', '32', '--res-y', '32', '--device', 'CPU',
            ], capture_output=True, text=True, timeout=90)
            self.assertIn('74-min.view.json', result.stdout + result.stderr)
            self.assertFalse(output.exists())
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
