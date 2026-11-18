"""The signed decision, and the guard that makes an unsigned one stop a build.

`00_PROJECT_STATE/MARKS_DECISION.md` says no code may run until its Purpose,
Basis and Scope are written by the owner. That sentence is only worth what
enforces it, so `src/marks_decision.load()` raises on a blank one and these tests
pin that — along with the rule that `yes` is the only value permitting anything.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from src.marks_decision import DECISION_PATH, MarksNotDecided, load

SIGNED = DECISION_PATH.read_text(encoding="utf-8")


def _written(text: str) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "MARKS_DECISION.md"
    tmp.write_text(text, encoding="utf-8")
    return tmp


class TestTheSignedFileIsReadExactly(unittest.TestCase):

    def setUp(self):
        self.d = load()

    def test_the_counts_are_the_ones_the_owner_signed(self):
        """8 holes and 14 components.

        15 until `59_Cialis brand#9` was withdrawn on 26 August 2026: it reads
        "Lilly" and turned out to be the LETTERING OF the holographic sticker,
        which was never in scope. See the containment test below.
        """
        self.assertEqual(len(self.d.holes), 8)
        self.assertEqual(len(self.d.components), 14)

    def test_the_header_block_is_the_owners_words_and_not_empty(self):
        for name in ("purpose", "basis", "scope"):
            with self.subTest(name):
                self.assertTrue(getattr(self.d, name).strip())

    def test_the_basis_states_the_limit_the_answers_obey(self):
        """Not a style check: the basis and the answers must be one decision.

        Eleven rows were withdrawn because they carried a mark belonging to
        another company's product. If the basis ever stopped saying so while
        those rows stayed withdrawn, the file would be recording two different
        decisions and nobody could tell which one the build obeyed.
        """
        # Whitespace-normalised: the basis is wrapped prose and a line break
        # falling inside the phrase is not a change of meaning.
        flat = " ".join(self.d.basis.split())
        self.assertIn("belongs to the manufacturer", flat)
        self.assertIn("falsely associate", flat)
        for folder in ("133_Ambien", "60_Cialis_Professional"):
            allowed = [k for f, k in self.d.components if f == folder]
            self.assertEqual(allowed, [], f"{folder} is allowed a mark, but the "
                                          f"basis excludes marks belonging to "
                                          f"another company's product")

    def test_the_holographic_oval_is_refused_by_absence_and_not_by_name(self):
        """`n/a` is not `yes`, and that is the whole mechanism.

        The security feature must not be reachable, and it must not be
        unreachable because a class name was special-cased in code -- a
        later reclassification would then quietly re-open it.
        """
        self.assertNotIn(("59_Cialis", "secondary_1#0"), self.d.components)
        self.assertIn(("59_Cialis", "secondary_1#0"), self.d.refused)
        import src.marks_decision as m
        self.assertNotIn("secondary_1", Path(m.__file__).read_text(encoding="utf-8")
                         .split('"""', 2)[-1],
                         "the loader names the holographic oval in its code; it "
                         "must be refused by the table saying n/a, not by a "
                         "special case that a reclassification could bypass")

    def test_no_approved_mark_sits_inside_a_refused_one(self):
        """A security feature is refused whole, lettering included.

        `59_Cialis brand#9` reads "Lilly" and was approved as a wordmark until it
        was drawn and looked at: it is the LETTERING OF the holographic sticker,
        and the sticker -- `secondary_1#0` -- was always out of scope.
        Reproducing part of an anti-counterfeiting element is the act this driver
        already refuses for LOT, EXP, a product code and a 2D symbol.

        Pinned by bounding box rather than by name, so the rule survives a
        renumbering: u 0.677-0.804 and v 0.743-0.854 lie wholly inside u
        0.617-0.875 and v 0.650-0.948. It is the only such pair in the group.
        """
        self.assertNotIn(("59_Cialis", "brand#9"), self.d.components)
        self.assertIn(("59_Cialis", "brand#9"), self.d.refused)
        self.assertNotIn(("59_Cialis", "secondary_1#0"), self.d.components)

    def test_the_solidity_of_every_approved_mark_is_recorded(self):
        """The corrected fact, kept where a later reader will meet it.

        The owner was first told a mark would render as a silhouette and not a
        legible mark. That was wrong twice over -- `islands = 0` misses a glyph
        that TOUCHES the boundary, and a wordmark's silhouette is the wordmark --
        and the decision file now says so. This fails if that correction is ever
        quietly removed.
        """
        text = DECISION_PATH.read_text(encoding="utf-8")
        self.assertIn("THIS WAS", text)
        self.assertIn("solidity below 0.83", text)
        self.assertIn("is not an island, it is a notch", text)


