"""The colour instrument that takes our render out of the comparison.

`measure_fit_colour` scores the fitter's declared fill against the pixels the
part actually covers in the photograph. Its whole claim to be readable is that
it has NO floor of its own -- the fill is a median of the photograph's raw
pixels, so measuring them back has to return it -- and these tests pin that
claim, the paint order the part map depends on, and the null-not-zero rule an
absent figure has broken twice in this project already.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from scripts.measure_fit_colour import (
    MIN_PART_PX, REPORT, part_index, score_part,
)
from src.design_group import FOLDER_BY_STEM


def _report() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _rect(u0, v0, u1, v1, fill="#FF0000") -> dict:
    return {"kind": "field", "area_pct": 1.0, "smoothness": 0.0, "holes": [],
            "fill": fill,
            "outline": [[u0, v0], [u1, v0], [u1, v1], [u0, v1]]}


class TestTheInstrumentHasNoFloorOfItsOwn(unittest.TestCase):
    """The one property that makes a gap readable as the fit's error.

    `spec["substrate"]` is `np.median(raw_px[substrate_cluster])` taken by
    `segment()`. Measuring that same cluster back through this instrument must
    return it exactly; anything left over would be the instrument's and would
    sit inside every field's number too.
    """

    def test_every_carton_recovers_its_declared_substrate_exactly(self):
        for row in _report()["rows"]:
            with self.subTest(sku=row["sku"]):
                self.assertIsNotNone(row["substrate_floor"],
                                     "no floor was measured for this carton")
                self.assertEqual(
                    row["substrate_floor"], 0.0,
                    f'{row["sku"]} does not recover its own substrate colour: '
                    f'{row["substrate_floor"]}. The headline compares against '
                    f'the RAW rectified face because that is the space the fill '
                    f'was measured in; a non-zero floor means something has been '
                    f'resampled or levelled back in, and every field gap on this '
                    f'carton carries it.')

    def test_the_levelled_reading_is_kept_beside_it(self):
        """It is worse, and it stays, so the illumination term stays visible."""
        rows = _report()["rows"]
        self.assertTrue(any(r["substrate_floor_levelled"] for r in rows),
                        "no carton reports a levelled floor; the column that "
                        "shows what flattening costs has gone")
        worst = max(r["substrate_floor_levelled"] for r in rows)
        self.assertGreater(
            worst, 0.0,
            "the levelled floor is zero everywhere, which would mean flattening "
            "is free -- it is not: it was measured at up to 0.0842, which is why "
            "it is not the headline")

    def test_the_report_covers_the_whole_group_and_nothing_else(self):
        self.assertEqual(sorted(r["sku"] for r in _report()["rows"]),
                         sorted(FOLDER_BY_STEM))


class TestAPartIsMeasuredWhereItIsVISIBLE(unittest.TestCase):
    """Paint order, which `spec_index` collapses and contract 1.9 needs kept."""

    def _spec(self):
        # Two parts in two fields; the second covers the first entirely.
        return {"substrate": "#FFFFFF", "face_aspect": 1.0, "fields": [
            {"role": "brand", "z": 0, "fill": "#FF0000", "coverage_pct": 25.0,
             "parts": [_rect(0.10, 0.10, 0.60, 0.60)]},
            {"role": "highlight", "z": 1, "fill": "#0000FF", "coverage_pct": 64.0,
             "parts": [_rect(0.05, 0.05, 0.85, 0.85)]},
        ]}

    def test_a_later_part_overwrites_an_earlier_one(self):
        idx, entries = part_index(self._spec(), 200, 200)
        self.assertEqual(len(entries), 2)
        self.assertEqual(int((idx == 0).sum()), 0,
                         "the first part is wholly covered by the second and "
                         "must contribute no pixels; measuring it anyway scores "
                         "paint that never reaches the carton")
        self.assertGreater(int((idx == 1).sum()), 1000)

    def test_an_uncovered_part_keeps_its_own_pixels(self):
        """Guards the test above: a map that is empty everywhere would pass it."""
        spec = self._spec()
        spec["fields"][1]["parts"] = [_rect(0.70, 0.70, 0.95, 0.95)]
        idx, _ = part_index(spec, 200, 200)
        self.assertGreater(int((idx == 0).sum()), 1000)
        self.assertGreater(int((idx == 1).sum()), 1000)


class TestAnAbsentFigureIsNullAndNeverZero(unittest.TestCase):
    """The failure this project has shipped twice, pinned at the third figure.

    `render_vs_reference` printed 0.0% for two cartons whose photograph had been
    orphaned by a rename, and `worst fld` printed 0.0% for three cartons that
    carry no field at all. A part with nothing left visible is the same shape of
    hole and must read as one.
    """

    def setUp(self):
        self.raw = np.zeros((40, 40, 3))
        self.flat = np.zeros((40, 40, 3))
        self.entry = {"field": 0, "role": "brand", "part": 0, "fill": "#FFFFFF",
                      "field_fill": "#FFFFFF", "kind": "field", "area_pct": 1.0}

    def test_a_part_with_no_visible_pixels_reports_null(self):
        row = score_part(self.raw, self.flat, np.zeros((40, 40), bool),
                         self.entry, (40, 40))
        self.assertEqual(row["px"], 0)
        for key in ("gap", "gap_levelled", "spread", "seen"):
            self.assertIsNone(row[key], f"{key} came back as a value for a part "
                                        f"that covers nothing")

    def test_a_part_just_under_the_floor_reports_null_too(self):
        sel = np.zeros((40, 40), bool)
        sel.flat[:MIN_PART_PX - 1] = True
        self.assertIsNone(score_part(self.raw, self.flat, sel,
                                     self.entry, (40, 40))["gap"])

    def test_a_part_just_over_the_floor_is_measured(self):
        """Guards the two above: a function that always returned None passes them."""
        sel = np.zeros((40, 40), bool)
        sel.flat[:MIN_PART_PX + 1] = True
        row = score_part(self.raw, self.flat, sel, self.entry, (40, 40))
        # White declared, black underneath: the largest gap there is.
        self.assertAlmostEqual(row["gap"], round(float(np.sqrt(3)), 4), places=3)


class TestSpreadSeparatesAWrongColourFromNoSingleColour(unittest.TestCase):
    """A fill is a claim that the part is one colour, and 1.9 can only fix the
    first of those two failures. `157-min` carries both: `type#0` is uniform and
    0.67 from its declared fill, `type#1` has a spread twice its own gap."""

    def _run(self, pixels):
        raw = np.zeros((40, 40, 3))
        sel = np.zeros((40, 40), bool)
        sel.flat[:len(pixels)] = True
        raw.reshape(-1, 3)[:len(pixels)] = pixels
        entry = {"field": 0, "role": "brand", "part": 0, "fill": "#000000",
                 "field_fill": "#000000", "kind": "field", "area_pct": 1.0}
        return score_part(raw, raw, sel, entry, (40, 40))

    def test_a_uniform_part_of_the_wrong_colour_has_a_gap_and_no_spread(self):
        row = self._run(np.tile([1.0, 0.0, 0.0], (200, 1)))
        self.assertAlmostEqual(row["gap"], 1.0, places=3)
        self.assertAlmostEqual(row["spread"], 0.0, places=3)

    def test_a_part_that_is_two_colours_shows_it(self):
        half = np.concatenate([np.tile([1.0, 0.0, 0.0], (100, 1)),
                               np.tile([0.0, 0.0, 1.0], (100, 1))])
        row = self._run(half)
        self.assertGreater(row["spread"], 0.5,
                           "a part split evenly between two saturated colours "
                           "reported almost no spread; the column cannot then "
                           "tell a mis-estimated fill from a part that has no "
                           "single colour to estimate")


class TestAgainstOneMeasuredCarton(unittest.TestCase):
    """`157_Valium`, reached by a second route and carrying contract 1.9 whole.

    `00_PROJECT_STATE/PART_COLOUR.md` records its `type#0` as `#083BC7` in the
    photograph while its FIELD is `#1F0A24`, measured through
    `region_colour_gap` and the part-colour bench. This instrument shares no code
    path with either and has to agree -- and under 1.9 it holds both halves at
    once: `gap_field` still says the field's colour is wrong for that part, and
    `gap` says the part's own declared colour is right.
    """

    def test_valium_type_0_is_the_blue_the_other_instruments_found(self):
        row = next(r for r in _report()["rows"] if r["sku"] == "157-min")
        part = next(p for p in row["parts"]
                    if p["role"] == "type" and p["part"] == 0)
        self.assertEqual(part["seen"], "#083BC7")
        self.assertEqual(part["field_fill"], "#1F0A24")
        self.assertGreater(
            part["gap_field"], 0.6,
            "the field's colour is no longer recorded as wrong for this part; "
            "that measurement is the reason contract 1.9 exists and it must not "
            "vanish just because the part is now painted correctly")
        self.assertLess(
            part["gap"], 0.02,
            "the part carries its own fill under contract 1.9 and it should "
            "match the photograph; a large gap here means the producer or the "
            "estimator has regressed")
        self.assertLess(part["spread"], 0.05,
                        "the part is uniform, which is what makes this a "
                        "mis-estimated fill rather than a mixed region")

    def test_the_parts_still_over_the_threshold_are_the_mixed_ones(self):
        """What 1.9 cannot fix, named rather than left to be rediscovered.

        A fill is a claim that a part is one colour. Where the spread is at or
        above the gap the claim is empty however the colour is estimated, and
        those parts stay over the threshold by construction -- five of the six
        that remain are exactly the five whose spread already exceeded their gap
        before the producer was switched.
        """
        over = [(r["sku"], p) for r in _report()["rows"] for p in r["parts"]
                if p["gap"] is not None and p["gap"] >= 0.08]
        self.assertLessEqual(len(over), 8,
                             f"{len(over)} parts are still beyond the threshold; "
                             f"before contract 1.9 it was 33, and a rise means "
                             f"the producer has regressed")
        mixed = [(s, p) for s, p in over if p["spread"] >= 0.5 * p["gap"]]
        self.assertGreaterEqual(
            len(mixed), len(over) - 1,
            "parts remain over the threshold that are NOT mixed regions: "
            + ", ".join(f'{s} {p["role"]}#{p["part"]} gap={p["gap"]} '
                        f'spread={p["spread"]}' for s, p in over
                        if (s, p) not in mixed))


if __name__ == "__main__":
    unittest.main()
