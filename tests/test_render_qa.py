import json
import os
import unittest
from unittest.mock import patch
from pathlib import Path
import scripts.render_qa as render_qa
from scripts.render_qa import check_image
from src.utils import PROJECT_ROOT

class TestManifestBackedChecks(unittest.TestCase):
    """QA must check the contract the renderer actually consumed.

    The Blender engine renders from the manifest's label_content. render_qa read
    brand_name and label_content off the PASSPORT, so wherever the two differ it
    reported a failure against a contract the renderer never saw.
    """

    MANIFEST = {
        "sku_id": "TEST-1",
        "template_id": "T1",
        "label_content": {
            "brand_name_display": "Atomoxetine Generic",
            "active_ingredient_display": "Atomoxetine",
            "dosage_display": "40mg",
            "unit_count_display": "10 Pills",
        },
    }

    @patch("scripts.render_qa.extract_text")
    def test_all_four_fields_found_scores_full_confidence(self, mock_extract):
        mock_extract.return_value = (
            True, "Atomoxetine Generic Atomoxetine 40mg 10 Pills")
        res = check_image(Path("dummy.png"), self.MANIFEST)
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["confidence"], 1.0)
        self.assertTrue(all(res["fields"].values()))

    @patch("scripts.render_qa.extract_text")
    def test_a_missing_field_warns_and_never_hard_fails(self, mock_extract):
        mock_extract.return_value = (True, "Atomoxetine 40mg 10 Pills")
        res = check_image(Path("dummy.png"), self.MANIFEST)
        self.assertEqual(res["status"], "WARN")
        self.assertFalse(res["fields"]["brand_name_display"])
        self.assertAlmostEqual(res["confidence"], 0.75)
        # Its own docstring promises the module never blocks the pipeline.
        self.assertNotIn("HARD_FAIL", res["status"])

    @patch("scripts.render_qa.extract_text")
    def test_dosage_still_matches_on_a_word_boundary(self, mock_extract):
        manifest = json.loads(json.dumps(self.MANIFEST))
        manifest["label_content"]["dosage_display"] = "5 mg"
        mock_extract.return_value = (True, "Atomoxetine Generic Atomoxetine 500mg 10 Pills")
        res = check_image(Path("dummy.png"), manifest)
        self.assertFalse(res["fields"]["dosage_display"],
                         "'5' must not match inside '500'")

    @patch("scripts.render_qa.extract_text")
    def test_ocr_unavailable_is_reported_not_scored(self, mock_extract):
        mock_extract.return_value = (False, "Tesseract binary not found")
        res = check_image(Path("dummy.png"), self.MANIFEST)
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertIsNone(res["confidence"])

    @patch("scripts.render_qa.extract_text")
    def test_empty_label_content_does_not_score_ok(self, mock_extract):
        # hits == result["expected"] is 0 == 0 for a manifest with nothing
        # checkable -- "nothing to check" must not read as "everything
        # checked out."
        mock_extract.return_value = (True, "anything")
        manifest = {"sku_id": "TEST-EMPTY", "label_content": {}}
        res = check_image(Path("dummy.png"), manifest)
        self.assertEqual(res["expected"], 0)
        self.assertEqual(res["found"], 0)
        self.assertNotEqual(res["status"], "OK")
        self.assertTrue(
            any("no checkable fields" in f for f in res["flags"]),
            f"flags={res['flags']}")


class TestSidecarAbsentVsNullCorners(unittest.TestCase):
    """A missing `{stem}.view.json` and one that exists but carries
    `"front_face_px": null` are different failure modes -- render_driver.py
    emits the latter whenever `_face_corners_px()` cannot locate the front
    face. Telling an operator to "re-render to produce the sidecar" when one
    is already sitting there sends them looking in the wrong place.
    """

    MANIFEST = TestManifestBackedChecks.MANIFEST

    @patch("scripts.render_qa.extract_text")
    def test_no_sidecar_at_all_is_reported_as_missing(self, mock_extract):
        mock_extract.return_value = (
            True, "Atomoxetine Generic Atomoxetine 40mg 10 Pills")
        res = check_image(Path("dummy.png"), self.MANIFEST, view=None)
        self.assertFalse(res["deskewed"])
        self.assertTrue(
            any("no {stem}.view.json" in f for f in res["flags"]),
            f"flags={res['flags']}")

    @patch("scripts.render_qa.extract_text")
    def test_sidecar_with_null_corners_is_reported_distinctly(self, mock_extract):
        mock_extract.return_value = (
            True, "Atomoxetine Generic Atomoxetine 40mg 10 Pills")
        res = check_image(Path("dummy.png"), self.MANIFEST,
                          view={"front_face_px": None})
        self.assertFalse(res["deskewed"])
        self.assertTrue(
            any("front_face_px is null" in f for f in res["flags"]),
            f"flags={res['flags']}")
        self.assertFalse(
            any("no {stem}.view.json" in f for f in res["flags"]),
            "a sidecar that exists must not be reported as missing")


