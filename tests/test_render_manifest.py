"""Tests for the Stage 1 -> Stage 2 render-manifest contract.

Both sides of the boundary are checked against the SAME artifact
(schemas/render_manifest.schema.json) rather than against each other's
expectations, which is the point of the contract.
"""
import json
import re
import unittest
from pathlib import Path

from src import silhouette
from src.render_manifest import (
    MANIFEST_VERSION,
    TARGET_SILHOUETTE_ASPECT,
    build_manifest,
    load_schema,
    orient_for_template,
    reshape_to_art_direction,
    resolve_carton,
    validate_manifest,
    manifest_path_for,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PASSPORTS = PROJECT_ROOT / "04_passports" / "passports_json"


def _passport(stem: str) -> dict:
    return json.loads((PASSPORTS / f"{stem}.json").read_text(encoding="utf-8"))


def _all_passport_stems() -> list:
    return sorted(p.stem for p in PASSPORTS.glob("*.json"))


class TestManifestSchema(unittest.TestCase):
    """The artifact itself must be a well-formed, self-consistent schema."""

    def test_schema_loads_and_is_valid(self):
        from jsonschema import Draft202012Validator
        Draft202012Validator.check_schema(load_schema())

    def test_schema_pins_the_manifest_version(self):
        from src.render_manifest import COMPOUND_MARK_MANIFEST_VERSION
        self.assertEqual(
            set(load_schema()["properties"]["manifest_version"]["enum"]),
            {MANIFEST_VERSION, COMPOUND_MARK_MANIFEST_VERSION, "1.13"},
            "schema must explicitly list supported contract versions",
        )


class TestBuildManifest(unittest.TestCase):
    """Provider side: what Stage 1 emits must satisfy the contract."""

    def test_real_passport_produces_valid_manifest(self):
        m = build_manifest(_passport("1-min"))
        validate_manifest(m)          # raises on any contract violation
        self.assertEqual(m["manifest_version"], MANIFEST_VERSION)
        self.assertEqual(m["sku_id"], _passport("1-min")["sku_id"])

    def test_carton_comes_from_the_passports_own_secondary_dimensions(self):
        # 1-min declares "115x55x48mm"; those exact numbers must survive to
        # the manifest rather than being round-tripped through the primary
        # package, which is lossy. Since contract 1.3 they survive in
        # passport_dimensions -- the geometry beside them is art-directed and is
        # deliberately NOT these numbers.
        m = build_manifest(_passport("1-min"))
        real = m["carton"]["passport_dimensions"]
        self.assertEqual(real["source"], "passport_secondary")
        self.assertAlmostEqual(real["width_mm"], 115.0)
        self.assertAlmostEqual(real["height_mm"], 55.0)
        self.assertAlmostEqual(real["depth_mm"], 48.0)

    def test_the_printed_size_is_never_the_rendered_size_by_accident(self):
        # The one mistake contract 1.3 exists to prevent: printing art-directed
        # measurements on pharmaceutical packaging. If a reshape ever silently
        # stops happening, this catches it before a packshot carries a number
        # that is real by coincidence rather than by construction.
        m = build_manifest(_passport("1-min"))
        self.assertEqual(m["carton"]["source"], "art_direction")
        self.assertNotAlmostEqual(m["carton"]["height_mm"],
                                  m["carton"]["passport_dimensions"]["height_mm"],
                                  places=3)

    def test_template_id_matches_the_router(self):
        from src.passport_generator import agent_1_router
        for stem in ("1-min", "192-min", "293-min"):
            data = _passport(stem)
            expected_tid, expected_override = agent_1_router(data)
            m = build_manifest(data)
            self.assertEqual(m["template_id"], expected_tid, stem)
            self.assertEqual(m["is_bottle_override"], expected_override, stem)

    def test_label_content_is_carried_verbatim(self):
        data = _passport("1-min")
        m = build_manifest(data)
        for field in ("brand_name_display", "dosage_display", "unit_count_display"):
            self.assertEqual(m["label_content"][field], data["label_content"][field])

    def test_active_ingredient_comes_from_the_passports_top_level(self):
        """The one label row the passport does NOT keep in label_content.

        It lives at the passport's top level as `active_ingredient`, so it is the
        one field build_manifest cannot read off `label` like its siblings, and
        the one most likely to be silently dropped.
        """
        data = _passport("1-min")
        m = build_manifest(data)
        self.assertEqual(m["label_content"]["active_ingredient_display"],
                         data["active_ingredient"])
        self.assertTrue(m["label_content"]["active_ingredient_display"],
                        "ingredient row is empty; the front face would render "
                        "without it and the packshot would be wrong, not merely "
                        "plain")

    def test_every_sku_has_an_ingredient_to_print(self):
        """All 391 carry one today. If that ever stops being true the renderer
        needs a documented fallback, so fail here rather than discover it as a
        blank row in a finished packshot."""
        empty = [stem for stem in _all_passport_stems()
                 if not (_passport(stem).get("active_ingredient") or "").strip()]
        self.assertEqual(empty, [], f"{len(empty)} SKU have no active_ingredient")

    def test_carton_carries_the_declared_construction_features(self):
        """Real per-SKU data, and the side panel is drawn from it: 370 of 391
        cartons declare Braille / DataMatrix_Zone / Tamper_Evident_Seal and 21
        declare nothing. A renderer that assumes every carton is identical gets
        the 21 wrong."""
        data = _passport("1-min")
        m = build_manifest(data)
        self.assertEqual(m["carton"]["features"],
                         data["secondary_packaging"]["features"])
        self.assertEqual(m["carton"]["material"],
                         data["secondary_packaging"]["material"])

    def test_features_survive_the_dimension_fallbacks(self):
        """Construction data is independent of whether the dimension string
        parsed, so it must travel on the derived and ratio paths too."""
        data = _passport("1-min")
        data["secondary_packaging"] = dict(data["secondary_packaging"],
                                           dimensions="not a size")
        m = build_manifest(data)
        self.assertNotEqual(m["carton"]["passport_dimensions"]["source"],
                            "passport_secondary",
                            "test premise: this should have left the happy path")
        self.assertEqual(m["carton"]["features"],
                         data["secondary_packaging"]["features"])
        self.assertTrue(m["carton"]["material"])

    def test_carton_is_the_secondary_not_the_primary_package(self):
        """The rendered object is the printed box, so the manifest must carry
        the carton. The blister inside is strictly smaller."""
        from src.passport_generator import get_primary_package
        data = _passport("1-min")
        primary = get_primary_package(data)
        m = build_manifest(data)
        self.assertGreater(m["carton"]["width_mm"], primary.width_mm)
        self.assertGreater(m["carton"]["depth_mm"], primary.depth_mm)


class TestCartonFallbacks(unittest.TestCase):
    """Dimensions must always be present; only their provenance varies."""

    BASE = {
        "sku_id": "synthetic-min.jpg",
        "product_name": "Synthetic Test Product",
        "packaging_geometry": "BLISTER",
        "minimal_package": 30,
        "branding": {"palette": {"primary": "#003366",
                                 "accent": "#0D5FB8",
                                 "background": "#FFFFFF"}},
        "label_content": {"brand_name_display": "Synthetic",
                          "dosage_display": "20mg",
                          "unit_count_display": "30 Pills"},
    }

    def test_unparseable_dimensions_fall_back_to_derivation(self):
        data = dict(self.BASE, secondary_packaging={"dimensions": "medium sized"})
        m = build_manifest(data)
        validate_manifest(m)
        self.assertEqual(m["carton"]["passport_dimensions"]["source"],
                         "derived_from_primary")
        self.assertGreater(m["carton"]["width_mm"], 0)

    def test_missing_secondary_packaging_still_yields_dimensions(self):
        m = build_manifest(dict(self.BASE))
        validate_manifest(m)
        self.assertIn(m["carton"]["passport_dimensions"]["source"],
                      ("derived_from_primary", "template_ratio"))
        self.assertGreater(m["carton"]["height_mm"], 0)

    def test_dimensions_are_never_null(self):
        """The whole reason the driver could silently guess was a null here."""
        for payload in ({}, {"dimensions": ""}, {"dimensions": "115x55"}):
            m = build_manifest(dict(self.BASE, secondary_packaging=payload))
            for axis in ("width_mm", "height_mm", "depth_mm"):
                self.assertIsNotNone(m["carton"][axis])
                self.assertGreater(m["carton"][axis], 0)


class TestOrientation(unittest.TestCase):
    """The dimension string supplies three extents but not which way is up;
    the template decides. Each expectation below is anchored to a curated
    reference render in 01_input_raster/reference/."""

    def test_vertical_family_stands_the_longest_edge_up(self):
        from src.render_manifest import orient_for_template
        # T_VERT_VIAL_144 (HUCOG-2000) reads "170x80x35mm" and renders portrait.
        self.assertEqual(orient_for_template((170.0, 80.0, 35.0), "T_VERT_VIAL"),
                         (80.0, 170.0, 35.0))
        # T_VERT_DROPPER_229 (Lumigan) reads "110x50x18mm", also portrait.
        self.assertEqual(orient_for_template((110.0, 50.0, 18.0), "T_VERT_DROPPER"),
                         (50.0, 110.0, 18.0))

    def test_horizontal_family_keeps_the_passport_order(self):
        from src.render_manifest import orient_for_template
        # T1_1 (Atomoxetine) reads the same "115x55x48mm" as the inhaler below
        # but renders landscape.
        self.assertEqual(orient_for_template((115.0, 55.0, 48.0), "T1"),
                         (115.0, 55.0, 48.0))
        # T_MULTIPACK_347 reads "110x50x18mm" and renders landscape, unlike the
        # dropper with the identical string.
        self.assertEqual(orient_for_template((110.0, 50.0, 18.0), "T_MULTIPACK"),
                         (110.0, 50.0, 18.0))

    def test_identical_string_diverges_by_template(self):
        """The whole reason orientation cannot be read off the string."""
        from src.render_manifest import orient_for_template
        dims = (115.0, 55.0, 48.0)
        self.assertNotEqual(orient_for_template(dims, "T1"),
                            orient_for_template(dims, "T_VERT_INHALER"))

    def test_already_upright_string_is_left_alone(self):
        from src.render_manifest import orient_for_template
        # T_BOTTLE_BOX_10 (Revia) reads "55x100x55mm" — the height is already
        # the largest extent, so reorienting must be a no-op.
        self.assertEqual(orient_for_template((55.0, 100.0, 55.0), "T_BOTTLE_BOX"),
                         (55.0, 100.0, 55.0))

    def test_every_vertical_family_sku_stands_upright_before_reshaping(self):
        for f in sorted(PASSPORTS.glob("*.json")):
            m = build_manifest(json.loads(f.read_text(encoding="utf-8")))
            if m["template_id"] in ("T_BOTTLE_BOX", "T_VERT_VIAL",
                                    "T_VERT_DROPPER", "T_VERT_INHALER"):
                c = m["carton"]["passport_dimensions"]
                self.assertGreaterEqual(
                    c["height_mm"], max(c["width_mm"], c["depth_mm"]),
                    f"{f.stem} ({m['template_id']}) is not upright",
                )

    def test_every_vertical_family_sku_still_PHOTOGRAPHS_portrait(self):
        # The claim worth holding is about the picture, and after reshaping it
        # is no longer the same claim as "the box is taller than it is wide".
        # T_VERT_VIAL solves to 172x170x35: wider than tall, and still a portrait
        # photograph at 0.9224 because the camera looks down a portrait carton.
        # Asserting on the box edges here would fail on a correct reshape.
        for f in sorted(PASSPORTS.glob("*.json")):
            m = build_manifest(json.loads(f.read_text(encoding="utf-8")))
            if m["template_id"] in ("T_BOTTLE_BOX", "T_VERT_VIAL",
                                    "T_VERT_DROPPER", "T_VERT_INHALER"):
                c = m["carton"]
                dims = (c["width_mm"], c["height_mm"], c["depth_mm"])
                self.assertLess(
                    silhouette.visible_faces_aspect(dims, m["template_id"]), 1.0,
                    f"{f.stem} ({m['template_id']}) photographs landscape",
                )


class TestContractRejectsDrift(unittest.TestCase):
    """A contract that accepts anything is not a contract."""

    def setUp(self):
        self.valid = build_manifest(_passport("1-min"))

    def test_a_1_2_manifest_is_rejected_rather_than_read_as_1_3(self):
        """The bump that must not be forgiving.

        1.3 repurposed carton.width_mm/height_mm/depth_mm from the carton's real
        size to art-directed scene geometry. A 1.2 file has the old meaning in
        the new field names and no passport_dimensions at all, so a consumer that
        accepted it would build the box from real dimensions -- merely wrong --
        and print whatever it could find -- not merely wrong. Both failure modes
        are silent, which is why the version is a const and not a minimum.
        """
        from jsonschema import ValidationError
        legacy = json.loads(json.dumps(self.valid))
        legacy["manifest_version"] = "1.2"
        real = legacy["carton"].pop("passport_dimensions")
        legacy["carton"].update({k: real[k] for k in
                                 ("width_mm", "height_mm", "depth_mm")})
        legacy["carton"]["source"] = real["source"]
        with self.assertRaises(ValidationError):
            validate_manifest(legacy)

    def test_a_manifest_without_the_real_dimensions_is_rejected(self):
        from jsonschema import ValidationError
        bad = json.loads(json.dumps(self.valid))
        bad["carton"].pop("passport_dimensions")
        with self.assertRaises(ValidationError):
            validate_manifest(bad)

    def test_unknown_field_is_rejected(self):
        from jsonschema import ValidationError
        bad = dict(self.valid, surprise_field="drift")
        with self.assertRaises(ValidationError):
            validate_manifest(bad)

    def test_missing_carton_is_rejected(self):
        from jsonschema import ValidationError
        bad = {k: v for k, v in self.valid.items() if k != "carton"}
        with self.assertRaises(ValidationError):
            validate_manifest(bad)

    def test_negative_dimension_is_rejected(self):
        from jsonschema import ValidationError
        bad = json.loads(json.dumps(self.valid))
        bad["carton"]["width_mm"] = -1
        with self.assertRaises(ValidationError):
            validate_manifest(bad)

    def test_malformed_hex_colour_is_rejected(self):
        from jsonschema import ValidationError
        bad = json.loads(json.dumps(self.valid))
        bad["palette"]["accent"] = "0D5FB8"      # missing the leading hash
        with self.assertRaises(ValidationError):
            validate_manifest(bad)

    def test_unknown_template_id_is_rejected(self):
        from jsonschema import ValidationError
        bad = dict(self.valid, template_id="T_NOT_A_TEMPLATE")
        with self.assertRaises(ValidationError):
            validate_manifest(bad)


class TestWholeCatalogue(unittest.TestCase):
    """Every SKU in the catalogue must satisfy the contract, not just samples."""

    def test_all_passports_produce_valid_manifests(self):
        files = sorted(PASSPORTS.glob("*.json"))
        self.assertGreater(len(files), 0, "no passports found")
        failures = []
        guessed = []
        for f in files:
            try:
                m = build_manifest(json.loads(f.read_text(encoding="utf-8")))
                validate_manifest(m)
                if m["carton"]["passport_dimensions"]["source"] == "template_ratio":
                    guessed.append(f.stem)
            except Exception as e:  # noqa: BLE001 - report all, not just the first
                failures.append(f"{f.stem}: {type(e).__name__}: {e}")
        self.assertEqual(failures, [], f"{len(failures)} passports failed the contract")
        # Not an assertion about correctness, but a guard against silently
        # regressing to guessed geometry for the whole catalogue.
        self.assertEqual(guessed, [], "these SKU fell back to guessed dimensions")


class TestReshapeToArtDirection(unittest.TestCase):
    """Geometry solved to the reference proportion, with the product kept upright.

    The targets are measurements, recorded in 01_input_raster/reference_analysis.md
    section 10; the solver is checked against the model that produced them, so a
    wrong constant and a wrong solve cannot cancel out.
    """

    def test_every_reshaped_carton_lands_on_its_template_target(self):
        for template_id, target in TARGET_SILHOUETTE_ASPECT.items():
            with self.subTest(template=template_id):
                base = orient_for_template((115.0, 55.0, 48.0), template_id)
                dims, reshaped = reshape_to_art_direction(base, template_id)
                self.assertTrue(reshaped, f"{template_id} refused a plain carton")
                self.assertAlmostEqual(
                    silhouette.visible_faces_aspect(dims, template_id), target, places=4)

    def test_the_target_is_matched_on_the_visible_faces_not_the_whole_box(self):
        # The distinction is worth a test of its own because getting it wrong is
        # silent: both quantities exist, both look plausible, and the wrong one
        # reports T1 as already correct when it is 14% out.
        base = orient_for_template((115.0, 55.0, 48.0), "T1")
        dims, _ = reshape_to_art_direction(base, "T1")
        target = TARGET_SILHOUETTE_ASPECT["T1"]
        self.assertAlmostEqual(silhouette.visible_faces_aspect(dims, "T1"), target,
                               places=4)
        self.assertNotAlmostEqual(silhouette.silhouette_aspect(dims, "T1"), target,
                                  places=2)

    def test_the_vial_becomes_the_squat_box_its_reference_shows(self):
        # 80x170x35 is a tall pen-shaped carton; T_VERT_VIAL_144.webp is a squat
        # 10-vial box, and the measurement says so at +77%. Solving lands on
        # 172x170x35 -- wider than tall as a box, still a portrait PICTURE at
        # 0.9224, which is why the flip guard reads the silhouette rather than
        # the edges.
        #
        # The ТЗ predicted 159x170 from an earlier measurement of the same
        # reference. That measurement is superseded, not reconciled: it paired a
        # reference's full silhouette against a model of our printed faces, which
        # are different quantities.
        base = orient_for_template((80.0, 170.0, 35.0), "T_VERT_VIAL")
        dims, reshaped = reshape_to_art_direction(base, "T_VERT_VIAL")
        self.assertTrue(reshaped)
        self.assertAlmostEqual(dims[1], 170.0, places=6, msg="height is the anchor")
        self.assertAlmostEqual(dims[2], 35.0, places=6, msg="depth is never solved")
        self.assertAlmostEqual(dims[0], 172.0, delta=2.0)
        self.assertLess(silhouette.visible_faces_aspect(dims, "T_VERT_VIAL"), 1.0,
                        "the picture must stay portrait")

    def test_the_anchor_is_the_larger_face_edge_and_the_depth(self):
        for dims_in, template_id in (((115.0, 55.0, 48.0), "T1"),
                                     ((140.0, 35.0, 25.0), "T3"),
                                     ((80.0, 170.0, 35.0), "T_VERT_VIAL")):
            with self.subTest(template=template_id):
                base = orient_for_template(dims_in, template_id)
                out, _ = reshape_to_art_direction(base, template_id)
                self.assertAlmostEqual(out[2], base[2], places=6, msg="depth moved")
                keep = 0 if base[0] >= base[1] else 1
                self.assertAlmostEqual(out[keep], base[keep], places=6,
                                       msg="the anchored edge moved")

    def test_a_carton_that_would_flip_keeps_its_passport_shape(self):
        # 55x100x55 and 45x80x45 are upright vials that routed to a landscape
        # template. Solving for T1's proportion would stretch them past three
        # times their width and stand the product on its side.
        for dims_in in ((55.0, 100.0, 55.0), (45.0, 80.0, 45.0)):
            with self.subTest(dims=dims_in):
                out, reshaped = reshape_to_art_direction(dims_in, "T1")
                self.assertFalse(reshaped)
                self.assertEqual(out, dims_in)

    def test_an_unknown_template_is_left_alone_rather_than_guessed(self):
        out, reshaped = reshape_to_art_direction((100.0, 50.0, 20.0), "T2")
        self.assertFalse(reshaped)
        self.assertEqual(out, (100.0, 50.0, 20.0))

    def test_reshaping_is_idempotent(self):
        base = orient_for_template((115.0, 55.0, 48.0), "T1")
        once, _ = reshape_to_art_direction(base, "T1")
        twice, _ = reshape_to_art_direction(once, "T1")
        for a, b in zip(once, twice):
            self.assertAlmostEqual(a, b, places=6)

    def test_scale_does_not_change_the_answer_but_shape_does(self):
        # The camera frames from the bounding sphere, so only proportion is
        # art-directable. A carton twice the size must reshape to twice the size.
        small, _ = reshape_to_art_direction((115.0, 55.0, 48.0), "T1")
        big, _ = reshape_to_art_direction((230.0, 110.0, 96.0), "T1")
        for a, b in zip(small, big):
            self.assertAlmostEqual(2.0 * a, b, places=4)

    def test_every_catalogue_carton_either_reshapes_or_says_why(self):
        if not PASSPORTS.exists():
            self.skipTest("passports are not in this checkout")
        from src.passport_generator import agent_1_router

        from src.design_group import is_design_sku

        refused = []
        skipped_for_design = []
        for f in sorted(PASSPORTS.glob("*.json")):
            passport = json.loads(f.read_text(encoding="utf-8"))
            template_id, _ = agent_1_router(passport)
            if template_id not in TARGET_SILHOUETTE_ASPECT:
                continue
            # A design-group carton is built to its REFERENCE's front face, not
            # to the template's silhouette target, so re-solving it here asks the
            # wrong question of it: three of the eleven are portrait against a
            # landscape template and would read as refusals. Counted rather than
            # skipped, so the exemption cannot quietly grow to cover a real one.
            if is_design_sku(passport.get("sku_id", "")):
                skipped_for_design.append(f.stem)
                continue
            carton = resolve_carton(passport, template_id)
            dims = (carton["width_mm"], carton["height_mm"], carton["depth_mm"])
            out, reshaped = reshape_to_art_direction(dims, template_id)
            if reshaped:
                self.assertAlmostEqual(
                    silhouette.visible_faces_aspect(out, template_id),
                    TARGET_SILHOUETTE_ASPECT[template_id], places=3,
                    msg=f"{f.stem} missed its target")
            else:
                refused.append((f.stem, template_id, dims))
        # The two known upright vials in a landscape template, and nothing else.
        # A third refusal is a new shape the rule has not been thought about for.
        self.assertLessEqual(
            len(refused), 2,
            f"{len(refused)} SKU refused reshaping, expected at most 2: {refused}")

        from src.design_group import TEMPLATE_SAMPLE
        self.assertEqual(
            len(skipped_for_design), len(TEMPLATE_SAMPLE),
            f"the art-direction path skipped {len(skipped_for_design)} SKU for "
            f"the design group, which holds {len(TEMPLATE_SAMPLE)}: "
            f"{sorted(skipped_for_design)}")


class TestManifestsOnDisk(unittest.TestCase):
    """What Stage 2 will actually open, not what build_manifest would produce.

    Those are the same thing only while the files are current, and a stale
    manifest is precisely the failure the version const exists to make loud. So
    these read the files.
    """

    MANIFESTS = PROJECT_ROOT / "04_passports" / "render_manifests"

    def setUp(self):
        if not self.MANIFESTS.exists():
            self.skipTest("render manifests have not been generated in this checkout")
        self.files = sorted(self.MANIFESTS.glob("*.json"))
        self.assertTrue(self.files, "manifest directory exists but is empty")

    def test_every_manifest_on_disk_satisfies_the_current_contract(self):
        # A partial migration is the worst of the three states: it renders, and
        # it renders some SKU one way and some another.
        stale = []
        for f in self.files:
            m = json.loads(f.read_text(encoding="utf-8"))
            if m.get("manifest_version") not in load_schema()['properties']['manifest_version']['enum']:
                stale.append(f"{f.stem}={m.get('manifest_version')}")
                continue
            validate_manifest(m)
        self.assertEqual(stale, [],
                         f"{len(stale)} manifests predate {MANIFEST_VERSION}; "
                         f"regenerate Stage 1 rather than migrate them by hand")

    def test_the_printed_dimensions_still_match_the_passport(self):
        # The reshape must not have leaked into the numbers that get printed.
        # Checked against the passport's own string rather than against
        # build_manifest, so a bug shared by both would not cancel out.
        if not PASSPORTS.exists():
            self.skipTest("passports are not in this checkout")
        checked = 0
        for f in self.files:
            m = json.loads(f.read_text(encoding="utf-8"))
            passport_file = PASSPORTS / f.name
            if not passport_file.exists():
                continue
            declared = (json.loads(passport_file.read_text(encoding="utf-8"))
                        .get("secondary_packaging") or {}).get("dimensions")
            numbers = re.findall(r"\d+(?:\.\d+)?", str(declared or ""))
            if len(numbers) != 3:
                continue
            real = m["carton"]["passport_dimensions"]
            with self.subTest(sku=f.stem):
                self.assertEqual(
                    sorted(float(n) for n in numbers),
                    sorted(real[k] for k in ("width_mm", "height_mm", "depth_mm")),
                    "the printed size is not the size the passport declares")
            checked += 1
        self.assertGreater(checked, 300, "too few SKU checked to mean anything")

    def test_every_reshaped_manifest_hits_its_template_target(self):
        declined = []
        for f in self.files:
            m = json.loads(f.read_text(encoding="utf-8"))
            carton, tid = m["carton"], m["template_id"]
            dims = (carton["width_mm"], carton["height_mm"], carton["depth_mm"])
            if carton["source"] == "art_direction":
                with self.subTest(sku=f.stem):
                    self.assertAlmostEqual(
                        silhouette.visible_faces_aspect(dims, tid),
                        TARGET_SILHOUETTE_ASPECT[tid], places=3)
            elif carton["source"] == "art_direction_declined_orientation":
                declined.append(f.stem)
                real = m["carton"]["passport_dimensions"]
                with self.subTest(sku=f.stem):
                    self.assertEqual(
                        dims, (real["width_mm"], real["height_mm"], real["depth_mm"]),
                        "a declined reshape must leave the geometry alone")
        # The two upright vials that routed to a landscape template. A third is a
        # shape nobody has looked at yet.
        self.assertEqual(len(declined), 2,
                         f"expected 2 declined reshapes, got {len(declined)}: {declined}")


class TestManifestPaths(unittest.TestCase):
    def test_path_uses_the_min_stem_convention(self):
        p = manifest_path_for("1-min", Path("/tmp/manifests"))
        self.assertEqual(p.name, "1-min.json")


if __name__ == "__main__":
    unittest.main()


class TestDesignChannel(unittest.TestCase):
    """Contract 1.4 — the measured design of a real carton reaches the renderer.

    Eleven SKU have reference photography, a measured face and a fitted spec.
    Before this the renderer could not see any of it: the manifest carried a
    palette and four strings, and every one of those eleven palettes is a
    category default rather than the carton's colour -- six of them share one
    pair while the cartons are olive, teal, navy, purple, pink, cyan and magenta.
    """

    MANIFESTS = PROJECT_ROOT / "04_passports" / "render_manifests"

    def _manifest(self, stem):
        return json.loads((self.MANIFESTS / f"{stem}.json").read_text(encoding="utf-8"))

    def test_every_sku_in_the_design_group_carries_its_design(self):
        from src.design_group import TEMPLATE_SAMPLE
        missing = []
        for folder, stem in sorted(TEMPLATE_SAMPLE.items()):
            path = self.MANIFESTS / f"{stem}.json"
            if not path.exists():
                missing.append(f"{stem} (no manifest)")
                continue
            if "design" not in self._manifest(stem):
                missing.append(f"{stem} ({folder})")
        self.assertFalse(
            missing,
            f"in the design group and rendering from the generic art direction: "
            f"{missing}. That produces a plausible carton in the wrong colours "
            f"and reports success, which is precisely what the group exists to "
            f"stop.")

    def test_the_built_face_matches_the_reference_it_is_copying(self):
        """The carton's front face, not its silhouette.

        These are different quantities and confusing them is a mistake this
        project has already made once, in the other direction: the silhouette
        target was compared against a whole-box model and read 12 points off.
        A design spec's coordinates are normalised to the FRONT FACE, so that is
        what has to match, or every outline in the spec lands somewhere else.
        """
        from src.design_group import TEMPLATE_SAMPLE
        for stem in sorted(set(TEMPLATE_SAMPLE.values())):
            m = self._manifest(stem)
            with self.subTest(stem=stem):
                carton, design = m["carton"], m["design"]
                built = carton["height_mm"] / carton["width_mm"]
                expected = design['face_aspect']
                self.assertAlmostEqual(
                    built, expected, places=3,
                    msg=f"{stem}: built face {built:.4f} against a reference "
                        f"measured at {design['face_aspect']:.4f}")
                self.assertEqual(carton["source"], "design_spec")

    def test_the_reference_proportion_does_not_inflate_the_carton(self):
        """Ativan's face is 1.540 -- portrait, against a landscape passport.

        Solving it by keeping the WIDTH would give a 115x177mm box: a carton far
        larger than the one the passport describes, to carry a proportion.
        Keeping the long edge and assigning it by orientation gives 75x115,
        which is the passport's own 115x55 carton stood up.

        This was Lexotanil's case at 2.026 until a re-acquisition replaced the
        group's photography and its new reference is landscape at 0.398. The
        property is the reshape's, not that carton's, so it moved to whichever
        SKU currently holds a portrait reference rather than being deleted with
        the photograph that first showed it.
        """
        m = self._manifest("135-min")
        carton = m["carton"]
        real = carton["passport_dimensions"]
        longest_built = max(carton["width_mm"], carton["height_mm"])
        longest_real = max(real["width_mm"], real["height_mm"])
        self.assertAlmostEqual(longest_built, longest_real, places=3)
        self.assertGreater(carton["height_mm"], carton["width_mm"],
                           "a portrait reference produced a landscape carton")

    def test_a_sku_outside_the_group_is_untouched(self):
        m = self._manifest("1-min")
        self.assertNotIn("design", m)
        self.assertIn(m["carton"]["source"],
                      ("art_direction", "art_direction_declined_orientation"))

    def test_74_manifest_carries_optional_carton_profile_without_version_bump(self):
        # Isolate the optional carton profile from separately versioned modes.
        from src.design_group import load_design
        from unittest.mock import patch
        import copy
        spec = copy.deepcopy(load_design('74-min'))
        for mark in spec.get('marks',[]):
            mark.pop('parts',None)
        with patch('src.render_manifest.load_design',return_value=spec):
            m = build_manifest(_passport("74-min"))

        self.assertEqual(m["manifest_version"], "1.10")
        self.assertEqual(
            m["design"]["carton_profile"]["profile_version"], "1.0")
        validate_manifest(m)

    def test_generic_build_has_no_design_or_carton_profile(self):
        m = build_manifest(_passport("1-min"))

        self.assertNotIn("design", m)

    def test_a_group_sku_whose_spec_is_missing_fails_loudly(self):
        from unittest.mock import patch
        from src import design_group
        with patch.dict(design_group.FOLDER_BY_STEM,
                        {"1-min": "99_NoSuchFolder"}, clear=False):
            with self.assertRaises(design_group.MissingDesignSpec):
                design_group.load_design("1-min")

    def test_the_design_block_survives_validation(self):
        from src.render_manifest import validate_manifest
        validate_manifest(self._manifest("59-min"))

    def test_a_manifest_from_the_previous_contract_is_rejected(self):
        from src.render_manifest import validate_manifest
        stale = self._manifest("59-min")
        stale["manifest_version"] = "1.4"
        with self.assertRaises(Exception):
            validate_manifest(stale)

    def test_a_type_row_without_a_cap_line_is_rejected(self):
        """1.5's whole point: `cap_frac` changed meaning, so a 1.4 row is not a
        1.5 row with a field missing -- it is the same number meaning something
        else, and reading it as a cap height oversizes the row by up to 38%.

        Reads `59-min` rather than `340-min`: Xanax Pfizer left the design group
        when its reference photograph was replaced by an unmeasurable frame, so
        its manifest no longer carries a design block at all. Cialis is one of
        the three folders the re-acquisition did not touch."""
        from src.render_manifest import validate_manifest
        stale = self._manifest("59-min")
        for row in stale["design"]["type_rows"].values():
            row.pop("cap_top_v", None)
        with self.assertRaises(Exception):
            validate_manifest(stale)

    def test_the_manifest_carries_the_type_rows_the_spec_measured(self):
        """Two scripts write one file, and one of them used to erase the other.

        `fit_design_spec` owns the fields, `measure_type_rows` owns `type_rows`,
        and both write `design_spec.json`. The fitter rewrote it wholesale, so
        re-running it deleted every measured row -- all eleven manifests came
        back with `"type_rows": {}` and every design carton silently returned to
        the generic grid. Nothing failed; it was found by diffing manifests.
        """
        import json as _json
        from src.design_group import TEMPLATES_DIR, TEMPLATE_SAMPLE
        for folder, stem in sorted(TEMPLATE_SAMPLE.items()):
            spec = _json.loads(
                (TEMPLATES_DIR / folder / "design_spec.json").read_text(encoding="utf-8"))
            with self.subTest(stem=stem):
                self.assertEqual(
                    self._manifest(stem)["design"].get("type_rows", {}),
                    spec.get("type_rows", {}),
                    f"{stem}: the manifest and the spec disagree about where "
                    f"this carton sets its type, so one of them was written "
                    f"over the other")

    # Parts that are neither off the face nor a block, i.e. admitted on the
    # strength of filling their own bounding box.
    def test_every_spec_field_is_a_component_a_person_called_print(self):
        """A spec carrying letter outlines prints the REFERENCE's words.

        Xanax shipped that way: "XANAX" clustered with the purple edge bar, its
        "XA" survived as one component covering 3.4% of the face, and the
        renderer built it as geometry beside our own brand -- the D-7 reader came
        back with "XAXa" off a carton printing "Xanax".

        WHAT THIS USED TO CHECK, AND WHY IT NO LONGER CAN. Until Phase B the
        fitter admitted a component on geometry -- it runs off the face, it reads
        as a block, or its pixels fill their own bounding box -- so this test
        restated that geometry and kept a list of measured exemptions. The rule
        has been replaced. `print_truth.json` now states, once per component and
        by hand, whether it is printed design, an object lying in front of the
        carton, a letterform, a logo, a photograph, or one surface counted twice;
        `fit()` emits the `print` components and nothing else.

        Re-asserting the old geometry would now flag ordinary design: fourteen
        parts across nine cartons float inside the face without being blocks --
        Modalert's red top rule, Lexotanil's two hexagons, Atarax's ring
        segments, Valium Brand's blue hexagon. Filling the exemption list with
        them would record that the admission rule changed while pretending it
        had not, which is worse than dropping the check.

        WHAT IS CHECKED INSTEAD, and it is stronger in the direction that
        matters: the spec must be exactly the `print` set, both ways round. A
        part with no matching component means the fitter drew something nobody
        classified; a `print` component with no part means it dropped something
        somebody did. Neither is reachable through the fitter's own predicate,
        because the truth file is written by a different program from a
        different source -- the photograph itself.

        WHAT IS GIVEN UP, stated rather than glossed: a person could still call
        a wordmark `print`, and no test can catch that. What catches it is
        `scripts/label_print.py --aid`, which tints every component by its class
        over the rectified face, so a wordmark labelled as design is visible at a
        glance. The guarantee moved from a proxy to a judgement, and the judgement
        is recorded per component with its area and its bounding box.
        """
        import json as _json
        from src.design_group import TEMPLATES_DIR, TEMPLATE_SAMPLE
        for folder in sorted(TEMPLATE_SAMPLE):
            root = TEMPLATES_DIR / folder
            spec = _json.loads((root / "design_spec.json").read_text(encoding="utf-8"))
            truth = _json.loads((root / "print_truth.json").read_text(encoding="utf-8"))
            printed = [c for c in truth["components"]
                       if c.get("class") == "print" and not c.get("vanished")]
            with self.subTest(folder=folder):
                # Matched on the recorded area and bounding box rather than by
                # re-running the segmentation: this reads what both sides wrote
                # down, so it cannot agree with the fitter by sharing its code.
                unmatched = []
                by_role = {}
                for c in printed:
                    by_role.setdefault(c["role"], []).append(c)
                for field in spec["fields"]:
                    if field.get("surface", "front") != "front":
                        continue
                    for part in field["parts"]:
                        us = [p[0] for p in part["outline"]]
                        vs = [p[1] for p in part["outline"]]
                        hit = None
                        for c in by_role.get(field["role"], []):
                            if abs(c["area_pct"] - part["area_pct"]) > 0.06:
                                continue
                            u0, v0, u1, v1 = c["bbox_uv"]
                            if (min(us) >= u0 - 0.02 and max(us) <= u1 + 0.02
                                    and min(vs) >= v0 - 0.02 and max(vs) <= v1 + 0.02):
                                hit = c
                                break
                        if hit is None:
                            unmatched.append((field["role"], part["area_pct"]))
                        else:
                            by_role[field["role"]].remove(hit)
                self.assertEqual(
                    unmatched, [],
                    f"{folder}: the spec draws a field no component was "
                    f"classified `print`. Either the fitter emitted something "
                    f"nobody looked at, or the partition moved under "
                    f"print_truth.json -- re-run label_print.py --init.")
                left = [(r, c["key"], c["area_pct"])
                        for r, cs in by_role.items() for c in cs]
                self.assertEqual(
                    left, [],
                    f"{folder}: a component classified `print` reached no field. "
                    f"The spec is missing design the photograph carries and a "
                    f"person confirmed.")


    def test_every_hole_the_spec_cuts_is_one_a_person_called_a_window(self):
        """Cutting the wrong hole prints another package's dosage on our carton.

        A hole in a printed field is board, and there are two reasons for that
        and only two: the carton leaves it unprinted, or the carton reverses its
        own TYPE out of the field. Both are the same pixels, so nothing in the
        segmentation separates them -- three instruments were tried and all
        three were measured failing, which is why `print_truth.json` carries a
        class per hole and `fit()` cuts `window` and nothing else.

        The stake is the invariant this project holds hardest. `59-min` is a
        20 mg Cialis whose reference photograph is a 10 mg pack; `344-min` is
        Modafinil Generic whose photograph is Modalert 200; `404-min`'s 72 holes
        spell "Ritalin 10 mg Tabletten" and "50 Tabletten/N2". Cut those and the
        board shows through our field in the shape of the other package's brand
        and dose -- the same act as printing a plausible LOT, which the driver
        already refuses.

        Checked both ways round and off the RECORDED numbers, so it shares no
        code with the fitter: a ring the truth has no window for means something
        was cut that nobody looked at, and a window with no ring means a real
        hole was filled in.
        """
        import json as _json
        from src.design_group import (TEMPLATES_DIR, TEMPLATE_SAMPLE,
                                      FOLDER_BY_STEM)
        from src.marks_decision import load as _load_decision
        _DECISION = _load_decision()
        STEM_BY_FOLDER = {f: s for s, f in FOLDER_BY_STEM.items()}
        cut = 0
        for folder in sorted(TEMPLATE_SAMPLE):
            root = TEMPLATES_DIR / folder
            spec = _json.loads((root / "design_spec.json").read_text(encoding="utf-8"))
            truth = _json.loads((root / "print_truth.json").read_text(encoding="utf-8"))
            # Contract 1.10 widens WHICH holes may be cut and not by how much:
            # a `mark` hole the owner approved BY NAME in MARKS_DECISION.md is
            # cut too, and nothing else is. The decision is read here rather
            # than a class list being relaxed, so the guard still fails on any
            # hole no person allowed -- which is the whole point of it.
            stem = STEM_BY_FOLDER.get(folder)
            approved = {k for s, k in _DECISION.holes if s == stem}
            windows = [h for h in truth.get("holes", [])
                       if not h.get("vanished")
                       and (h.get("class") == "window" or h.get("key") in approved)]
            with self.subTest(folder=folder):
                unmatched = []
                for field in spec["fields"]:
                    for part in field["parts"]:
                        for ring in part.get("holes") or []:
                            us = [q[0] for q in ring]
                            vs = [q[1] for q in ring]
                            hit = None
                            for hole in windows:
                                u0, v0, u1, v1 = hole["bbox_uv"]
                                if (min(us) >= u0 - 0.01 and max(us) <= u1 + 0.01
                                        and min(vs) >= v0 - 0.01
                                        and max(vs) <= v1 + 0.01):
                                    hit = hole
                                    break
                            if hit is None:
                                unmatched.append((field["role"], round(min(us), 3),
                                                  round(min(vs), 3)))
                            else:
                                windows.remove(hit)
                                cut += 1
                self.assertEqual(
                    unmatched, [],
                    f"{folder}: the spec cuts a hole that is neither a window "
                    f"nor a mark the owner approved by name. If it is the "
                    f"reference's own lettering, our field will show board in "
                    f"the shape of another package's words.")
                self.assertEqual(
                    [h["key"] for h in windows], [],
                    f"{folder}: a hole a person called a window reached no ring. "
                    f"The spec fills a region the carton leaves open -- which is "
                    f"how one Adderall field came to enclose 9.07 times its ink.")
        self.assertGreaterEqual(
            cut, 5, "no spec cuts a hole, so this test asserts nothing")

    def test_a_hole_is_only_ever_asked_about_inside_a_printed_component(self):
        """The truth enumerates holes of `print` components and of nothing else.

        A hole in a component the label already dropped is not a question anyone
        has to answer: the component is not in the spec, so neither is its
        interior. Keeping the two populations aligned this way is what lets a
        hole be named off its component's own key rather than by a second
        enumeration that could drift from the first.
        """
        import json as _json
        from src.design_group import TEMPLATES_DIR, TEMPLATE_SAMPLE
        for folder in sorted(TEMPLATE_SAMPLE):
            truth = _json.loads(
                (TEMPLATES_DIR / folder / "print_truth.json").read_text(encoding="utf-8"))
            printed = {c["key"] for c in truth["components"]
                       if c.get("class") == "print" and not c.get("vanished")}
            stray = sorted({h["of"] for h in truth.get("holes", [])
                            if not h.get("vanished")} - printed)
            with self.subTest(folder=folder):
                self.assertEqual(
                    stray, [],
                    f"{folder}: holes are enumerated inside components that are "
                    f"not `print`. Re-run label_print.py --init.")


class TestAnOutlineIsARegion(unittest.TestCase):
    """A self-intersecting ring means different things under different fill rules.

    `rasterise()` fills with PIL's even-odd scanline and is what every spec's
    `verification.pixel_agreement` was measured against; the driver hands the
    same points to a Blender curve, which tessellates them. On `340-min` they
    disagreed by 1.33% of the face -- its brand outline has eight points, one of
    which sits far below the other seven, and Blender filled the triangle back
    to the panel. Our packshot carried a magenta wedge the real carton does not
    have, and the field read 0.752 at 100.0% recall and 75.2% precision.

    Eight parts across six of the eleven cartons were tangled this way.
    """

    MANIFESTS = PROJECT_ROOT / "04_passports" / "render_manifests"

    def _design_stems(self):
        from src.design_group import FOLDER_BY_STEM
        return sorted(FOLDER_BY_STEM, key=lambda s: int(s.split("-")[0]))

    def test_no_manifest_on_disk_carries_a_ring_that_crosses_itself(self):
        from src.design_group import ring_crossings
        seen = 0
        for stem in self._design_stems():
            path = self.MANIFESTS / f"{stem}.json"
            if not path.exists():
                continue
            seen += 1
            design = json.loads(path.read_text(encoding="utf-8")).get("design") or {}
            for field in design.get("fields") or []:
                for i, part in enumerate(field.get("parts") or []):
                    with self.subTest(sku=stem, field=field.get("role"), part=i):
                        self.assertEqual(
                            ring_crossings([(float(p[0]), float(p[1]))
                                            for p in part["outline"]]), [])
        self.assertTrue(seen, "no design manifests on disk to check")

    def test_the_contract_rejects_one(self):
        """On write and on load, by name -- not left to the renderer to find."""
        stem = self._design_stems()[0]
        manifest = json.loads(
            (self.MANIFESTS / f"{stem}.json").read_text(encoding="utf-8"))
        part = manifest["design"]["fields"][0]["parts"][0]
        part["outline"] = [[0.1, 0.1], [0.9, 0.9], [0.9, 0.1], [0.1, 0.9]]
        with self.assertRaises(ValueError) as ctx:
            validate_manifest(manifest)
        self.assertIn("crosses itself", str(ctx.exception))

    def test_the_contract_rejects_a_tangled_hole_and_says_which(self):
        """Contract 1.8 checks the holes on the same footing as the outline.

        A part is its outline minus its holes, so a hole that crosses itself is
        a tangled region boundary and reaches the render the same way -- the
        driver hands both to Blender as cyclic splines of one curve, where the
        tessellation and PIL's even-odd scanline disagree exactly as they did on
        `340-min`.
        """
        stem = self._design_stems()[0]
        manifest = json.loads(
            (self.MANIFESTS / f"{stem}.json").read_text(encoding="utf-8"))
        part = manifest["design"]["fields"][0]["parts"][0]
        part["holes"] = [[[0.2, 0.2], [0.4, 0.4], [0.4, 0.2], [0.2, 0.4]]]
        with self.assertRaises(ValueError) as ctx:
            validate_manifest(manifest)
        self.assertIn("hole 0", str(ctx.exception))
        self.assertIn("crosses itself", str(ctx.exception))

    def test_a_part_that_does_not_say_whether_it_has_holes_is_refused(self):
        """`holes` is required and may be empty, and the difference matters.

        A 1.7 part carries no such key. Read as 1.8 it is not a part with no
        holes, it is a part whose holes are unknown -- and filling them in
        silence is the packshot this group had been rendering: Adderall's brand
        enclosing 9.07 times its own ink, 53.48% of a face it inks 5.90% of.
        """
        from jsonschema import ValidationError
        stem = self._design_stems()[0]
        manifest = json.loads(
            (self.MANIFESTS / f"{stem}.json").read_text(encoding="utf-8"))
        manifest["design"]["fields"][0]["parts"][0].pop("holes")
        with self.assertRaises(ValidationError):
            validate_manifest(manifest)

    def test_a_part_that_does_not_say_what_colour_it_is_is_refused(self):
        """Contract 1.9, on the same footing as `holes` above.

        A 1.8 part carries no `fill`. Read as 1.9 it is not a part painted its
        field's colour, it is a part whose colour is unknown -- and painting it
        the field's in silence is what 33 of the group's 75 parts should not be:
        `152_Artvigil`'s `brand#1` is declared `#E05506` and is `#2D3336` in the
        photograph, over 6.47% of the face.
        """
        from jsonschema import ValidationError
        stem = self._design_stems()[0]
        manifest = json.loads(
            (self.MANIFESTS / f"{stem}.json").read_text(encoding="utf-8"))
        manifest["design"]["fields"][0]["parts"][0].pop("fill")
        with self.assertRaises(ValidationError):
            validate_manifest(manifest)

    def test_every_design_part_states_its_own_colour(self):
        """And the shipped manifests carry it, which is the other half."""
        seen = own = 0
        for stem in self._design_stems():
            manifest = json.loads(
                (self.MANIFESTS / f"{stem}.json").read_text(encoding="utf-8"))
            for field in (manifest.get("design") or {}).get("fields") or []:
                for i, part in enumerate(field.get("parts") or []):
                    seen += 1
                    self.assertIn(
                        "fill", part,
                        f"{stem} {field.get('role')}#{i} carries no fill")
                    if part["fill"] != field["fill"]:
                        own += 1
        self.assertGreater(seen, 0, "no design parts were checked at all")
        self.assertGreater(
            own, 0,
            "not one part in the catalogue differs from its field's colour. "
            "Contract 1.9 exists because 33 of the group's 75 do; a manifest "
            "set where none does means the producer has been switched off.")

    # The exact outline that showed the repair was scoring itself on the wrong
    # quantity. Ritalin's `highlight#1`, simplified at a 0.001 face width: a
    # 22-vertex ring crossing itself six times, its two long edges running the
    # full width of the face a thousandth apart. Kept here rather than
    # regenerated because it is evidence, and the tolerance it came from is not
    # the committed one.
    RITALIN_TANGLE = [
        [0.0, 0.5405], [0.0036, 0.9628], [0.0055, 0.9672], [0.0082, 0.9628],
        [0.01, 0.965], [0.0109, 0.9737], [0.0082, 0.9759], [0.0073, 0.9825],
        [0.0109, 0.9912], [0.0682, 0.9956], [0.0782, 0.9912], [0.1464, 0.9912],
        [0.1645, 0.9978], [0.1809, 0.9934], [0.1873, 0.9978], [0.1973, 0.9934],
        [0.2073, 0.9978], [0.2191, 0.9978], [0.2218, 0.9934], [0.5336, 0.9978],
        [0.0, 0.9978], [0.0, 0.5427],
    ]

    def test_the_index_finds_exactly_what_testing_every_pair_finds(self):
        """`ring_crossings` is indexed by a grid; an index that misses a crossing
        would let a tangled ring reach the driver as a region.

        Checked against the full pairwise scan on every ring the group carries
        AND on 300 deterministic random rings, because the group's rings are all
        traced round printed shapes and share a shape of their own.
        """
        import random
        from src.design_group import _crosses, ring_crossings, spec_path

        def brute(poly):
            n, out = len(poly), []
            for i in range(n):
                for j in range(i + 1, n):
                    if (j + 1) % n == i or (i + 1) % n == j:
                        continue
                    if _crosses(poly[i], poly[(i + 1) % n],
                                poly[j], poly[(j + 1) % n]):
                        out.append((i, j))
            return out

        rings = [[(float(a), float(b)) for a, b in self.RITALIN_TANGLE]]
        for stem in self._design_stems():
            path = spec_path(stem)
            if path is None or not path.exists():
                continue
            spec = json.loads(path.read_text(encoding="utf-8"))
            for field in spec.get("fields") or []:
                for part in field.get("parts") or []:
                    o = [(float(a), float(b)) for a, b in part["outline"]]
                    if len(o) >= 4:
                        rings.append(o)
        rng = random.Random(7)
        for _ in range(300):
            rings.append([(rng.random(), rng.random())
                          for _ in range(rng.randint(4, 40))])
        for n, ring in enumerate(rings):
            with self.subTest(ring=n, verts=len(ring)):
                self.assertEqual(ring_crossings(ring), brute(ring))

    def test_a_repair_that_cannot_keep_the_region_raises(self):
        """The repair used to choose by the SHOELACE area, which on a ring that
        crosses itself is a signed cancellation and not what an even-odd fill
        covers. On this outline it dropped two vertices and turned 0.36% of the
        face into 11.87% -- it did not lose the region, it invented one
        thirty-three times larger and put it on the carton. Nothing failed.

        Now it either keeps the region or says it cannot.
        """
        from src.design_group import RingRepairFailed, simple_ring
        with self.assertRaises(RingRepairFailed) as ctx:
            simple_ring(self.RITALIN_TANGLE)
        self.assertIn("kept only", str(ctx.exception))

    def test_the_objective_is_the_fill_and_not_the_shoelace_sum(self):
        """A figure eight is the case that separates them: its lobes cancel in
        the shoelace sum and both are covered by an even-odd fill. A repair
        judged on the first is judged on a number unrelated to what is painted.
        """
        try:
            import numpy as np
            from PIL import Image, ImageDraw
        except ImportError as e:  # pragma: no cover - environment, not logic
            self.skipTest(f"Pillow/numpy unavailable: {e}")
        eight = [(0.1, 0.1), (0.5, 0.1), (0.1, 0.9), (0.5, 0.9)]
        n = len(eight)
        shoelace = abs(sum(eight[i][0] * eight[(i + 1) % n][1]
                           - eight[(i + 1) % n][0] * eight[i][1]
                           for i in range(n))) / 2

        def fill(poly, size=400):
            im = Image.new("L", (size, size), 0)
            ImageDraw.Draw(im).polygon(
                [(u * size, v * size) for u, v in poly], fill=255)
            return (np.asarray(im) > 0)

        covered = float(fill(eight).mean())
        self.assertLess(shoelace, 1e-9,
                        "this ring no longer cancels; pick another figure eight")
        self.assertGreater(covered, 0.05,
                           "an even-odd fill covers both lobes, so the two "
                           "measures must disagree for this test to mean anything")

    def test_the_repair_keeps_the_region_that_was_verified(self):
        """Dropping vertices must not redraw the field. Measured against the
        original's even-odd raster, the eight repaired rings score 0.972-0.9999."""
        try:
            import numpy as np
            from PIL import Image, ImageDraw
        except ImportError as e:  # pragma: no cover - environment, not logic
            self.skipTest(f"Pillow/numpy unavailable: {e}")
        from src.design_group import ring_crossings, simple_ring, spec_path

        def fill(poly, n=700):
            im = Image.new("L", (n, n), 0)
            ImageDraw.Draw(im).polygon([(u * n, v * n) for u, v in poly], fill=255)
            return np.asarray(im) > 0

        checked = 0
        for stem in self._design_stems():
            path = spec_path(stem)
            if path is None or not path.exists():
                continue
            # The spec on disk is the raw trace; load_design repairs at load, so
            # this reads the file directly to see what was traced.
            spec = json.loads(path.read_text(encoding="utf-8"))
            for field in spec.get("fields") or []:
                for part in field.get("parts") or []:
                    raw = [(float(p[0]), float(p[1])) for p in part["outline"]]
                    if len(raw) < 4 or not ring_crossings(raw):
                        continue
                    checked += 1
                    a, b = fill(raw), fill(simple_ring(raw))
                    with self.subTest(sku=stem, field=field.get("role")):
                        self.assertGreater((a & b).sum() / max((a | b).sum(), 1), 0.97)
        if not checked:
            self.skipTest("no tangled outlines in this checkout to repair")


class TestWhatIsPrintedIsNotWhatKeysIt(unittest.TestCase):
    """Contract 1.6 — `sku_id` identifies the row, `product_code` goes on the pack.

    `SKU.csv`'s first column is named `picture` and holds the source image's
    filename. It became the SSOT registry's key, then the passport's `sku_id`,
    then the manifest's -- and the side panel prints the identifier under the
    barcode and encodes it into the Code 128. So all 391 cartons carried `.jpg`
    on them, as a scannable product code.

    No single step was wrong. `sku_id` really is the catalogue's key and the
    barcode really should carry the SKU. The two questions had never been
    separated, so the answer to one was used for the other.
    """

    MANIFESTS = PROJECT_ROOT / "04_passports" / "render_manifests"
    FILENAME = re.compile(r"(?i)\.(jpg|jpeg|png|webp|json)$")

    def _manifests(self):
        return sorted(self.MANIFESTS.glob("*.json"))

    def test_no_manifest_carries_a_product_code_that_is_a_filename(self):
        seen = 0
        for path in self._manifests():
            m = json.loads(path.read_text(encoding="utf-8"))
            seen += 1
            with self.subTest(sku=path.stem):
                self.assertNotRegex(m["product_code"], self.FILENAME)
        self.assertTrue(seen, "no manifests on disk to check")

    def test_it_is_the_key_with_the_extension_removed(self):
        from src.utils import product_code
        for path in self._manifests()[:40]:
            m = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(sku=path.stem):
                self.assertEqual(m["product_code"], product_code(m["sku_id"]))

    def test_the_catalogue_is_still_keyed_by_the_filename(self):
        """The other half of the separation, asserted so a later 'tidy-up' of
        `sku_id` cannot silently break every registry lookup."""
        m = json.loads(self._manifests()[0].read_text(encoding="utf-8"))
        self.assertRegex(m["sku_id"], self.FILENAME)

    def test_the_contract_rejects_a_printed_filename(self):
        m = json.loads(self._manifests()[0].read_text(encoding="utf-8"))
        m["product_code"] = m["sku_id"]
        with self.assertRaises(Exception):
            validate_manifest(m)

    def test_a_manifest_without_one_is_rejected(self):
        m = json.loads(self._manifests()[0].read_text(encoding="utf-8"))
        del m["product_code"]
        with self.assertRaises(Exception):
            validate_manifest(m)

    def test_the_code_is_encodable_as_code_128_subset_b(self):
        """It is put into a scannable symbol, so every character must be in the
        subset the encoder implements."""
        for path in self._manifests():
            code = json.loads(path.read_text(encoding="utf-8"))["product_code"]
            with self.subTest(sku=path.stem):
                self.assertTrue(all(32 <= ord(c) <= 126 for c in code), code)
