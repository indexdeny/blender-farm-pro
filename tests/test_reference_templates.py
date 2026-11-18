"""The reference-template folders must describe their own contents truthfully.

`metadata.json` is declared a machine-readable contract for downstream agents --
the Blender driver, the SVG generator, the UV builder all read it rather than the
photographs. Its `quality_gate` block reports `"status": "complete"`.

Both benchmark folders shipped with a `reference_images` list naming
`raw_01_angle_left.png`, `raw_02_front.png` and `raw_03_angle_right.png`, and
neither folder contained a single one of those files -- the intersection with
what was on disk was empty. A consumer following that contract would have found
nothing and had no way to tell whether the reference set was missing or the
manifest was wrong.

That is the same defect the verification barrier exists to remove, one layer up:
a record asserting something nothing checked. These tests check it.
"""
import json
import unittest
from pathlib import Path

from src.utils import PROJECT_ROOT

TEMPLATES_DIR = PROJECT_ROOT / "Reference Templates"
IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}

# The owner's cap: no template folder may hoard more than this. Recorded here
# rather than only in the ТЗ, so exceeding it fails rather than merely
# contradicting a document.
MAX_IMAGES_PER_TEMPLATE = 7


def _template_dirs():
    if not TEMPLATES_DIR.exists():
        return []
    return sorted(d for d in TEMPLATES_DIR.iterdir() if d.is_dir())


def _images_in(directory):
    return sorted(p.name for p in directory.iterdir()
                  if p.suffix.lower() in IMAGE_SUFFIXES)


class TestMetadataMatchesDisk(unittest.TestCase):
    def test_at_least_one_template_carries_metadata(self):
        # Without this the suite below passes vacuously the day the folders are
        # emptied, reporting success having checked nothing.
        #
        # But "the reference material is not in this checkout" and "it is here
        # and unchecked" are different states and must not share an outcome:
        # `Reference Templates/` is currently untracked, so a clean clone has no
        # such directory at all. Absent -> skip; present but silent -> fail.
        if not TEMPLATES_DIR.exists():
            self.skipTest(
                f"{TEMPLATES_DIR.name}/ is not in this checkout -- it is "
                f"untracked, so a clean clone has none. Nothing to verify here; "
                f"that is not the same as verifying nothing.")
        with_metadata = [d for d in _template_dirs() if (d / "metadata.json").exists()]
        self.assertTrue(with_metadata,
                        f"{TEMPLATES_DIR.name}/ exists with "
                        f"{len(_template_dirs())} folders but not one has a "
                        f"metadata.json; the checks below would inspect nothing")

    def test_every_listed_reference_image_exists(self):
        for d in _template_dirs():
            meta = d / "metadata.json"
            if not meta.exists():
                continue
            # The photographs are gitignored while the metadata is tracked, so a
            # clean clone has the folder and its contract but none of its
            # pictures. A folder with no images at all is that state, not a
            # false manifest. A folder with SOME images and a listed one absent
            # is the defect this guards.
            if not _images_in(d):
                continue
            with self.subTest(template=d.name):
                listed = json.loads(meta.read_text(encoding="utf-8")).get(
                    "reference_images", [])
                missing = [f for f in listed if not (d / f).exists()]
                self.assertEqual(
                    missing, [],
                    f"{d.name}/metadata.json lists files that are not on disk: "
                    f"{missing}. A downstream agent reading this contract would "
                    f"find nothing and could not tell which side is wrong.")

    def test_every_image_on_disk_is_listed(self):
        for d in _template_dirs():
            meta = d / "metadata.json"
            if not meta.exists():
                continue
            with self.subTest(template=d.name):
                listed = set(json.loads(meta.read_text(encoding="utf-8")).get(
                    "reference_images", []))
                unlisted = [f for f in _images_in(d) if f not in listed]
                self.assertEqual(
                    unlisted, [],
                    f"{d.name} holds images its metadata does not mention: "
                    f"{unlisted}. An unlisted reference is invisible to every "
                    f"consumer that reads the contract rather than the folder.")