class TestFieldPresent(unittest.TestCase):
    """Pins `_field_present` directly, independent of `check_image`.

    The brief's own verbatim implementation fails these cases -- confirmed
    interactively before this class was written (see task-7-report.md,
    "second attempt" section). Kept as a standing regression class so a
    future edit that reintroduces either bug fails immediately here, rather
    than only surfacing as a lower confidence score somewhere else.
    """

    def test_numeric_field_matches_when_unit_is_glued_to_the_digits(self):
        # '\b40\b' cannot match inside "40mg" -- '0' and 'm' are both word
        # characters, so \b finds no boundary between them. Every dosage in
        # this catalogue glues the unit straight onto the number this way.
        self.assertTrue(
            render_qa._field_present("40mg", "Atomoxetine 40mg 10 Pills"))

    def test_numeric_field_does_not_match_inside_a_longer_number(self):
        self.assertFalse(
            render_qa._field_present("5 mg", "TestDrug 500mg 10 Pills"),
            "'5' must not match inside '500'")

    def test_numeric_field_matches_with_surrounding_punctuation(self):
        # The property under test is the digit boundary surviving punctuation
        # pressed against the number -- "5," here.
        self.assertTrue(
            render_qa._field_present("5 mg", "TestDrug dosage: 5, mg quantity: 10"))

    def test_a_separated_unit_is_part_of_the_field_and_must_be_on_the_page(self):
        # This case USED to pass with the text below, which contains no "mg" at
        # all: the remainder "mg" is two characters, fell under the significance
        # filter, left an empty token list, and an empty `all()` is True. That
        # made the assertion "a field counts as found when part of it is
        # demonstrably absent", which is the false-OK this module exists to
        # avoid -- certifying a packshot is worse than nagging about one.
        #
        # Nothing in the catalogue has this shape: dosages glue their unit
        # ("40mg", the sole remainder form across all 391), and every unit-count
        # remainder is a word of three characters or more. So this is a contract
        # statement, not a live behaviour change.
        self.assertFalse(
            render_qa._field_present("5 mg", "TestDrug dosage: 5, quantity: 10"),
            "'mg' is not on the page, so the field is not fully present")

    def test_two_word_phrase_requires_every_token_not_just_the_longest(self):
        # "Atomoxetine" (11 chars) is longer than "Generic" (7), so a
        # "longest token wins" check would score this field found whenever
        # the separately-checked active-ingredient field is on the page,
        # even though "Generic" was never printed anywhere.
        self.assertFalse(
            render_qa._field_present("Atomoxetine Generic",
                                     "Atomoxetine 40mg 10 Pills"),
            "'Generic' never appears; matching the longest token alone is a false positive")
        self.assertTrue(
            render_qa._field_present(
                "Atomoxetine Generic",
                "Atomoxetine Generic Atomoxetine 40mg 10 Pills"))

    def test_numeric_field_does_not_satisfy_a_different_numeric_field(self):
        # 04_passports/render_manifests/21-min.json: dosage_display "30mg",
        # unit_count_display "30 Pills". Both reduce to the digits "30", and
        # the numeric branch used to stop at the number and never check
        # "Pills" -- so a render missing the whole unit-count row still
        # scored unit_count_display as found, purely because the dosage
        # printed "30mg" somewhere on the page. 11 of 391 SKU carry this
        # exact collision shape.
        text = "Cymbalta Duloxetine 30mg"  # no "Pills" anywhere
        self.assertTrue(
            render_qa._field_present("30mg", text),
            "the dosage itself is on the page and must still be found")
        self.assertFalse(
            render_qa._field_present("30 Pills", text),
            "'Pills' never appears; reducing the field to its digits alone "
            "lets the dosage's '30mg' satisfy the unit count too")
        self.assertTrue(
            render_qa._field_present("30 Pills", text + " 30 Pills"),
            "once 'Pills' is actually on the page the field is found")

    def test_a_short_unit_word_is_checked_like_any_other(self):
        # The significance filter drops tokens under three characters, which is
        # right for the general branch -- a one- or two-letter fragment is OCR
        # noise as often as it is a word. But in the numeric branch the filter
        # was applied to the REMAINDER and an empty result silently satisfied
        # `all()`, reopening the collision the test above closes: a unit count
        # written "30 EA" fell straight back to matching the digits alone, so a
        # dosage of "30mg" elsewhere on the page satisfied it.
        #
        # No SKU in the catalogue uses a unit shorter than three characters
        # today -- the shortest is "Pen", exactly at the threshold -- so this
        # guards a future catalogue rather than a present defect.
        text = "Brand Ingredient 30mg"  # no "EA" anywhere
        self.assertFalse(
            render_qa._field_present("30 EA", text),
            "'EA' never appears; a remainder too short to be a significant "
            "token must still be required, not dropped")
        self.assertTrue(
            render_qa._field_present("30 EA", text + " 30 EA"),
            "once 'EA' is on the page the field is found")

    def test_the_shortest_real_unit_in_the_catalogue_still_works(self):
        # "Pen" is three characters, exactly on the significance threshold, and
        # is a live value -- it must not become collateral damage of the test
        # above. If someone lowers or raises that threshold, this fails.
        self.assertTrue(render_qa._field_present("1 Pen", "Lantus 100IU 1 Pen"))
        self.assertFalse(
            render_qa._field_present("1 Pen", "Lantus 100IU 1 unit"),
            "'Pen' is not on the page")

    def test_blank_expected_is_never_present(self):
        self.assertFalse(render_qa._field_present("", "anything"))
        self.assertFalse(render_qa._field_present(None, "anything"))


