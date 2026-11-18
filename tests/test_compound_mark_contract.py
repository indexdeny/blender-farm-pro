"""Compound marks preserve one pairing envelope and ordered coloured regions."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import ValidationError

from src.render_manifest import build_manifest, validate_manifest


ROOT = Path(__file__).resolve().parents[1]


def rectangle(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def compound_manifest():
    manifest = json.loads((ROOT / "tests/fixtures/ocr/74-min.manifest.json").read_text())
    manifest["manifest_version"] = "1.11"
    envelope = rectangle(.1, .1, .9, .9)
    field = manifest["design"]["fields"][0]
    field["parts"] = [field["parts"][0]]
    field["parts"][0].update(outline=rectangle(0, 0, 1, 1), holes=[copy.deepcopy(envelope)], mark_holes=[0])
    manifest["design"]["fields"] = [field]
    manifest["design"]["marks"] = [{
        "role": "brand", "key": "brand#0/hole#0", "source": "hole",
        "fill": "#FFFFFF", "outline": envelope, "holes": [], "z": 1,
        "parts": [{"outline": rectangle(.2, .2, .5, .7),
                   "holes": [rectangle(.3, .3, .4, .4)], "fill": "#012958"}],
    }]
    return manifest


class TestCompoundMarkContract(unittest.TestCase):
    def assertRejected(self, manifest):
        with self.assertRaises((ValueError, ValidationError)):
            validate_manifest(manifest)

    def test_accepts_compound_mark_without_mutation(self):
        manifest = compound_manifest()
        before = copy.deepcopy(manifest)
        try:
            validate_manifest(manifest)
        except (ValueError, ValidationError) as exc:
            self.fail(f"valid compound mark rejected: {exc}")
        self.assertEqual(manifest, before)

    def test_build_selects_new_version_only_for_parts(self):
        manifest = compound_manifest()
        passport = json.loads((ROOT / "04_passports/passports_json/74-min.json").read_text())
        spec = manifest["design"]
        with patch("src.render_manifest.load_design", return_value=spec):
            actual = build_manifest(passport)
        self.assertEqual(actual["manifest_version"], "1.11")
        self.assertEqual(actual["design"]["marks"], spec["marks"])
        del spec["marks"][0]["parts"]
        with patch("src.render_manifest.load_design", return_value=spec):
            actual = build_manifest(passport)
        self.assertEqual(actual["manifest_version"], "1.10")
        validate_manifest(actual)

    def test_legacy_version_cannot_silently_ignore_parts(self):
        manifest = compound_manifest()
        manifest["manifest_version"] = "1.10"
        self.assertRejected(manifest)

    def test_legacy_reference_manifests_remain_readable(self):
        for path in sorted((ROOT / "tests/fixtures/ocr").glob("*.manifest.json")):
            with self.subTest(path=path.name):
                validate_manifest(json.loads(path.read_text()))

    def test_parts_must_be_nonempty_and_have_known_shape_and_colour(self):
        bad_parts = [[], None, {}, [{"outline": rectangle(.2, .2, .5, .5), "fill": "#012958"}]]
        for key, value in (("fill", "navy"), ("outline", []), ("texture", "letters.png"), ("parts", [])):
            part = copy.deepcopy(compound_manifest()["design"]["marks"][0]["parts"][0])
            part[key] = value
            bad_parts.append([part])
        for parts in bad_parts:
            with self.subTest(parts=parts):
                manifest = compound_manifest()
                manifest["design"]["marks"][0]["parts"] = parts
                self.assertRejected(manifest)

    def test_all_mark_rings_reject_nonfinite_out_of_face_and_malformed_points(self):
        for which in ("base", "part", "hole"):
            for point in ([float("nan"), .3], [float("inf"), .3], [-.1, .3], [1.1, .3], [True, .3]):
                with self.subTest(which=which, point=point):
                    manifest = compound_manifest()
                    mark = manifest["design"]["marks"][0]
                    ring = mark["outline"] if which == "base" else mark["parts"][0]["outline"] if which == "part" else mark["parts"][0]["holes"][0]
                    ring[0] = point
                    self.assertRejected(manifest)

    def test_simple_rings_reject_crossing_touching_degenerate_and_backtracking(self):
        bad_rings = [
            [[.2, .2], [.6, .6], [.2, .6], [.6, .2]],
            [[.2, .2], [.5, .2], [.5, .5], [.35, .2], [.2, .5]],
            [[.2, .2], [.3, .3], [.4, .4]],
            [[.2, .2], [.5, .2], [.3, .2], [.3, .5], [.2, .5]],
            [[.2, .2], [.5, .2], [.5, .2], [.2, .5]],
        ]
        for ring in bad_rings:
            with self.subTest(ring=ring):
                manifest = compound_manifest()
                manifest["design"]["marks"][0]["parts"][0].update(outline=ring, holes=[])
                self.assertRejected(manifest)

    def test_parts_outside_envelope_are_rejected(self):
        manifest = compound_manifest()
        manifest["design"]["marks"][0]["parts"][0]["outline"] = rectangle(.05, .2, .5, .7)
        self.assertRejected(manifest)

    def test_concave_envelope_rejects_edge_leaving_region_with_all_vertices_inside(self):
        manifest = compound_manifest()
        envelope = [[.1, .1], [.9, .1], [.9, .9], [.6, .9], [.6, .4], [.4, .4], [.4, .9], [.1, .9]]
        manifest["design"]["fields"][0]["parts"][0]["holes"] = [copy.deepcopy(envelope)]
        mark = manifest["design"]["marks"][0]
        mark["outline"] = envelope
        mark["parts"][0].update(outline=[[.2, .8], [.8, .8], [.2, .2]], holes=[])
        self.assertRejected(manifest)

    def test_envelope_vertex_contacts_cannot_hide_an_edge_across_a_notch(self):
        manifest = compound_manifest()
        envelope = [[.1, .1], [.9, .1], [.9, .9], [.6, .9], [.6, .4], [.4, .4], [.4, .9], [.1, .9]]
        manifest["design"]["fields"][0]["parts"][0]["holes"] = [copy.deepcopy(envelope)]
        mark = manifest["design"]["marks"][0]
        mark["outline"] = envelope
        mark["parts"][0].update(outline=[[.4, .9], [.6, .9], [.5, .2]], holes=[])
        self.assertRejected(manifest)

    def test_overlay_can_paint_a_base_hole_inside_the_outer_envelope(self):
        manifest = compound_manifest()
        manifest["design"]["marks"][0]["holes"] = [rectangle(.15, .15, .55, .75)]
        validate_manifest(manifest)

    def test_envelope_boundary_contact_is_valid(self):
        manifest = compound_manifest()
        manifest["design"]["marks"][0]["parts"][0]["outline"] = rectangle(.1, .2, .5, .7)
        try:
            validate_manifest(manifest)
        except (ValueError, ValidationError) as exc:
            self.fail(f"valid envelope boundary contact rejected: {exc}")

    def test_holes_cannot_escape_touch_overlap_or_nest(self):
        bad_holes = [
            [rectangle(.15, .3, .4, .4)], [rectangle(.2, .3, .4, .4)],
            [rectangle(.3, .3, .4, .4), rectangle(.35, .35, .45, .45)],
            [rectangle(.25, .25, .45, .6), rectangle(.3, .3, .4, .4)],
            [rectangle(.3, .3, .4, .4), rectangle(.4, .3, .45, .4)],
        ]
        for holes in bad_holes:
            with self.subTest(holes=holes):
                manifest = compound_manifest()
                manifest["design"]["marks"][0]["parts"][0]["holes"] = holes
                self.assertRejected(manifest)

    def test_pairing_uses_envelope_and_still_rejects_missing_host(self):
        manifest = compound_manifest()
        manifest["design"]["fields"][0]["parts"][0]["mark_holes"] = []
        self.assertRejected(manifest)

    def test_drawable_parts_preserve_base_then_overlay_and_holes(self):
        from src import mark_geometry
        mark = compound_manifest()["design"]["marks"][0]
        before = copy.deepcopy(mark)
        parts = mark_geometry.drawable_mark_parts(mark)
        self.assertEqual([p["fill"] for p in parts], ["#FFFFFF", "#012958"])
        self.assertEqual(parts[0]["outline"], rectangle(.1, .1, .9, .9))
        self.assertEqual(parts[1]["holes"], [rectangle(.3, .3, .4, .4)])
        self.assertEqual(mark, before)
        del mark["parts"]
        self.assertEqual(len(mark_geometry.drawable_mark_parts(mark)), 1)
