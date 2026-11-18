"""Which marks may be drawn, read from the file the owner signed.

`00_PROJECT_STATE/MARKS_DECISION.md` is the decision, and this module is the only
thing that reads it. It is deliberately parsed rather than copied into code: a
second list would drift from the signed one, and the drift would be silent and in
the direction of drawing more.

**The file's own rule is enforced here rather than merely written down.** It says
no code may run until Purpose, Basis and Scope are stated by the owner, so this
loader raises `SystemExit` when any of the three is blank. A build that would
reproduce another company's mark on the strength of an unsigned file stops
instead, by name.

Three things this module will not do, each because the file forbids it:

- **It enters no default.** A key absent from the tables is not allowed; a key
  present with anything other than `yes` is not allowed. There is no fallback.
- **It does not read `print_truth.json`.** That file records what a region IS;
  this one records what may be done with it, and conflating the two is how a
  classification would become a permission.
- **It carries no exception for a class name.** `59_Cialis secondary_1#0`, the
  Lilly holographic oval, is `n/a` in the table and therefore simply not
  allowed — not special-cased, just absent from the allowed set.
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DECISION_PATH = PROJECT_ROOT / "00_PROJECT_STATE" / "MARKS_DECISION.md"

#: The only value that permits anything. Written out rather than truthy-tested,
#: because `n/a` and a blank and a stray note must all mean "no".
ALLOWED = "yes"

_HEADER = {
    "purpose": r"\*\*Purpose the catalogue serves:\*\*(.*?)(?=\n\*\*|\Z)",
    "basis": r"\*\*Basis — authorisation, licence, or the reasoning relied on:\*\*(.*?)(?=\n\*\*|\Z)",
    "scope": r"\*\*Scope in one sentence:\*\*(.*?)(?=\n\*\*|\n---|\Z)",
}

#: A line that is only underscores, or empty, is the template's blank.
_BLANK = re.compile(r"^[\s_←A-Z]*$")


class MarksNotDecided(SystemExit):
    """The decision file is unsigned, and the file itself says that stops a build."""


def _header_block(text: str) -> dict:
    out = {}
    for name, pattern in _HEADER.items():
        m = re.search(pattern, text, re.S)
        value = (m.group(1).strip() if m else "")
        out[name] = "" if _BLANK.match(value) else value
    return out


def _rows(text: str):
    """Every markdown table row in the file, as a list of stripped cells."""
    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or set("".join(cells)) <= set("-: "):
            continue
        yield cells


def _decided(cell: str) -> bool:
    """`yes` and nothing else, with any emphasis markers stripped."""
    return cell.replace("*", "").strip().lower() == ALLOWED


class Decision:
    """The signed answers, and nothing derived from anything else."""

    def __init__(self, header: dict, holes: set, components: set, refused: set):
        self.purpose = header["purpose"]
        self.basis = header["basis"]
        self.scope = header["scope"]
        #: (sku stem, "role#i/hole#j") pairs approved for cutting.
        self.holes = holes
        #: (folder name, "role#i") pairs approved for drawing.
        self.components = components
        #: everything the file lists and refuses, kept so a caller can report
        #: what it declined rather than silently drawing less than expected.
        self.refused = refused

    def may_cut_hole(self, stem: str, hole_key: str) -> bool:
        return (stem, hole_key) in self.holes

    def may_draw_component(self, folder: str, key: str) -> bool:
        return (folder, key) in self.components

    def __repr__(self) -> str:
        return (f"<Decision {len(self.holes)} holes, {len(self.components)} "
                f"components, {len(self.refused)} refused>")


def load(path: Path = DECISION_PATH) -> Decision:
    """Parse the signed decision, or stop.

    Stops rather than returns empty, and the difference matters: an empty
    decision looks exactly like "the owner said no to everything", which is a
    valid outcome the file explicitly provides for. An unsigned file is not that
    outcome and must not be mistaken for it.
    """
    if not path.exists():
        raise MarksNotDecided(
            f"{path} is absent. It is the record of a decision only its owner "
            f"can make; no mark may be drawn without it.")
    text = path.read_text(encoding="utf-8")
    header = _header_block(text)
    missing = [k for k, v in header.items() if not v]
    if missing:
        raise MarksNotDecided(
            f"{path.name} has no {', '.join(missing)}. Those lines are the "
            f"authorisation and not paperwork: the per-entry answers say WHAT "
            f"may be drawn and the basis says whether it may be. An implementer "
            f"may not supply them, and this build stops rather than reading "
            f"their absence as permission.")

    holes, components, refused = set(), set(), set()
    for cells in _rows(text):
        who, key, decision = cells[0], cells[1], cells[-1]
        if "/hole#" in key:
            (holes if _decided(decision) else refused).add((who, key))
        elif re.fullmatch(r"[a-z_0-9]+#\d+", key):
            (components if _decided(decision) else refused).add((who, key))
    return Decision(header, holes, components, refused)