class TestPunctuationTolerantMultiTokenFields(unittest.TestCase):
    """`_field_present` must survive OCR re-spacing punctuation, not just
    demand every token byte-for-byte.

    Values are real `brand_name_display` strings pulled from
    04_passports/render_manifests/ (111-min: Retin-A Cream 0.025%; 351-min
    carries a hyphenated "L-VC" token; 409/411/412-min carry the
    "<ingredient words> Generic" collision shape at three tokens instead of
    two). The 111-min OCR text quoted here is the ACTUAL raw (un-deskewed)
    pytesseract output measured on this branch -- not invented -- confirming
    that even the corrected matcher does not manufacture a match where the
    OCR reading has genuinely lost a letter, only where it has mangled
    punctuation/whitespace around letters that are still there.
    """

    def test_hyphen_and_percent_respacing_still_matches(self):
        # Every punctuation mark in the field ("-", ".", "%") independently
        # re-spaced by OCR, exactly the shape reported against 04_passports/
        # render_manifests/111-min.json's brand_name_display.
        self.assertTrue(render_qa._field_present(
            "Retin-A Cream 0.025%",
            "Retin - A Cream 0.025 % Tretinoin 30 Tubes"))

    def test_percent_respacing_alone_still_matches(self):
        # 04_passports/render_manifests declares this exact string for
        # several SKU (e.g. Vaniqa Cream 13.9%, Lumigan 0.03%).
        self.assertTrue(render_qa._field_present(
            "Vaniqa Cream 13.9%", "Vaniqa Cream 13.9 % Eflornithine"))

    def test_hyphenated_token_survives_hyphen_dropped_to_a_space(self):
        # 04_passports/render_manifests/351-min.json's brand_name_display
        # ends in the hyphenated token "L-VC".
        self.assertTrue(render_qa._field_present(
            "Test Pack L-VC", "Test Pack L VC kit"))

    def test_verbatim_punctuation_still_matches(self):
        # The un-mangled case must keep working: normalisation must not
        # require noise to be present, only tolerate it when it is.
        self.assertTrue(render_qa._field_present(
            "Retin-A Cream 0.025%", "Retin-A Cream 0.025% Tretinoin"))

    def test_a_genuinely_lost_letter_is_still_a_miss(self):
        # The actual raw (un-deskewed) OCR reading measured on this branch
        # for 111-min: extract_text() on 02_processing/blender_test_renders/
        # 111-min.png returns '...retin” cream...' -- the '-A' is not
        # respaced, it is GONE, replaced by a stray quote glyph. Punctuation
        # normalisation can recover formatting noise; it cannot invent a
        # letter tesseract never read. This must stay a miss -- if it did
        # not, the matcher would have drifted from "tolerant of formatting"
        # to "tolerant of missing content," which is the too-lax failure
        # mode this task also has to avoid.
        self.assertFalse(render_qa._field_present(
            "Retin-A Cream 0.025%", "8 retin” cream Moraes p"))

    def test_three_token_generic_collision_still_requires_every_token(self):
        # 04_passports/render_manifests/409-min.json, 411-min.json and
        # 412-min.json each carry a THREE-token brand of the
        # "<ingredient words> Generic" shape, e.g. brand_name_display
        # "Nandrolone Decanoate Generic" against active_ingredient_display
        # "Nandrolone Decanoate". Punctuation tolerance must not have been
        # achieved by also relaxing which TOKENS are required: if "Generic"
        # is missing, the brand is still not found, even though two of its
        # three tokens (both shared with the separately-checked ingredient
        # field) are right there in the text.
        self.assertFalse(render_qa._field_present(
            "Nandrolone Decanoate Generic",
            "Nandrolone Decanoate 50mg 10 Vials"))
        self.assertTrue(render_qa._field_present(
            "Nandrolone Decanoate Generic",
            "Nandrolone Decanoate Generic 50mg 10 Vials"))


class TestTokenMatchAlignsToWordBoundaries(unittest.TestCase):
    """A letter-bearing token may only match text that OCR split ONE word
    across a space -- never text formed by bridging into the middle of a
    genuinely different, unrelated word.

    Round 1 of the punctuation fix flattened the WHOLE OCR text to one
    contiguous letters/digits blob (`"foo x yzoo"` -> `"fooxyzoo"`) and did a
    bare substring search. That has no boundary anchor at all, so it can
    "find" a token the text never actually contains: `"Xyz"` is not in
    `"foo x yzoo"`, but it IS a substring of the flattened
    `"fooxyzoo"`, spanning the tail of the unrelated word "x" and the head
    of the unrelated word "yzoo". Code review reproduced this directly and
    swept all 391 manifests x 4 fields for cases where it flips a real
    verdict -- none found today, but the class of bug is exactly what a
    verification barrier exists to keep out, latent or not.

    The fix requires a match to BEGIN where some original word begins and
    END where some (possibly later) word ends, with nothing but other
    complete words in between -- true for "Cream" split into "Cre am" by an
    OCR-inserted space, false for "Xyz" bridging "x" and "yzoo".
    """

    def test_intra_word_split_by_a_stray_space_still_matches(self):
        # The exact shape this whole branch exists to tolerate: OCR drops
        # one space into the middle of a single printed word.
        self.assertTrue(render_qa._field_present("Cream", "Cre am"))
        self.assertTrue(render_qa._field_present("Generic", "Gene ric"))
        self.assertTrue(render_qa._field_present("Retin-A", "Ret in A"))

    def test_bridging_into_an_unrelated_word_does_not_match(self):
        # The counter-example from code review: "Xyz" is not written
        # anywhere in "foo x yzoo" -- the flattened blob "fooxyzoo" merely
        # happens to contain the substring "xyz" by coincidence of two
        # unrelated words landing next to each other.
        self.assertFalse(render_qa._field_present("Xyz", "foo x yzoo"))

    def test_multi_token_field_still_recovers_a_genuine_intra_word_split(self):
        # Property 1 from the review: the 98 multi-token brands must not
        # regress. 111-min's brand_name_display, respaced the way OCR
        # actually respaces it, must still be a full match.
        self.assertTrue(render_qa._field_present(
            "Retin-A Cream 0.025%", "Retin - A Cream 0.025 %"))

    def test_multi_token_field_does_not_match_via_a_bridged_token(self):
        # Same shape as the Xyz counter-example, but inside a multi-token
        # field: "Cream" is genuinely there, but "Retin-A" is not -- it must
        # not be manufactured by bridging into an unrelated word.
        self.assertFalse(render_qa._field_present(
            "Retin-A Cream 0.025%", "foo x yzoo Cream"))

    def test_slash_joined_field_still_matches_when_text_has_no_space_around_it(self):
        # Regression pinned by this fix's own 391-SKU sweep. 111-min's
        # dosage_display is "0.025g/0.025%": the outer tokenizer splits it
        # on '/' into two required tokens ("0.025g", "0.025%"), but if the
        # word-boundary detector for the OCR TEXT only split on whitespace,
        # the verbatim "0.025g/0.025%" (no space around the '/') stayed ONE
        # undivided text word with no internal boundary, so the first token
        # failed its end-boundary check even though it is right there,
        # unmangled. `_TOKEN_SPLIT_RE` must be the SAME pattern on both
        # sides to avoid this.
        self.assertTrue(render_qa._field_present(
            "0.025g/0.025%", "Retin-A Cream 0.025g/0.025% Tretinoin 30 Tubes"))
        # Same shape for a word field: 239-min's active_ingredient_display.
        self.assertTrue(render_qa._field_present(
            "Caffeine/Ergotamine", "Cafergot Caffeine/Ergotamine 1mg 30 Pills"))