class TestImageBudget(unittest.TestCase):
    def test_no_template_exceeds_the_image_cap(self):
        for d in _template_dirs():
            with self.subTest(template=d.name):
                images = _images_in(d)
                self.assertLessEqual(
                    len(images), MAX_IMAGES_PER_TEMPLATE,
                    f"{d.name} holds {len(images)} images, over the cap of "
                    f"{MAX_IMAGES_PER_TEMPLATE}: {images}")


class TestReferenceScope(unittest.TestCase):
    """The owner's scope is 28 active designs plus one gated candidate."""

    def test_reference_scope_is_28_active_plus_tramadol_candidate(self):
        if not TEMPLATES_DIR.exists():
            self.skipTest(f"{TEMPLATES_DIR.name}/ is not in this checkout")
        from src.design_group import TEMPLATE_SAMPLE

        folders = {
            path.name for path in TEMPLATES_DIR.iterdir()
            if path.is_dir() and path.name.split("_", 1)[0].isdigit()
        }
        self.assertEqual(len(folders), 29)
        self.assertEqual(set(TEMPLATE_SAMPLE), folders - {"107_Tramadol"})

    def test_every_reference_scope_stem_has_passport_and_manifest(self):
        if not TEMPLATES_DIR.exists():
            self.skipTest(f"{TEMPLATES_DIR.name}/ is not in this checkout")

        root = TEMPLATES_DIR.parent
        stems = {
            f"{path.name.split('_', 1)[0]}-min"
            for path in TEMPLATES_DIR.iterdir()
            if path.is_dir() and path.name.split("_", 1)[0].isdigit()
        }
        missing = []
        for stem in sorted(stems, key=lambda value: int(value.split("-", 1)[0])):
            for kind, relative in (
                    ("passport", f"04_passports/passports_json/{stem}.json"),
                    ("manifest", f"04_passports/render_manifests/{stem}.json")):
                if not (root / relative).is_file():
                    missing.append((stem, kind, relative))
        self.assertEqual(missing, [])


class TestNoDuplicateImages(unittest.TestCase):
    """Two files of the same picture in different formats are one reference, not
    two, and both count against the cap. The Kamagra benchmark shipped with two
    such pairs -- `.webp` copies of its `.png` files, pixel-identical.
    """

    def test_no_two_images_in_a_folder_share_pixels(self):
        try:
            import numpy as np
            from PIL import Image
        except ImportError as e:  # pragma: no cover - environment, not logic
            self.skipTest(f"Pillow/numpy unavailable: {e}")
        import hashlib

        for d in _template_dirs():
            images = _images_in(d)
            if len(images) < 2:
                continue
            with self.subTest(template=d.name):
                seen = {}
                for name in images:
                    with Image.open(d / name) as im:
                        digest = hashlib.sha256(
                            np.asarray(im.convert("RGB")).tobytes()).hexdigest()
                    self.assertNotIn(
                        digest, seen,
                        f"{d.name}: {name} and {seen.get(digest)} are the same "
                        f"picture in different files")
                    seen[digest] = name