class TestAnUnsignedFileStopsTheBuild(unittest.TestCase):
    """The file's own sentence, made executable."""

    def _blanked(self, label: str) -> str:
        return re.sub(rf"(\*\*{re.escape(label)}[^\n]*\*\*)(.*?)(?=\n\*\*|\n---)",
                      r"\1 _______________________", SIGNED, count=1, flags=re.S)

    def test_a_blank_basis_raises(self):
        path = _written(self._blanked(
            "Basis — authorisation, licence, or the reasoning relied on:"))
        with self.assertRaises(MarksNotDecided) as ctx:
            load(path)
        self.assertIn("basis", str(ctx.exception))

    def test_a_blank_purpose_raises(self):
        path = _written(self._blanked("Purpose the catalogue serves:"))
        with self.assertRaises(MarksNotDecided):
            load(path)

    def test_a_blank_scope_raises(self):
        path = _written(self._blanked("Scope in one sentence:"))
        with self.assertRaises(MarksNotDecided):
            load(path)

    def test_an_absent_file_raises_rather_than_returning_nothing(self):
        """An empty decision and an unsigned one are not the same outcome.

        "No to everything" is a valid answer the file explicitly provides for,
        and it looks exactly like an empty allowed set. An unsigned file must
        therefore stop rather than resemble it.
        """
        with self.assertRaises(MarksNotDecided):
            load(Path(tempfile.mkdtemp()) / "absent.md")

    def test_the_signed_file_still_loads(self):
        """Guards the four above: a loader that always raised would pass them."""
        self.assertGreater(len(load().holes), 0)


class TestOnlyYesPermitsAnything(unittest.TestCase):

    HEAD = SIGNED.split("### Per-entry decision")[0] + "### Per-entry decision\n\n"

    def _table(self, decision: str) -> Path:
        return _written(
            self.HEAD
            + "| sku | key | points | what it is | draw? |\n"
            + "|---|---|---|---|---|\n"
            + f"| 74-min | brand#0/hole#0 | +5.290 | oval | {decision} |\n"
            + "\n| folder | key | area % | rights holder | draw? |\n"
            + "|---|---|---|---|---|\n"
            + f"| 64_Kamagra | highlight#7 | 0.395 | device | {decision} |\n")

    def test_yes_permits(self):
        d = load(self._table("yes"))
        self.assertIn(("74-min", "brand#0/hole#0"), d.holes)
        self.assertIn(("64_Kamagra", "highlight#7"), d.components)

    def test_everything_else_refuses(self):
        for decision in ("no", "n/a", "", "maybe", "YES?", "yes, but only in print"):
            with self.subTest(decision=decision):
                d = load(self._table(decision))
                self.assertEqual(d.holes, set(),
                                 f"{decision!r} was read as permission")
                self.assertEqual(d.components, set(),
                                 f"{decision!r} was read as permission")

    def test_emphasis_around_yes_still_reads_as_yes(self):
        """The file writes some answers bold; that is formatting, not meaning."""
        self.assertIn(("74-min", "brand#0/hole#0"), load(self._table("**yes**")).holes)