class TestNumericTokenIsNotWeldedToTheNextNumber(unittest.TestCase):
    """A numeric token's digit boundary must be judged against the REAL
    spacing of the OCR text, not against text with every space deleted.

    `_digit_bounded_search` used to run on `re.sub(r"\\s+", "", text)`, so a
    percent-ending token printed next to an unrelated number -- exactly how
    this catalogue lays out a label, dosage then unit count -- had the two
    welded into one string: "0.025% 30 Tubes" collapsed to "0.025%30Tubes",
    and the trailing '(?!\\d)' then saw the '3' of an entirely different
    token and rejected a value that is plainly printed on the page.

    18 of 391 SKU carry a percent-ending `dosage_display` (04_passports/
    render_manifests: 10g/1% x3, 5mg/5% x2, 0.025g/0.025%, 15g/13.9%,
    1.62%, 0.005%, 5g/2.5% ...) and every one of them is followed by a
    `unit_count_display` that starts with a digit ("30 Tubes", "1 Tube",
    "30 Sachets"). Feeding all 391 manifests a PERFECT reading of their own
    four label fields, 317-min ("5g/2.5%" beside "1 Tube") already scored its
    own correct dosage as missing before this fix; the other 17 were masked
    only because the same value also appears in their brand field ahead of a
    letter.

    The stripping was not gratuitous -- it was there to tolerate OCR
    re-spacing punctuation ("0.025%" read back "0.025 %"), which is why the
    naive repair of simply searching the raw text is wrong too. Both
    properties are pinned here together, because a fix that only satisfies
    one of them is not a fix.
    """

    def test_percent_token_followed_by_a_separate_number_is_found(self):
        # 111-min: dosage_display "0.025g/0.025%", unit_count_display
        # "30 Tubes". The '%' half is matched by the digit-bounded path; the
        # '3' of "30" is a different token and must not act as its boundary.
        self.assertTrue(render_qa._field_present(
            "0.025g/0.025%", "BrandX IngredientY 0.025g/0.025% 30 Tubes"))
        # 317-min: the one SKU already mis-scored against a perfect reading.
        self.assertTrue(render_qa._field_present(
            "5g/2.5%", "Zovirax Acyclovir 5g/2.5% 1 Tube"))
        # 143-min: a bare percent dosage, no '/' half to fall back on.
        self.assertTrue(render_qa._field_present(
            "1.62%", "Rogaine Minoxidil 1.62% 30 Sachets"))

    def test_a_number_before_the_token_does_not_hide_it_either(self):
        # The same welding in the other direction: stripping the space makes
        # the leading '(?<!\\d)' see the '0' of "30" ahead of "1.62%".
        self.assertTrue(render_qa._field_present(
            "1.62%", "Rogaine 30 1.62% Sachets"))

    def test_respacing_inside_the_token_is_still_tolerated_beside_a_number(self):
        # Both properties at once, which is what makes this a real pin: the
        # space OCR inserts BEFORE the '%' still has to be forgiven, while
        # the genuine space AFTER it still has to count as a boundary. A
        # repair that just searches the raw text passes the two tests above
        # and fails this one.
        self.assertTrue(render_qa._field_present(
            "1.62%", "Rogaine Minoxidil 1.62 % 30 Sachets"))
        self.assertTrue(render_qa._field_present(
            "0.025g/0.025%", "Retin-A Cream 0.025g / 0.025 % 30 Tubes"))

    def test_a_digit_glued_to_the_token_is_still_not_a_boundary(self):
        # The guarantee the digit boundary exists for, unchanged: tolerating
        # a real space must not also tolerate a digit printed hard against
        # the token. "2.5%" is not present in "12.5%".
        self.assertFalse(render_qa._field_present(
            "2.5%", "Cream 12.5% 1 Tube"))
        self.assertFalse(render_qa._field_present(
            "5 mg", "TestDrug 500mg 10 Pills"))


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "ocr"
_HAVE_TESSERACT = render_qa._TESSERACT_AVAILABLE


@unittest.skipUnless(_HAVE_TESSERACT,
                     f"Tesseract unavailable: {render_qa._TESSERACT_ERROR}")
@unittest.skipUnless((FIXTURE_DIR / "1-min.png").exists(),
                     f"OCR fixture missing from {FIXTURE_DIR}")
class TestOCRBarrier(unittest.TestCase):
    """Proves the label text is VISIBLE, which --dump-scene cannot.

    A dump proves a text object holds the right string byte for byte. It cannot
    see a correct string that fell outside the camera, ended up behind another
    face, or rendered white on white. This can.

    A committed fixture rather than a live render, because renders are not
    tracked by git and an opt-in check is not a barrier. The slow gate below
    re-renders the same SKU so the fixture cannot silently go stale.
    """

    @classmethod
    def setUpClass(cls):
        cls.png = FIXTURE_DIR / "1-min.png"
        cls.manifest = json.loads(
            (FIXTURE_DIR / "1-min.manifest.json").read_text(encoding="utf-8"))
        cls.view = json.loads(
            (FIXTURE_DIR / "1-min.view.json").read_text(encoding="utf-8"))

    def test_the_brand_name_is_readable_off_the_render(self):
        res = render_qa.check_image(self.png, self.manifest, self.view)
        self.assertTrue(res["deskewed"], "the fixture's view sidecar was not used")
        self.assertTrue(
            res["fields"]["brand_name_display"],
            f"brand name not recognised; flags={res['flags']}")

    def test_at_least_three_of_four_label_fields_are_readable(self):
        res = render_qa.check_image(self.png, self.manifest, self.view)
        # A threshold, not an exact string: Tesseract is a third-party
        # recogniser and an upgrade may change its output. 5.4.0.20240606 is the
        # version this was calibrated against.
        self.assertGreaterEqual(
            res["found"], 3,
            f"only {res['found']}/{res['expected']} fields read; "
            f"flags={res['flags']}")

    def test_deskewing_is_what_makes_it_readable(self):
        """Without this, someone could delete the deskew call and the two tests
        above might still pass by luck on one lucky fixture."""
        with_deskew = render_qa.check_image(self.png, self.manifest, self.view)
        without = render_qa.check_image(self.png, self.manifest, None)
        self.assertFalse(without["deskewed"])
        self.assertGreater(
            with_deskew["found"], without["found"],
            "deskewing did not improve recognition; either the corners are "
            "wrong or the deskew step is not being applied")


