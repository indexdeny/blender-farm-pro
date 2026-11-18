"""`scripts/measure_hole_payoff.py` measures, and must never classify.

The script answers one question -- what cutting a hole would be worth -- and the
whole design of Phase 1 rests on it never answering the other one. Whether a
hole is a `window` is a judgement about what is printed on somebody else's
carton; `404_Ritalin`'s 72 holes spell that manufacturer's brand and dose, and
they are large, so any ranking by payoff puts them near the top. A script that
ranks holes by payoff AND proposes a class is a machine for turning lettering
into windows, which is the exact act contract 1.8 exists to refuse.

So two properties are pinned here rather than trusted:

  1. the script writes to its own report and to nothing else -- in particular
     never to a `print_truth.json`;
  2. every class in the report is the class the truth file already carried, so
     the report is a join and not an opinion.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src.utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "measure_hole_payoff.py"
REPORT = PROJECT_ROOT / "00_PROJECT_STATE" / "hole_payoff.json"
TEMPLATES = PROJECT_ROOT / "Reference Templates"


class TestItNeverWritesTheLabelling(unittest.TestCase):
    """A static scan, the same instrument that keeps `src/vectorise.py` unwired."""

    #: Every write primitive Python offers that could reach a file, as it would
    #: appear in source. `open` is matched separately because its mode is what
    #: decides, and a read is legitimate.
    WRITE_CALLS = re.compile(
        r"\.write_text\s*\(|\.write_bytes\s*\(|\.write\s*\(|"
        r"json\.dump\s*\(|shutil\.copy|shutil\.move|os\.replace|os\.remove|"
        r"\.unlink\s*\(|\.rename\s*\(", re.M)

    #: The one write the script is allowed. Anything else is a finding.
    ALLOWED_WRITE = "Path(args.out).write_text("

    def setUp(self):
        self.assertTrue(SCRIPT.exists(), f"{SCRIPT} is missing")
        self.src = SCRIPT.read_text(encoding="utf-8")

    def test_the_only_write_is_its_own_report(self):
        found = [m.group(0) for m in self.WRITE_CALLS.finditer(self.src)]
        # The allowed call contributes exactly one `.write_text(`.
        self.assertIn(self.ALLOWED_WRITE, self.src,
                      "the script no longer writes its report the way this test expects; "
                      "re-read it before relaxing the check")
        self.assertEqual(
            found, [".write_text("],
            f"measure_hole_payoff.py performs writes beyond its own report: {found}. "
            f"It may not write to print_truth.json under any circumstances -- the "
            f"labelling is the most expensive artefact in this project and the "
            f"script exists precisely so that a person, not a number, edits it.")

    def test_it_opens_nothing_for_writing(self):
        opens = re.findall(r"open\s*\([^)]*\)", self.src)
        bad = [o for o in opens if re.search(r"[\"'][wax]b?\+?[\"']", o)]
        self.assertEqual(bad, [], f"write-mode open() in measure_hole_payoff.py: {bad}")

    def test_it_does_not_import_the_labelling_writer(self):
        pattern = re.compile(r"^\s*(?:from\s+scripts\.label_print\b|"
                             r"import\s+scripts\.label_print\b)", re.M)
        self.assertIsNone(
            pattern.search(self.src),
            "measure_hole_payoff.py imports label_print, which owns print_truth.json "
            "and whose --init MERGES old classes onto new components")


class TestTheReportIsAJoinAndNotAnOpinion(unittest.TestCase):
    """Every class in the report came from the truth file, unchanged."""

    def setUp(self):
        if not REPORT.exists():
            self.skipTest(f"{REPORT.name} not generated yet")
        self.report = json.loads(REPORT.read_text(encoding="utf-8"))

    def test_every_class_matches_print_truth(self):
        truth_class = {}
        for folder in sorted(TEMPLATES.glob("*/print_truth.json")):
            t = json.loads(folder.read_text(encoding="utf-8"))
            for hole in (t.get("holes") or []):
                truth_class[(folder.parent.name, hole["key"])] = hole.get("class")
        if not truth_class:
            self.skipTest("no print_truth.json on disk (a clean clone has no images)")

        mismatched = []
        for carton in self.report["cartons"]:
            for hole in carton["holes"]:
                want = truth_class.get((carton["folder"], hole["key"]))
                if hole.get("class") != want:
                    mismatched.append((carton["folder"], hole["key"],
                                       hole.get("class"), want))
        self.assertEqual(
            mismatched, [],
            f"hole_payoff.json carries a class the truth file does not: {mismatched[:5]}. "
            f"The report must be a join onto the hand-made labelling, never a proposal.")

    def test_no_row_carries_a_recommendation(self):
        forbidden = {"suggested", "suggested_class", "recommend", "recommended_class",
                     "should_cut", "proposed", "verdict"}
        offenders = set()
        for carton in self.report["cartons"]:
            for hole in carton["holes"]:
                offenders |= (set(hole) & forbidden)
        self.assertEqual(
            offenders, set(),
            f"hole_payoff.json rows carry {offenders}; this report states what a cut "
            f"would be worth and never whether to make it")

    def test_lettering_is_reported_apart_from_the_headline(self):
        """The figure the gate reads must exclude what a person already called type."""
        s = self.report["summary"]
        for key in ("potential_all_pts", "potential_excluding_lettering_pts",
                    "by_class", "enumeration_floor_note"):
            self.assertIn(key, s, f"summary lost `{key}`")
        self.assertNotEqual(
            s["potential_all_pts"], None,
            "the headline potential is missing; the Phase 1 gate cannot be read")

    def test_already_cut_holes_are_exactly_the_windows(self):
        cut = [(c["folder"], h["key"], h["class"])
               for c in self.report["cartons"] for h in c["holes"] if h["already_cut"]]
        wrong = [x for x in cut if x[2] != "window"]
        self.assertEqual(
            wrong, [],
            f"a hole is recorded as already cut without being classified `window`: {wrong}. "
            f"Contract 1.8 cuts that class and no other.")


if __name__ == "__main__":
    unittest.main()