class TestEveryPhotographedFolderIsInTheBarrier(unittest.TestCase):
    """A folder with reference photography must name the SKU it documents.

    The OCR barrier over the template sample
    (tests/test_render_qa.py::TestOCRBarrierOverTheTemplateSample) is defined by
    `TEMPLATE_SAMPLE` in scripts/make_ocr_fixtures.py -- a hand-resolved map,
    because folder names do not identify a SKU on their own: `15_T1_Xanax` and
    `24_T1_Xanax_Pfizer` are two catalogue entries whose names contain each
    other. A hand-resolved map is exactly the kind that falls behind the folders
    it describes, and nothing would say so: acquiring a reference for a twelfth
    product and leaving it unmapped simply means the barrier keeps covering
    eleven while the repository looks like it covers twelve.

    This test was written after the map was first built with a folder in it that
    holds no photograph at all.
    """

    #: Photographed, deliberately unmapped, and named here so the omission is
    #: a statement rather than a gap. `21_Valium_Brand` and `24_Xanax_Pfizer`
    #: needed no entry because their folders left the disk with them; these
    #: keep their photography, so nothing else records that they are out.
    UNMEASURABLE = {
        # 107 components in the highlight cluster, largest holding 60% of the
        # mask; the boundary walk crosses itself 136 times before any
        # simplification, and the even-odd fill of that ring is three disjoint
        # pieces (74/14/10%). No simple ring can represent it -- see the
        # reason recorded beside TEMPLATE_SAMPLE in src/design_group.py.
        "107_Tramadol",
    }

    def test_no_photographed_folder_is_missing_from_the_sample(self):
        if not TEMPLATES_DIR.exists():
            self.skipTest(f"{TEMPLATES_DIR.name}/ is not in this checkout")
        from scripts.make_ocr_fixtures import TEMPLATE_SAMPLE

        photographed = {d.name for d in _template_dirs() if _images_in(d)}
        unmapped = sorted(photographed - set(TEMPLATE_SAMPLE)
                          - self.UNMEASURABLE)
        self.assertFalse(
            unmapped,
            f"these folders hold reference photography but name no SKU: "
            f"{unmapped}. Add them to TEMPLATE_SAMPLE and rebuild the fixtures, "
            f"or name them in UNMEASURABLE with the measurement that puts them "
            f"there; otherwise the barrier silently keeps its old coverage.")

    def test_the_sample_names_no_folder_without_a_photograph(self):
        if not TEMPLATES_DIR.exists():
            self.skipTest(f"{TEMPLATES_DIR.name}/ is not in this checkout")
        from scripts.make_ocr_fixtures import TEMPLATE_SAMPLE

        photographed = {d.name for d in _template_dirs() if _images_in(d)}
        on_disk = {d.name for d in _template_dirs()}
        if not photographed:
            self.skipTest("NOT VERIFIED: optional reference photography dataset is not installed")
        phantom = sorted(set(TEMPLATE_SAMPLE) - photographed)
        self.assertFalse(
            phantom,
            f"the sample names folders with no reference photograph: {phantom} "
            f"({[p for p in phantom if p not in on_disk]} are not on disk at "
            f"all). A reference folder with no image is a reference to nothing.")


class TestARowBoxedAsItsBlock(unittest.TestCase):
    """`ink_within` recovers the glyphs when the reader returns the shape.

    Tesseract binarises per region, so a colour block with type reversed out of
    it is one blob and the word box comes back as the BLOCK. On our own Cialis
    render "20mg" was returned at exactly the block's outline, v 0.2948-0.4292
    against glyphs at 0.3165-0.4133, which read back as a row 38% oversized and
    0.02 high -- the worst type figures in the group, on a carton the scene dump
    says is built exactly right.

    Synthetic rather than fixture-driven: the property is about a filled shape
    with lighter marks inside it, and stating it in twenty lines of pixels is
    clearer than pointing at a render.
    """

    def _face(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (200, 100), "#E0DCD0")
        d = ImageDraw.Draw(img)
        d.rectangle([40, 20, 159, 79], fill="#204020")      # the block
        d.rectangle([60, 35, 139, 64], fill="#FFFFFF")      # the reversed type
        return img

    def _block_outline(self):
        return [[40 / 200, 20 / 100], [160 / 200, 20 / 100],
                [160 / 200, 80 / 100], [40 / 200, 80 / 100]]

    def test_a_box_around_the_block_is_pulled_back_to_the_glyphs(self):
        from scripts.measure_type_rows import ink_within
        row = {"text": "20mg", "u0": 40 / 200, "u1": 160 / 200,
               "v0": 20 / 100, "v1": 80 / 100, "cap_frac": 0.6,
               "words": [{"text": "20mg", "u0": 40 / 200, "u1": 160 / 200,
                          "v0": 20 / 100, "v1": 80 / 100}]}
        got = ink_within(self._face(), row, [("#204020", self._block_outline(), [])])
        self.assertAlmostEqual(got["u0"], 0.300, delta=0.02)
        self.assertAlmostEqual(got["u1"], 0.700, delta=0.02)
        self.assertAlmostEqual(got["v0"], 0.350, delta=0.02)
        self.assertAlmostEqual(got["v1"], 0.650, delta=0.02)

    def test_the_words_come_back_with_it(self):
        """Everything downstream rebuilds a row from its words.

        `_unclaimed` does it before scoring and `narrow_to_string` inside it, so
        leaving the reader's word boxes in place quietly restores the block's own
        rectangle and the correction never reaches the figures. It did exactly
        that on the first attempt.
        """
        from scripts.measure_type_rows import ink_within
        row = {"text": "20mg", "u0": 40 / 200, "u1": 160 / 200,
               "v0": 20 / 100, "v1": 80 / 100, "cap_frac": 0.6,
               "words": [{"text": "20mg", "u0": 40 / 200, "u1": 160 / 200,
                          "v0": 20 / 100, "v1": 80 / 100}]}
        got = ink_within(self._face(), row, [("#204020", self._block_outline(), [])])
        self.assertEqual(len(got["words"]), 1)
        for key in ("u0", "u1", "v0", "v1"):
            self.assertEqual(got["words"][0][key], got[key])

    def test_a_row_that_is_not_a_block_is_untouched(self):
        from scripts.measure_type_rows import ink_within
        row = {"text": "Tadalafil", "u0": 0.30, "u1": 0.70,
               "v0": 0.35, "v1": 0.65, "cap_frac": 0.30, "words": []}
        self.assertEqual(
            ink_within(self._face(), row, [("#204020", self._block_outline(), [])]),
            row, "a row whose box is not the shape must be returned unchanged")