@unittest.skipUnless(_HAVE_TESSERACT,
                     f"Tesseract unavailable: {render_qa._TESSERACT_ERROR}")
class TestOCRBarrierOverTheTemplateSample(unittest.TestCase):
    """The same barrier as above, over eleven SKU instead of one.

    The audit's third finding: the product's headline claim -- that a text object
    draws the string it is handed or nothing at all -- was proven on `1-min` and
    nowhere else, while a 48-SKU sweep had already turned up two classes of
    defect that fixture cannot show. One SKU is an example, not a guarantee.

    The eleven are the reference-template sample: every folder under
    `Reference Templates/` that holds actual reference photography. They are the
    SKU the project has real packaging to be judged against, which is why they
    are the group worth proving readable. Their fixtures are committed, so this
    runs on a clean checkout with no renderer and no `Reference Templates/`
    present -- an opt-in check is not a barrier.

    What it does NOT cover: every one of the eleven is T1 or T1_SMALL. The
    narrower faces -- T3, the vertical family, T_MULTIPACK -- have no reference
    photography and are not represented here. This closes "one SKU" and does not
    close "one template family".
    """

    # REGENERATED at contract 1.8, from fixtures built at `3c53e52`.
    #
    # Between those two commits the renderer changed four times -- Phase A
    # enumerated the design, Phase B replaced every geometric admission rule
    # with a hand-made ground truth, 1.7 gave the fields a paint order, 1.8 made
    # a part a region rather than a ring -- and the fixtures were not rebuilt
    # once. They described a renderer that no longer existed, and the suite was
    # green because it read them and they were self-consistent with each other.
    # `TestOCRAgainstAFreshRender` is the gate that says so, and it had been red
    # across all four phases with nobody running it.
    #
    # WHAT THE REGENERATION ABSORBED, stated because a regeneration that does
    # not say what it swallowed is a silent cap. Six rows had started missing
    # before 1.8 and were not noticed: `149-min` dosage, `150-min` unit count,
    # `308-min` dosage, `357-min` ingredient, `365-min` ingredient, `404-min`
    # unit count. One is attributable to 1.8 -- `64-min` dosage -- and there the
    # RENDER improved: its "100mg" used to be printed white on the teal field
    # and is now dark on the board window the field leaves for the salmon badge,
    # which is what the real carton does. Tesseract read the old one and does
    # not read the new one.
    #
    # It also shrank. Ten rows that used to miss now READ -- `60-min` brand and
    # dosage, `149-min` unit count, `157-min` ingredient, `221-min` dosage and
    # unit count, `340-min` unit count, `346-min` brand and unit count, `365-min`
    # dosage -- so the list goes 21 entries to 17 while the sample's total misses
    # go 21 to 18. The four phases made the renderer better; nothing was watching
    # that either.
    #
    # Accepted misses. Every one was checked on the rectified face of the render
    # it is scored against: the string is PRINTED and legible to a person, and
    # Tesseract returns something else or nothing. What it returns is recorded
    # beside it as evidence, so a reader can see what the reader did instead of
    # taking a comment for it. A row where a GLYPH is not legible is not here --
    # see `ROWS_THE_RENDER_HIDES`.
    #
    # Reading at 2x resolution was measured as a way out and is worse, not
    # better: 21 misses become 25 and not one brand is recovered.
    #
    # MISREAD -- the string comes back mangled, so we can see it was found:
    KNOWN_OCR_MISSES = {
        ("59-min", "unit_count_display"),    # "30 Pills" -> "30 ill"
        ("135-min", "dosage_display"),       # "1mg" -> "lmg", lowercase L for the digit
        ("308-min", "dosage_display"),       # "3mg" -> "& mg" one pass, "a mg" the other
        ("365-min", "active_ingredient_display"),  # "HCl" -> "HCI}" -- the same lowercase
                                             # L as `230-min`, plus the edge of the design
                                             # block that ABUTS the row read as a brace.
                                             # The block does not cover a glyph: measured,
                                             # 0.0% of this row's cap band is hidden.
        ("365-min", "unit_count_display"),   # "30 Pills" -> "0 Pills" / "si Pills"
        ("404-min", "unit_count_display"),   # "30 Pills" -> "30 ee"
        #
        # NOT RETURNED AT ALL, though printed and legible -- checked on the
        # rectified face one by one. Tesseract simply omits the row.
        ("62-min", "active_ingredient_display"),
                                             # "Tadalafil", and the row did not
                                             # move: it reads in every page mode
                                             # from a crop of its own band and
                                             # is lost only in the whole-face
                                             # read, which changed when the
                                             # brand beside it did. The brand
                                             # used to lie across the dosage bar
                                             # and no longer does; this is what
                                             # that cost.
        ("62-min", "dosage_display"),        # "20mg" in its amber badge at v0.43
        ("64-min", "dosage_display"),        # "100mg" dark in the board window the
                                             # teal field leaves; crisp at any crop
        ("149-min", "unit_count_display"),   # "30 Pills", dark on the board at the
                                             # right, the purple band's corner just
                                             # touching the foot of the glyphs. LOOKED
                                             # AT on the rectified face at native scale:
                                             # every glyph is clear, and
                                             # TestNoGridRowIsPrintedInInkItsOwn
                                             # BackgroundHides passes on this carton --
                                             # the cap band is on one surface. It started
                                             # missing at contract 1.9 for the same
                                             # reason `149-min`'s dosage started
                                             # READING: that band went from `#C84569` at
                                             # 0.390 perceived luma to `#7333B8` at
                                             # 0.291. Darker helps white type on it and
                                             # hurts dark type across it -- one cause,
                                             # two signs.
        ("344-min", "unit_count_display"),   # the same string on the same frame and a
                                             # different carton shape, where it sits
                                             # ENTIRELY on the board beside the small
                                             # `#6009B0` square. Nothing covers a glyph;
                                             # this is the `365-min` pattern already
                                             # recorded above, a design edge ABUTTING
                                             # the row perturbing the whole-face read.
        ("155-min", "unit_count_display"),   # "30 Pills", small, bottom left
        ("158-min", "brand_name_display"),   # the whole face returns "a Clonazepam"
        ("158-min", "dosage_display"),       # likewise
        ("158-min", "unit_count_display"),   # likewise
        ("344-min", "dosage_display"),       # "200mg", the same frame as `149-min`
        #
        # CONTRACT 1.10 -- a MARK stands beside or across the row, and Tesseract
        # groups it with the words. Every one of these was looked at on the
        # rectified face at native scale and every glyph is legible to a person;
        # what changed is that the face now carries small letterform-like shapes
        # the reader treats as characters. Nine rows here against three that
        # started reading -- `230-min` active ingredient, `150-min` unit count
        # and `357-min` brand, all three removed above rather than left recorded
        # as broken, and the last of them also leaves `KNOWN_BRAND_MISREADS`.
        #
        # It is filed as the READER on the project's two checks and not on the
        # OCR return: the faces were inspected one by one, and the marks do not
        # hide a glyph -- `157-min`'s Roche hexagon is an OUTLINE crossing
        # "30 Pills", `230-min`'s Neptune mark is an orange outline overlapping
        # "15mg", `404-min`'s two Novartis fragments sit on the board beside
        # "Ritalin 10mg". The related RENDER defect -- that the grid does not
        # know marks exist and can place a row across one -- is open and
        # recorded in the driver and in 00_PROJECT_STATE/MARKS_DRAWN.md.
        #
        # This list was briefly wrong in a way worth recording, because the
        # instrument was at fault rather than the carton: two rows were entered
        # here that the RENDER reads and the committed WEBP did not. At q98 the
        # fixture had stopped reading the same as the PNG it came from -- three
        # rows of 112, in both directions -- so no list could satisfy both the
        # fixture barrier and the fresh-render gate at once. The fixtures are
        # lossless now and the two agree again; see `scripts/make_ocr_fixtures`.
        ("157-min", "active_ingredient_display"),
        ("157-min", "dosage_display"),
        # `157-min` unit count came OFF this list by being earned. "30 Pills"
        # was printed straight through the Roche hexagon -- the strokes cut the
        # "0", the "P" and the "s" -- and the row now sets clear of it, because
        # `_clear_of_design` can see a mark. That was reverted once on a misread
        # figure; the driver's `_one_ink_serves` carries the correction.
        ("221-min", "dosage_display"),
        ("221-min", "unit_count_display"),
        ("230-min", "dosage_display"),
        ("357-min", "active_ingredient_display"),
        ("404-min", "brand_name_display"),
        ("404-min", "dosage_display"),
    }

    #: Rows where a GLYPH is not legible, which is a defect in the RENDER and
    #: not in the reader. Kept apart from `KNOWN_OCR_MISSES` on purpose: filing
    #: one of these as a reader limitation is how a regeneration hides a
    #: regression, and the two are told apart by looking at the rectified face
    #: and asking whether a person can read every glyph.
    #:
    #: Tolerated so the suite is green, and visible so it is not forgotten.
    #: Measured with the same computation `tests/test_blender_carton.py::
    #: TestNoGridRowIsPrintedInInkItsOwnBackgroundHides` uses -- which does NOT
    #: cover this SKU: its list is nine cartons and `357-min` is not one of them,
    #: so this barrier is the only thing that sees it.
    #: Empty, and it took a fix to empty it. It held one entry --
    #: `357-min`'s ingredient row, 10.0% of its cap band printed in white where
    #: the white swoosh rises into it, which Tesseract returned as 'Amphetamine
    #: / Dextroamphetapaiiugmtaa ts ie'. The cause was that
    #: `render_driver._clear_of_design` only ever moved a row DOWN, and every
    #: offset that clears that row lies UP the face. It is cleared now by a rise
    #: of 0.015, and the row reads. The same change cleared `357-min`'s dosage
    #: at 28.7% and `149-min`'s unit count at 13.7%, neither of which this
    #: barrier had ever noticed, because both still read while straddling.
    ROWS_THE_RENDER_HIDES = {}

    # The sample cannot silently shrink to the one fixture it replaced.
    #
    # Twenty-eight: every folder in `src/design_group.TEMPLATE_SAMPLE`. It was
    # nine, covering the SKU that happened to have fixtures, while nineteen
    # more sat in the sample unwatched -- and when they were finally rendered
    # and read, eight render defects came out of them. Lowering this number is
    # exactly the quiet shrink the constant exists to catch.
    #
    # The earlier note, kept because the reasoning still holds: nine, not
    # eleven, and the two it lost are named in `src/design_group.py`
    # rather than merely subtracted here: a re-acquisition replaced the group's
    # photography, and `21_Valium_Brand` and `24_Xanax_Pfizer` came back with
    # frames nothing can measure -- a blister lying across the printed face, and
    # two cartons in one shot. They left TEMPLATE_SAMPLE, so they left this
    # barrier with it. Lowering this number is exactly the quiet shrink the
    # constant exists to catch, which is why it is lowered in the open, with the
    # cause written down, and not by one.
    MIN_SAMPLE = 28

    @classmethod
    def setUpClass(cls):
        from scripts.make_ocr_fixtures import sample_stems
        cls.stems = sample_stems()
        cls.cases = []
        for stem in cls.stems:
            webp = FIXTURE_DIR / f"{stem}.webp"
            manifest = FIXTURE_DIR / f"{stem}.manifest.json"
            view = FIXTURE_DIR / f"{stem}.view.json"
            if not (webp.exists() and manifest.exists() and view.exists()):
                continue
            cls.cases.append((
                stem, webp,
                json.loads(manifest.read_text(encoding="utf-8")),
                json.loads(view.read_text(encoding="utf-8")),
            ))

    def test_the_sample_is_present_and_has_not_shrunk(self):
        self.assertGreaterEqual(
            len(self.cases), self.MIN_SAMPLE,
            f"only {len(self.cases)} of {len(self.stems)} fixtures found. "
            f"Rebuild with `python scripts/make_ocr_fixtures.py`; a barrier that "
            f"quietly covers fewer SKU reports the same green as one that covers "
            f"them all.")

    def test_every_label_field_in_the_sample_is_readable_off_the_render(self):
        misses = set()
        for stem, webp, manifest, view in self.cases:
            res = render_qa.check_image(webp, manifest, view)
            self.assertTrue(res["deskewed"],
                            f"{stem}: the view sidecar was not used")
            for field, found in res["fields"].items():
                if not found:
                    misses.add((stem, field))
        new = misses - self.KNOWN_OCR_MISSES - set(self.ROWS_THE_RENDER_HIDES)
        self.assertFalse(
            new,
            f"label text that no longer reads off the render: {sorted(new)}")

    def test_the_known_miss_list_is_not_stale(self):
        """A ratchet that has silently been fixed is a ratchet nobody trusts.

        Both lists, not one. A render defect that starts reading has been FIXED,
        and leaving it recorded says the renderer still hides a row it does not
        -- which is the same lie in the other direction.
        """
        listed = self.KNOWN_OCR_MISSES | set(self.ROWS_THE_RENDER_HIDES)
        still_missing = set()
        for stem, webp, manifest, view in self.cases:
            if not any(s == stem for s, _ in listed):
                continue
            res = render_qa.check_image(webp, manifest, view)
            still_missing |= {(stem, f) for f, ok in res["fields"].items() if not ok}
        fixed = listed - still_missing
        self.assertFalse(
            fixed,
            f"these now read and should be removed from KNOWN_OCR_MISSES or "
            f"ROWS_THE_RENDER_HIDES: {sorted(fixed)}")

    #: Brands that are PRINTED correctly and misread by Tesseract, with what
    #: it returns instead. The value is the evidence, kept as data so a person
    #: can see what the reader actually did rather than take a comment for it.
    #: All four were checked on the rectified face: the wordmark is there and a
    #: person reads it. All four are stable across runs.
    #:
    #: This weakens a guard deliberately, so it is worth being exact about
    #: which one. What caught the Gemini engine's invented "Datels" was that a
    #: renderer can print a word appearing in no manifest. THAT is pinned
    #: byte-for-byte on the built scene by tests/test_blender_carton.py::
    #: TestLabelText::test_every_string_survives_verbatim -- which runs on one
    #: fixture SKU, the rest resting on the structural argument that a Blender
    #: text object draws its `body` or nothing. What is given up here is the
    #: weaker, per-SKU claim that the string also survives legibly INTO PIXELS,
    #: and only for these four.
    #:
    #: Reading at 2x resolution was measured as a way out: 21 misses become 25
    #: and not one of these four is recovered.
    #: Regenerated with the fixtures at contract 1.8. `60-min` ("Cialis
    #: Professional") and `346-min` ("Modvigil") came OFF -- both brands now
    #: read, and the list can only shrink by being earned. The two that remain
    #: return nothing at all rather than a fragment: the whole of `158-min`'s
    #: face comes back as "a Clonazepam", and `357-min`'s as the ingredient row
    #: and the unit count with no "Adderall" anywhere. Both wordmarks are white
    #: on a dark field, both measured 0.0% hidden.
    KNOWN_BRAND_MISREADS = {
        "158-min": "",             # of "Klonopin" -- not returned
        # `357-min` was here until contract 1.10 and came off by being earned:
        # "Adderall" now returns. It is the same carton whose INGREDIENT row
        # entered `KNOWN_OCR_MISSES` in the same contract, which is worth seeing
        # together -- drawing the C-II symbol below and right of that row cost
        # the reader one row on this face and gained it another.
        # CONTRACT 1.10. "Ritalin" is printed, is legible on the rectified face
        # at native scale, and did not move -- the fixture from before the marks
        # shows the identical layout. What changed is that two Novartis mark
        # fragments now sit on the board BESIDE it at the same height, and the
        # reader groups them with the row. This is the reader, on the project's
        # own test of looking rather than on the OCR return, and it is the price
        # of a decision rather than a defect: see 00_PROJECT_STATE/MARKS_DRAWN.md.
        "404-min": "",             # of "Ritalin" -- not returned
    }

    def test_the_brand_name_reads_on_every_SKU_in_the_sample(self):
        """Singled out because it is the field the Gemini engine invented.

        `reference_analysis.md` §7 caught that engine printing "Datels", a word
        appearing nowhere in any manifest. Whatever else a packshot gets wrong,
        the brand on the front face has to be the brand.

        `KNOWN_BRAND_MISREADS` is the exception list and it is not a skip list:
        a brand on it must STILL FAIL to read. One that starts reading has to
        come off, the same rule `test_the_known_miss_list_is_not_stale` applies
        to the other ratchet, so the list can only shrink by being earned.
        """
        for stem, webp, manifest, view in self.cases:
            with self.subTest(stem=stem):
                res = render_qa.check_image(webp, manifest, view)
                expected = manifest["label_content"]["brand_name_display"]
                got = res["fields"]["brand_name_display"]
                if stem in self.KNOWN_BRAND_MISREADS:
                    self.assertFalse(
                        got,
                        f"{stem}: brand '{expected}' now READS. Take it out of "
                        f"KNOWN_BRAND_MISREADS -- an exception nobody has to earn "
                        f"is an exception nobody checks.")
                    continue
                self.assertTrue(
                    got,
                    f"{stem}: brand '{expected}' not readable; flags={res['flags']}")


