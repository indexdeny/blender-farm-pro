"""`scripts/render_mark_evidence.py` shows, and must never decide or write.

Phase 1 of the marks question exists to put facts in front of the person who
decides. Two things would quietly turn it into something else: writing to the
labelling, and stating a verdict. Both are pinned here rather than trusted, the
same instrument that keeps `measure_hole_payoff.py` honest.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src.utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "render_mark_evidence.py"
INDEX = PROJECT_ROOT / "02_processing" / "marks_evidence" / "index.json"
TEMPLATES = PROJECT_ROOT / "Reference Templates"


class TestItNeverWritesTheLabelling(unittest.TestCase):

    def setUp(self):
        self.assertTrue(SCRIPT.exists(), f"{SCRIPT} is missing")
        self.src = SCRIPT.read_text(encoding="utf-8")

    def test_no_write_names_a_truth_file(self):
        """`print_truth` may appear only where the script READS it."""
        for line in self.src.splitlines():
            if "print_truth" not in line:
                continue
            self.assertNotRegex(
                line, r"write_text|write_bytes|\.save\s*\(|json\.dump|open\s*\([^)]*[\"'][wax]",
                f"a write names print_truth: {line.strip()!r}")

    def test_it_opens_nothing_for_writing(self):
        opens = re.findall(r"open\s*\([^)]*\)", self.src)
        bad = [o for o in opens if re.search(r"[\"'][wax]b?\+?[\"']", o)]
        self.assertEqual(bad, [], f"write-mode open() in render_mark_evidence.py: {bad}")

    def test_every_write_lands_under_the_evidence_directory(self):
        """The sheets and the index, and nothing anywhere else.

        Matched on the whole statement rather than on the receiver, because the
        receiver may be an expression: `(out_dir / "index.json").write_text(...)`.
        What every write must mention is a name rooted at the output directory.
        """
        writes = [ln.strip() for ln in self.src.splitlines()
                  if re.search(r"\.(?:save|write_text|write_bytes)\s*\(", ln)]
        stray = [w for w in writes
                 if not re.search(r"\bout_dir\b|\bsheet_path\b|\bsheet\b", w)]
        self.assertEqual(
            stray, [],
            f"render_mark_evidence.py writes somewhere that is not derived from the "
            f"output directory: {stray}. Every output belongs under "
            f"02_processing/marks_evidence/.")

    def test_it_does_not_import_the_labelling_writer(self):
        self.assertIsNone(
            re.search(r"^\s*(?:from|import)\s+scripts\.label_print\b", self.src, re.M),
            "render_mark_evidence.py imports label_print, which owns print_truth.json")

    def test_it_states_no_verdict(self):
        """The script measures structure; naming a decision is the person's job."""
        forbidden = ("container", "artwork", "allowed", "permit", "should_draw",
                     "recommend", "verdict", "decision")
        # The words may appear in prose; what may not appear is a field carrying one.
        emitted = re.search(r"index\.append\(\{(.*?)\}\)", self.src, re.S)
        self.assertIsNotNone(emitted, "index.append no longer looks as this test expects")
        keys = set(re.findall(r"\"(\w+)\":", emitted.group(1)))
        self.assertEqual(
            keys & set(forbidden), set(),
            f"the evidence index carries a verdict field {keys & set(forbidden)}; it may "
            f"carry what was MEASURED and never what should follow from it")


class TestTheEvidenceIsComplete(unittest.TestCase):

    def setUp(self):
        if not INDEX.exists():
            self.skipTest("marks evidence not generated yet")
        self.index = json.loads(INDEX.read_text(encoding="utf-8"))

    def test_every_mark_in_the_labelling_has_a_crop(self):
        want = set()
        for p in sorted(TEMPLATES.glob("*/print_truth.json")):
            t = json.loads(p.read_text(encoding="utf-8"))
            folder = p.parent.name
            for c in t["components"]:
                if c.get("class") == "mark" and not c.get("vanished"):
                    want.add((folder, c["key"]))
            for h in (t.get("holes") or []):
                if h.get("class") == "mark" and not h.get("vanished"):
                    want.add((folder, h["key"]))
        if not want:
            self.skipTest("no print_truth.json on disk (a clean clone has no images)")

        got = {(e["folder"], e["key"]) for e in self.index["entries"]}
        self.assertEqual(
            want - got, set(),
            f"marks with no evidence crop: {sorted(want - got)[:5]}. A decision may not "
            f"be taken on an entry nobody was shown.")

    def test_each_entry_carries_its_measured_structure(self):
        for e in self.index["entries"]:
            for key in ("islands", "solid_frac", "area_px", "reason"):
                self.assertIn(key, e, f"{e['key']} lost `{key}`")


if __name__ == "__main__":
    unittest.main()