if __name__ == "__main__":
    unittest.main()


class TestAPartIsItsOutlineMinusItsHoles(unittest.TestCase):
    """Contract 1.8, on the measuring side.

    `part_region` is the one implementation of what a part covers, and every
    figure the design group is judged by reads it: the spec's own raster, the
    QA target `design_qa` compares a render against, and `design_coverage`'s
    agreement. A second idea of it is how this project has twice been bitten,
    and a hole existing in one of them and not the others is the same defect
    wearing a new coat.

    Synthetic, for the reason the block test above is: the property is about a
    shape with a window in it, and twenty lines of pixels state it more clearly
    than a fixture does.
    """

    SQUARE = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]
    WINDOW = [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]]

    def _covered(self, part):
        import numpy as np
        from scripts.fit_design_spec import part_region
        return np.asarray(part_region(part, 100, 100))

    def test_a_hole_is_removed_from_what_the_part_covers(self):
        solid = self._covered({"outline": self.SQUARE, "holes": []})
        holed = self._covered({"outline": self.SQUARE, "holes": [self.WINDOW]})
        # PIL fills the boundary, so a 0.2-0.8 square on a 100px grid is 61x61
        # and its 0.4-0.6 window 21x21. The point of stating both is that the
        # difference is the window and nothing else.
        self.assertAlmostEqual(solid.mean(), 0.3721, delta=0.002)
        self.assertAlmostEqual(holed.mean(), 0.3721 - 0.0441, delta=0.002)
        self.assertFalse(holed[50, 50], "the middle of the window is still covered")
        self.assertTrue(holed[25, 50], "the part outside its window was dropped")

    def test_a_missing_or_empty_holes_key_covers_the_whole_outline(self):
        """The key is required by the contract; the raster must not guess at it.

        Refusing here as well would put the contract's enforcement in two places
        and this one cannot say which manifest it is reading. The schema rejects
        the missing key on write and on load, and the driver raises SystemExit
        rather than build the part -- that is where it is caught.
        """
        for holes in ([], None):
            part = {"outline": self.SQUARE}
            if holes is not None:
                part["holes"] = holes
            self.assertAlmostEqual(self._covered(part).mean(), 0.3721, delta=0.002)

    def test_ink_inside_a_hole_is_not_the_shapes_own(self):
        """`ink_within` measures the glyphs inside a filled shape, so the shape
        it measures inside has to be the region, not the ring."""
        from PIL import Image, ImageDraw
        from scripts.measure_type_rows import ink_within
        img = Image.new("RGB", (200, 100), "#E0DCD0")
        d = ImageDraw.Draw(img)
        d.rectangle([40, 20, 159, 79], fill="#204020")      # the block
        d.rectangle([60, 35, 139, 64], fill="#FFFFFF")      # type reversed out
        d.rectangle([20, 20, 39, 79], fill="#FFFFFF")       # a window beside it
        outline = [[20 / 200, 20 / 100], [160 / 200, 20 / 100],
                   [160 / 200, 80 / 100], [20 / 200, 80 / 100]]
        window = [[20 / 200, 20 / 100], [40 / 200, 20 / 100],
                  [40 / 200, 80 / 100], [20 / 200, 80 / 100]]
        row = {"text": "20mg", "u0": 20 / 200, "u1": 160 / 200,
               "v0": 20 / 100, "v1": 80 / 100, "cap_frac": 0.6,
               "words": [{"text": "20mg", "u0": 20 / 200, "u1": 160 / 200,
                          "v0": 20 / 100, "v1": 80 / 100}]}
        got = ink_within(img, row, [("#204020", outline, [window])])
        self.assertGreater(
            got["u0"], 0.25,
            "the window's white counted as the row's ink, so the box was pulled "
            "left onto board the shape does not cover")