@unittest.skipUnless(os.environ.get("PHARMAGEN_SLOW_TESTS"),
                     "set PHARMAGEN_SLOW_TESTS=1 to re-render the fixture SKU")
@unittest.skipUnless(_HAVE_TESSERACT,
                     f"Tesseract unavailable: {render_qa._TESSERACT_ERROR}")
class TestOCRAgainstAFreshRender(unittest.TestCase):
    """The same assertions against output rendered now, so the committed
    fixture cannot drift away from what the renderer actually produces."""

    def test_a_fresh_render_of_the_fixture_sku_still_reads(self):
        import subprocess
        import sys
        out_dir = Path(render_qa.DEFAULT_PROCESSED_DIR)
        png = out_dir / "1-min.png"
        for stale in (png, png.with_suffix(".view.json")):
            if stale.exists():
                stale.unlink()
        proc = subprocess.run(
            [sys.executable, "-m", "src.blender_renderer", "--limit", "1",
             "--from", "1-min"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=600)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertTrue(png.exists(), "the render produced no PNG")

        manifest = json.loads(
            (Path(render_qa.DEFAULT_MANIFESTS_DIR) / "1-min.json")
            .read_text(encoding="utf-8"))
        view = render_qa.load_view(png)
        res = render_qa.check_image(png, manifest, view)
        self.assertGreaterEqual(res["found"], 3, f"flags={res['flags']}")

    #: Rendered once and read twice -- the sample is 28 Blender launches and
    #: two tests need the same result. Memoised on the class rather than in
    #: setUpClass so the cheap `1-min` test above is not made to wait for it.
    _FRESH = None

    @classmethod
    def _fresh_misses(cls, case) -> set:
        """Re-render the whole sample and score it. ~15 minutes."""
        if cls._FRESH is not None:
            return cls._FRESH
        import subprocess
        import sys
        from scripts.make_ocr_fixtures import sample_stems

        out_dir = Path(render_qa.DEFAULT_PROCESSED_DIR)
        misses = set()
        for stem in sample_stems():
            png = out_dir / f"{stem}.png"
            # Resume in Stage 2 is unconditional -- an existing PNG means done --
            # so the stale one has to go or nothing is re-rendered at all.
            for stale in (png, png.with_suffix(".view.json")):
                if stale.exists():
                    stale.unlink()
            proc = subprocess.run(
                [sys.executable, "-m", "src.blender_renderer", "--limit", "1",
                 "--from", stem],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=600)
            case.assertEqual(proc.returncode, 0, f"{stem}: {proc.stderr[-1500:]}")
            case.assertTrue(png.exists(), f"{stem}: the render produced no PNG")

            manifest = json.loads(
                (Path(render_qa.DEFAULT_MANIFESTS_DIR) / f"{stem}.json")
                .read_text(encoding="utf-8"))
            res = render_qa.check_image(png, manifest, render_qa.load_view(png))
            misses |= {(stem, f) for f, ok in res["fields"].items() if not ok}
        cls._FRESH = misses
        return misses

    def test_the_template_sample_fixtures_still_match_a_fresh_render(self):
        """Twenty-eight committed fixtures drift twenty-eight ways, not one.

        Re-renders the whole sample and re-runs the barrier's own assertion
        against the new pixels. A fixture set is only worth what it still
        represents -- and this gate is the reason we know the set had gone four
        contract phases stale while the suite reported green.
        """
        listed = (TestOCRBarrierOverTheTemplateSample.KNOWN_OCR_MISSES
                  | set(TestOCRBarrierOverTheTemplateSample.ROWS_THE_RENDER_HIDES))
        misses = self._fresh_misses(self)
        self.assertFalse(
            misses - listed,
            f"a fresh render reads worse than the committed fixtures: "
            f"{sorted(misses - listed)}")

    def test_the_fixtures_and_a_fresh_render_miss_exactly_the_same_rows(self):
        """Not merely "no worse" -- the SAME.

        The assertion above is one-sided: a fixture set that misses MORE than
        the renderer does passes it, and that is precisely the state a stale set
        arrives in. Both sides are read by the same `check_image` over the same
        manifests, so any difference is a difference in the pixels, and the
        committed WEBP is measured to score identically to the PNG it came from.

        That measurement is not free and it has been falsified TWICE, which is
        why the fixtures are lossless rather than merely high quality. At q92 it
        held until contract 1.9 moved `62-min`'s badge a few levels and took its
        unit count across Tesseract's boundary; the set went to q98, which
        disagreed with the PNG on none of the sample's 112 rows. Contract 1.10
        then put three rows on that boundary and q98 disagreed on all three, in
        BOTH directions -- and q100 disagreed on three as well, a different
        three. Quality is not the dial. Lossless disagrees on none, at 2.82 ->
        31.97 MB; `scripts/make_ocr_fixtures` carries the full measurement.

        The failure this test showed while that held is worth keeping: with the
        two sources disagreeing, NO ratchet list can satisfy both this gate and
        the fixture barrier, because one demands a row be listed and the other
        demands it be removed. An exception list would have hidden that; the
        equality assertion made it impossible to paper over.
        """
        fixture_misses = set()
        for stem, webp, manifest, view in self._fixture_cases():
            res = render_qa.check_image(webp, manifest, view)
            fixture_misses |= {(stem, f) for f, ok in res["fields"].items() if not ok}
        fresh = self._fresh_misses(self)
        self.assertEqual(
            fixture_misses, fresh,
            f"the committed fixtures and a fresh render disagree. Only in the "
            f"fixtures: {sorted(fixture_misses - fresh)}; only in the render: "
            f"{sorted(fresh - fixture_misses)}. Rebuild with "
            f"`python scripts/make_ocr_fixtures.py`.")

    @staticmethod
    def _fixture_cases():
        from scripts.make_ocr_fixtures import sample_stems
        out = []
        for stem in sample_stems():
            webp = FIXTURE_DIR / f"{stem}.webp"
            manifest = FIXTURE_DIR / f"{stem}.manifest.json"
            view = FIXTURE_DIR / f"{stem}.view.json"
            if webp.exists() and manifest.exists() and view.exists():
                out.append((stem, webp,
                            json.loads(manifest.read_text(encoding="utf-8")),
                            json.loads(view.read_text(encoding="utf-8"))))
        return out


if __name__ == '__main__':
    unittest.main()
