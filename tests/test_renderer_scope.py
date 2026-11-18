"""Supported public renderer contract boundaries."""

import json
from pathlib import Path
import unittest

from jsonschema.exceptions import ValidationError

from src.render_manifest import build_manifest, validate_manifest


class TestPublicRendererScope(unittest.TestCase):
    def test_retired_projection_contract_version_is_rejected(self):
        root = Path(__file__).resolve().parents[1]
        passport = json.loads(
            (root / "04_passports/passports_json/74-min.json").read_text("utf-8")
        )
        manifest = build_manifest(passport)
        manifest["manifest_version"] = "1.12"
        with self.assertRaises(ValidationError):
            validate_manifest(manifest)