class TestAPartsColourIsAStatementAboutItsSURFACE(unittest.TestCase):
    """Contract 1.9's two rules, on synthetic masks with known colours.

    A field's `fill` is the median of the whole cluster `segment()` found, and a
    part is one region of that cluster. Measured over the design group's 75
    printed parts, 33 sit at or beyond `SAME_SURFACE_MAX` from the colour they
    were painted (00_PROJECT_STATE/FIT_COLOUR.md), which is why the part carries
    its own. What these pin is the two rules that decide WHICH colour, both of
    which were added because measurement said the naive version fails.
    """

    W = H = 60

    def _canvas(self, blocks):
        """(masks, raw) for a list of (slice_x, colour) blocks."""
        import numpy as np
        raw = np.zeros((self.H, self.W, 3), dtype=float)
        masks = []
        for x0, x1, colour in blocks:
            m = np.zeros((self.H, self.W), dtype=bool)
            m[10:50, x0:x1] = True
            raw[m] = colour
            masks.append(m)
        return masks, raw

    def _fills(self, blocks, field_colour):
        from scripts.fit_design_spec import _part_fills
        masks, raw = self._canvas(blocks)
        return _part_fills(masks, raw, field_colour)

    def test_two_parts_of_one_surface_take_one_colour(self):
        """The defect the merge exists to stop.

        Without it the threshold below splits a single surface in two, because
        its parts land on either side of it: measured over the group, ten pairs
        across four cartons, worst `64_Kamagra`'s `highlight#1` and
        `highlight#3` at 0.0039 apart in the photograph and painted differently.
        """
        import numpy as np
        near = [(2, 20, (0.20, 0.20, 0.20)), (30, 48, (0.24, 0.24, 0.24))]
        got = self._fills(near, np.array([0.90, 0.90, 0.90]))
        self.assertEqual(got[0], got[1],
                         "two parts 0.069 apart were painted differently; they "
                         "are one surface by SAME_SURFACE_MAX, which is the "
                         "constant segment() merges two clusters at")

    def test_two_parts_of_different_surfaces_keep_their_own(self):
        """Guards the test above: merging everything would pass it."""
        import numpy as np
        far = [(2, 20, (0.10, 0.10, 0.10)), (30, 48, (0.80, 0.10, 0.10))]
        got = self._fills(far, np.array([0.50, 0.50, 0.50]))
        self.assertNotEqual(got[0], got[1],
                            "two parts 0.7 apart were given one colour")

    def test_a_part_near_its_field_takes_the_fields_value_exactly(self):
        """Not a near-duplicate of it.

        Emitting every part's own colour regardless is what the rolled-back
        attempt did, and it sent eight of the 28 cartons to "palette not
        separable" -- two paints a classifier cannot tell apart are not two
        paints. Thresholded, it is two.
        """
        import numpy as np
        field = np.array([0.40, 0.50, 0.60])
        got = self._fills([(2, 48, (0.41, 0.50, 0.60))], field)
        self.assertEqual(got[0], "#668099",
                         "a part within SAME_SURFACE_MAX of its field did not "
                         "take the field's value exactly")

    def test_a_part_far_from_its_field_does_not(self):
        """Guards the test above: always returning the field's would pass it."""
        import numpy as np
        got = self._fills([(2, 48, (0.05, 0.70, 0.30))], np.array([0.40, 0.50, 0.60]))
        self.assertNotEqual(got[0], "#668099")

    def test_the_merge_is_weighted_by_area(self):
        """A merged surface's colour is its big region's, not the average of two.

        Medians of two regions are each already robust; combining them by area
        is what keeps a sliver from dragging the surface it belongs to.
        Re-estimating over the union is NOT the same thing -- the erosion asks
        the mask how thick it is, and a union of scattered parts has no
        meaningful thickness.
        """
        import numpy as np
        # 0.069 apart, i.e. inside SAME_SURFACE_MAX so they merge at all. The
        # first version of this fixture used 0.20 and 0.26 -- 0.104 apart -- and
        # failed correctly, because those are two surfaces and not one.
        blocks = [(2, 46, (0.20, 0.20, 0.20)), (50, 53, (0.24, 0.24, 0.24))]
        got = self._fills(blocks, np.array([0.90, 0.90, 0.90]))
        self.assertEqual(got[0], got[1])
        level = int(got[0][1:3], 16) / 255.0
        self.assertLess(abs(level - 0.20), abs(level - 0.24),
                        f"the merged colour {got[0]} sits nearer the 3px sliver "
                        f"than the 44px region it belongs to")