class TestNothingUnapprovedIsEverDrawn(unittest.TestCase):
    """The decision is only worth what the shipped artefacts obey.

    Over every manifest in the catalogue and every spec in the group: each drawn
    mark must name a key the owner said `yes` to, and none of the refused keys
    may appear anywhere. This is the test that would fail if a class were ever
    renamed into permission, or if a fitter change started emitting by class.
    """

    @classmethod
    def setUpClass(cls):
        cls.d = load()
        cls.manifests = Path("04_passports/render_manifests")

    def _drawn(self):
        import json as _json
        from src.design_group import FOLDER_BY_STEM
        for f in sorted(self.manifests.glob("*.json")):
            m = _json.loads(f.read_text(encoding="utf-8"))
            folder = FOLDER_BY_STEM.get(f.stem)
            for mark in ((m.get("design") or {}).get("marks") or []):
                yield f.stem, folder, mark

    def test_every_drawn_mark_names_an_approved_key(self):
        for stem, folder, mark in self._drawn():
            key = mark.get("key")
            with self.subTest(sku=stem, key=key):
                approved = ((stem, key) in self.d.holes
                            if mark.get("source") == "hole"
                            else (folder, key) in self.d.components)
                self.assertTrue(
                    approved,
                    f"{stem} draws mark {key!r} ({mark.get('source')}) which is "
                    f"not `yes` in MARKS_DECISION.md. A mark may only be drawn "
                    f"because a person said so by name.")

    def test_no_refused_key_is_drawn_anywhere(self):
        """Compared as (folder, key) PAIRS, and the first version was not.

        A bare key is not an identity: `brand#8` is refused for `133_Ambien` and
        approved for `230_Slimex`, and `highlight#2` is refused for
        `60_Cialis_Professional` and approved for `155_Imovane`. Comparing key
        strings alone reported four breaches that were not breaches -- and the
        same mistake in the other direction would MISS a real one, since a
        refused key drawn on its own folder would look approved because some
        other folder approved that string.
        """
        drawn = {(folder, mark.get("key")) for _s, folder, mark in self._drawn()
                 if mark.get("source") == "component"}
        self.assertEqual(
            drawn & self.d.refused, set(),
            "a mark the owner refused is being drawn. The eleven withdrawn rows "
            "are marks belonging to another company's product, and the "
            "holographic oval is a security feature.")
        for folder in ("133_Ambien", "60_Cialis_Professional"):
            self.assertEqual(
                [k for f, k in drawn if f == folder], [],
                f"{folder} draws a mark; every one of its rows is `no`.")

    def test_the_catalogue_draws_exactly_what_was_approved(self):
        """Guards the two above: drawing nothing at all would pass them both."""
        drawn = list(self._drawn())
        self.assertEqual(len(drawn), len(self.d.holes) + len(self.d.components),
                         f"{len(drawn)} marks drawn against "
                         f"{len(self.d.holes) + len(self.d.components)} approved; "
                         f"an approved mark that stopped being emitted is as much "
                         f"a drift as an unapproved one that started.")

    def test_a_hole_sourced_mark_is_paired_with_a_cut_hole(self):
        """The scope sentence, checked on the artefact rather than the producer."""
        import json as _json
        from src.render_manifest import _reject_unpaired_marks
        for f in sorted(self.manifests.glob("*.json")):
            m = _json.loads(f.read_text(encoding="utf-8"))
            if not ((m.get("design") or {}).get("marks") or []):
                continue
            with self.subTest(sku=f.stem):
                _reject_unpaired_marks(m)


if __name__ == "__main__":
    unittest.main()


class TestWhatAMarkActuallyDraws(unittest.TestCase):
    """The fact the decision now rests on, kept re-checkable.

    An owner was first told a mark would render as "a silhouette, not a legible
    mark". That was wrong twice -- `islands = 0` misses a glyph that TOUCHES the
    boundary, and a wordmark's silhouette is the wordmark -- and the correction
    is what `scripts/measure_mark_shapes.py` exists to keep measurable rather
    than remembered.
    """

    @classmethod
    def setUpClass(cls):
        from scripts.measure_mark_shapes import BLOB_MIN, measure
        cls.rows = measure()
        cls.floor = BLOB_MIN

    def test_the_count_of_letterform_marks_is_stated_and_not_drifting(self):
        letters = [r for r in self.rows if r["solidity"] < self.floor]
        self.assertEqual(
            (len(letters), len(self.rows)), (11, 22),
            f"{len(letters)} of {len(self.rows)} emitted marks carry letterform "
            f"geometry; it was 11 of 22 when the owner confirmed them knowing "
            f"that. A change here means the catalogue now draws something the "
            f"decision was not taken against.")

    def test_the_threshold_sits_in_a_real_gap(self):
        """0.85 is where the distribution is empty, not where it looked tidy.

        Eleven marks sit at 0.907-1.000 and eleven at 0.190-0.825. A threshold
        chosen inside a crowd would make the count above meaningless.
        """
        s = sorted(r["solidity"] for r in self.rows)
        below = max(v for v in s if v < self.floor)
        above = min(v for v in s if v >= self.floor)
        self.assertGreater(above - below, 0.05,
                           f"the nearest solidities straddling {self.floor} are "
                           f"{below} and {above} -- too close for the split to "
                           f"mean anything")

    def test_the_viagra_oval_is_not_a_plain_oval(self):
        """The specific claim that was wrong, pinned so it cannot be re-made.

        `74_Viagra`'s Pfizer oval was described as rendering as an OVAL. It
        renders as an oval with the "fi" ligature notched out of it, which a
        plain ellipse's solidity -- 1.0 against its own hull -- cannot be.
        """
        row = next(r for r in self.rows
                   if r["sku"] == "74-min" and r["key"] == "brand#0/hole#0")
        self.assertLess(row["solidity"], 0.95)