class TestAReconstructedVertexLandsOnThePixelItWasTracedFrom(unittest.TestCase):
    """`part_region` is the inverse of the normalisation, for every reader.

    The spec stores an integer pixel index as `round(x / w, 4)`. Multiplying it
    back gives a value up to 0.0826 px either side of that integer, and PIL
    TRUNCATES a float polygon coordinate -- so half of every ring in every spec
    was rebuilt a WHOLE pixel off the pixel it was traced from. The gap between
    a fortieth of a pixel and a whole one is the entire defect.

    The old behaviour is reconstructed INSIDE these tests rather than left
    reachable from the code, because the three readers of this function -- the
    spec's own raster, the QA target and the coverage instrument -- must not be
    able to disagree about what a part covers, which is the property the
    function's docstring is built around.

    The grid is 1100x700 and not something round, deliberately. `x / 200` is
    exact in four decimals for every integer `x`, so on a tidy fixture the
    defect cannot appear at all -- the first draft of this class was written on
    one and passed while the bug was live. 1100 is the width these faces are
    actually rectified to.
    """

    W, H = 1100, 700
    #: The traced polygon, in the pixel indices `trace_outline` returns. Three
    #: of its four edges do not survive the round trip and y=91 does, which is
    #: the point: the displacement is signed per coordinate, not a global shift.
    TRACED = [(137, 91), (742, 91), (742, 508), (137, 508)]

    def _stored(self, pts):
        """What `fit()` writes to disk for these vertices."""
        return [[round(x / self.W, 4), round(y / self.H, 4)] for x, y in pts]

    def _mask(self, ring):
        import numpy as np
        from scripts.fit_design_spec import part_region
        return np.asarray(part_region({"outline": ring, "holes": []},
                                      self.W, self.H))

    def _fill(self, pts):
        """A polygon rasterised at the coordinates given, PIL's own way.

        With integer vertices this is the polygon as traced. With the products
        `u * w` it is what `part_region` used to build -- the defect, kept here
        so it is stated somewhere rather than merely absent.
        """
        import numpy as np
        from PIL import Image, ImageDraw
        im = Image.new("1", (self.W, self.H), 0)
        ImageDraw.Draw(im).polygon([tuple(q) for q in pts], fill=1)
        return np.asarray(im)

    def _unsnapped(self, ring):
        return self._fill([(u * self.W, v * self.H) for u, v in ring])

    def test_the_reconstruction_reproduces_the_traced_polygon_exactly(self):
        got = self._mask(self._stored(self.TRACED))
        want = self._fill(self.TRACED)
        self.assertTrue(
            (got == want).all(),
            f"{int((got != want).sum())} pixels differ from the polygon as "
            f"traced; the reconstruction is not the inverse of the storage")

    def test_the_plain_product_moves_the_edge_a_whole_pixel(self):
        """The defect itself, so a revert cannot pass unnoticed.

        Stated as the edge rather than as an area: the shape keeps very nearly
        its size and MOVES, which is why it cost agreement without costing
        coverage and so stayed invisible in every figure but the coverage one.
        """
        import numpy as np
        stored = self._stored(self.TRACED)
        plain = self._unsnapped(stored)
        want = self._fill(self.TRACED)
        self.assertFalse((plain == want).all(),
                         "expected the unsnapped reconstruction to be displaced")
        left_plain = int(np.nonzero(plain.any(0))[0].min())
        left_want = int(np.nonzero(want.any(0))[0].min())
        self.assertEqual(left_want - left_plain, 1,
                         "the displacement is one whole pixel, not a fraction")
        self.assertTrue(np.array_equal(self._mask(stored), want),
                        "and `part_region` must be on the corrected side of it")

    def test_all_three_readers_get_the_same_region(self):
        """One implementation, which is what the function exists to guarantee.

        `rasterise()` is what `design_qa` scores a render against and what
        `verify()` writes `pixel_agreement` from; `spec_index` is what
        `design_coverage` reads. Before this they could not disagree because
        they shared the defect. Now they cannot disagree because they share the
        fix, and this is the test that says so.
        """
        import numpy as np
        from scripts.design_coverage import SUBSTRATE, spec_index
        from scripts.fit_design_spec import rasterise
        # Contract 1.9: the part carries the fill and `rasterise` paints it,
        # with no fallback to the field's. Equal here -- what this test is about
        # is the REGION both readers reconstruct, not which colour goes in it.
        spec = {"substrate": "#000000",
                "fields": [{"role": "brand", "fill": "#FFFFFF", "z": 0,
                            "parts": [{"outline": self._stored(self.TRACED),
                                       "fill": "#FFFFFF", "holes": []}]}]}
        drawn = np.asarray(rasterise(spec, self.W, self.H))[:, :, 0] > 127
        indexed = spec_index(spec, self.W, self.H) != SUBSTRATE
        want = self._fill(self.TRACED)
        self.assertTrue(np.array_equal(drawn, want), "rasterise() disagrees")
        self.assertTrue(np.array_equal(indexed, want), "spec_index() disagrees")

    def test_rounding_is_an_inverse_and_not_a_general_improvement(self):
        """A vertex that genuinely sits between two pixels is MOVED by it.

        The distinction the whole change rests on. Rounding is right here
        because the forward map's domain is the integers, so it removes a
        round-trip artefact. Handed a shape whose corners really do fall
        between pixels it displaces them instead -- it is not a step that can
        be added anywhere to make a number go up.
        """
        import numpy as np
        between = [(x + 0.7, y + 0.7) for x, y in self.TRACED]
        ring = [[x / self.W, y / self.H] for x, y in between]
        self.assertFalse(
            np.array_equal(self._mask(ring), self._unsnapped(ring)),
            "a genuinely fractional outline must be moved, not left alone -- "
            "otherwise the rounding is not doing what it claims")

    def test_the_rounding_rule_is_pinned_and_real_data_never_reaches_it(self):
        """Python rounds a tie to even. Named, and shown to be unreachable.

        `round(0.5) == 0` where half-up would give 1. The rule only bites for a
        vertex exactly between two pixels, and the storage puts every real one
        within 0.0826 px of an integer -- so it is documented rather than
        depended on.
        """
        self.assertEqual((round(0.5), round(1.5), round(2.5)), (0, 2, 2))

    def test_every_vertex_the_group_stores_snaps_without_ambiguity(self):
        """Real data: nothing in the 28 specs is anywhere near a tie.

        Face width is `measure_reference_face.OUT_WIDTH`, height follows from
        the spec's own `face_aspect`, so this reads the specs and no images.
        """
        from src.design_group import FOLDER_BY_STEM, TEMPLATES_DIR
        from scripts.measure_reference_face import OUT_WIDTH
        worst, worst_at, n = 0.0, None, 0
        for stem, folder in FOLDER_BY_STEM.items():
            spec = json.loads((TEMPLATES_DIR / folder / "design_spec.json")
                              .read_text(encoding="utf-8"))
            w = OUT_WIDTH
            h = round(w * float(spec["face_aspect"]))
            for field in spec.get("fields") or []:
                for part in field.get("parts") or []:
                    rings = [part.get("outline") or []]
                    rings += list(part.get("holes") or [])
                    for ring in rings:
                        for u, v in ring:
                            for val, size in ((u, w), (v, h)):
                                d = abs(val * size - round(val * size))
                                n += 1
                                if d > worst:
                                    worst, worst_at = d, (stem, val, size)
        self.assertGreater(n, 5000, "the group's specs went missing")
        self.assertLess(
            worst, 0.25,
            f"a stored coordinate is {worst:.4f} px from the nearest pixel "
            f"({worst_at}); the rounding is the inverse of the trace only while "
            f"every vertex is unambiguously one pixel")


class TestTheFaceResolutionCeilingIsDeclared(unittest.TestCase):
    """How many real pixels each measurement had, stated instead of assumed.

    `measure_reference_face.OUT_WIDTH` is 1100 for every folder whatever the
    photograph, so a spec is traced from the face enlarged to that width. On
    `357_Adderall` the face is 134x172 pixels in its source and the enlargement
    is 8.2x; `SIMPLIFY_TOLERANCE`, a thousandth of the rectified width, is 0.13
    of a source pixel there -- finer than the grid the evidence is on.

    This test DECLARES that rather than forbidding it. A folder below the
    threshold keeps its spec, stays in TEMPLATE_SAMPLE and goes on rendering;
    what it may not do is be a surprise. The same idiom as UNMEASURABLE above,
    for a different limit: `107_Tramadol` is out because no simple ring can
    represent its segmentation, these six are in but measured from very little.

    It fails in both directions on purpose. Better photography for one of these
    should remove it from the set, and a folder that drops below the threshold
    should be added -- either way by editing a list, which is a decision, rather
    than by a figure quietly moving.
    """

    #: Threshold and membership both come from scripts/measure_face_resolution.py,
    #: which states how the number was taken from the distribution rather than
    #: chosen. Kept here as literals so this test is readable on its own and
    #: fails loudly if the script's answer changes.
    MIN_FACE_PX = 350
    BELOW_THRESHOLD = {
        "135_Ativan",        # 302x465, 3.64x
        "151_Provigil",      # 147x248, 7.48x  -- and no `print` component at all
        "156_Xanax",         # 260x179, 4.23x
        "304_Sonata",        # 278x182, 3.96x
        "357_Adderall",      # 134x172, 8.21x  -- the group's smallest face
        "362_Hydrocodone",   # 322x406, 3.42x
    }

    def test_exactly_these_folders_are_measured_from_a_short_face(self):
        if not TEMPLATES_DIR.exists():
            self.skipTest(f"{TEMPLATES_DIR.name}/ is not in this checkout")
        from scripts.measure_face_resolution import MIN_FACE_PX, face_size
        from src.design_group import FOLDER_BY_STEM

        self.assertEqual(
            MIN_FACE_PX, self.MIN_FACE_PX,
            "the threshold moved in measure_face_resolution.py; this list was "
            "measured against the old one")

        short = set()
        seen = 0
        for name in set(FOLDER_BY_STEM.values()):
            md = TEMPLATES_DIR / name / "metadata.json"
            if not md.exists():
                continue
            corners = json.loads(md.read_text(encoding="utf-8")).get("front_face_px")
            if not corners or len(corners) != 4:
                continue
            seen += 1
            if face_size(corners)[0] < MIN_FACE_PX:
                short.add(name)

        self.assertGreater(seen, 20, "the group's metadata went missing")
        self.assertEqual(
            short, self.BELOW_THRESHOLD,
            f"the set of folders measured from a face narrower than {MIN_FACE_PX}px "
            f"has changed: now {sorted(short)}. This is a declaration, not a gate -- "
            f"update the list and say in the commit which photograph moved.")
