# Contract 1.9, rebuilt: a part's colour is a statement about its SURFACE

Measured 26 August 2026. Contract goes to **1.9**: `design.fields[].parts[].fill`
is required. `print_truth.json` was not touched, no corner moved, and **all 28
specs are byte-identical to their 1.8 selves once that one key is stripped** —
geometry, `type_rows` and `verification` all unchanged, across three full
re-fits.

The first attempt at this went in whole and came out whole (`PART_FILL.md`,
commit `01dd401`). It closed by naming two things a future attempt would need:
an estimator that knows where a part's rim is, and a comparison that survives the
palette moving underneath it. Both were then built —
[`PART_COLOUR.md`](PART_COLOUR.md), [`FIT_COLOUR.md`](FIT_COLOUR.md) — and this
is the attempt they made possible.

---

## The problem, restated with the instrument that measures it

A field's `fill` is `np.median(raw_px[cluster])`: the median of the whole cluster
`segment()` found. A part is one region of that cluster. `measure_fit_colour`
scores the declared colour against the pixels the part actually covers, with no
render in the comparison and **a floor of exactly zero on all 28 cartons**.

Under 1.8 it read **33 of 75 printed parts at or beyond `SAME_SURFACE_MAX`**,
across 20 of the 28 cartons. `152_Artvigil`'s `brand#1` is declared `#E05506`
and is `#2D3336` in the photograph, over 6.47% of the face, with a spread of
**0.0000** — a uniform region painted a colour from the other end of the palette.

---

## Three rules, and each was added because measurement demanded it

`_part_fills()` in `scripts/fit_design_spec.py`.

### 1. Merge first — a colour is a property of a SURFACE, not of a part

Parts whose own colours lie within `SAME_SURFACE_MAX` are one surface by this
project's own definition; it is the constant `segment()` merges two clusters at.
Without this the threshold below splits a single surface, because its parts land
on either side of it.

Measured over the group: **ten pairs across four cartons** were one surface in
the photograph and painted differently, worst `64_Kamagra`'s `highlight#1` and
`highlight#3` at **0.0039** apart and painted differently. Merging takes those
ten to **two**, and the two that remain are honest disagreement rather than
leakage: `59-min`'s and `62-min`'s brand parts are inside the threshold by the
full-region median and outside it by the eroded estimate, which is the better of
the two by a factor of four on a bench with known answers.

Merged colours combine by area. Re-estimating over the union is not the same
thing — the erosion asks the mask how thick it is, and a union of scattered
parts has no meaningful thickness.

### 2. Then threshold against the field

A surface within `SAME_SURFACE_MAX` of its field takes the field's value
**exactly**, not a near-duplicate. Emitting every part's own colour regardless is
what the rolled-back attempt did, and it is measured — twice now, once by that
attempt and once here — to send **eight of the 28 cartons** to "palette not
separable". Thresholded it is two.

### 3. And never emit a colour the vocabulary cannot hold

A candidate landing within `SAME_SURFACE_MAX` of the substrate or of any other
field's colour is refused, and the part keeps its field's value **even though
that value is known to be wrong for it**. This is the `SEPARABLE_MIN` collapse
`PART_FILL.md` asked for. It fires on exactly two cartons and both are named:

| carton | candidate | collides with | distance |
|---|---|---|---|
| `59_Cialis` | `highlight` `#D4C7AB` | its own **substrate** `#DDD1B9` | 0.0761 |
| `64_Kamagra` | `highlight` `#014035` | its own **brand** `#00463B` | 0.0335 |

**The price was measured before it was paid.** Emitting Kamagra's colour anyway
bought **0.0032** of `region_colour_gap` on that field and took its `render~spec`
IoU from 0.975 and 0.959 down to **0.633 and 0.340**. Two paints a classifier
cannot separate are not two paints.

Kamagra is also the case that says where the real defect is: **its brand and
highlight sit 0.0251 apart in the photograph and 0.1221 apart in the spec.** By
this project's own constant they are ONE surface — the segmentation split them
and the spec inherited the split — and no choice of fill repairs a partition.
That is a `segment()` question, and `segment()` is frozen by its labelling.

---

## What it costs and what it buys, on the target side

`measure_fit_colour`, which takes no render:

| | 1.8 | shipped |
|---|---|---|
| parts at or beyond `SAME_SURFACE_MAX` | **33** of 75 | **8** of 75 |
| mean gap | 0.1377 | 0.0319 |
| worst gap | 0.7389 | 0.1689 |
| instrument's own floor | 0.0000 | 0.0000 |

**Six of the eight that remain have no single colour to estimate** — their spread
is at or near their own gap, so no fill is right for them however it is
measured: `155-min`, `157-min` `type#1`, `304-min`, `357-min`, `404-min`,
`60-min`. **Two are the ones rule 3 deliberately withheld**: `59-min`'s
`highlight#2` at 0.1544 and `64-min`'s `highlight#0` at 0.0944.

That the six are the mixed ones was predicted from the 1.8 measurement before
the producer was switched, and it held.

---

## Stage A was landed separately and is provably neutral

The plumbing went in with every part's fill set to its field's — the value it
had always been painted — so that "did the wiring change anything" could be
answered apart from "did the measurement change anything".

| check | result |
|---|---|
| specs, stripping `part.fill` | **28 of 28 identical** |
| manifests, stripping the version and that key | **391 of 391 identical** |
| `design_coverage` | 99.18 / 52.79 / 95.36 / 0.76 — **not one figure moved** |
| `157-min` re-rendered under the new driver | **every IDAT chunk byte-identical**; only the `tEXt` Date and render-timing chunks differ |

---

## The render side

`design_qa`, over fresh renders of all 28. The judge was fixed **before** the
numbers arrived: `region_colour_gap` read as a DELTA is primary, because its
regions come from geometry and its exposure and black-lift terms are properties
of the metering and the rig, so between two renders of one carton they are common
and the difference is the paint.

| figure | 1.8 | rule 2 alone | + rule 1 | **shipped** | movement |
|---|---|---|---|---|---|
| `region_colour_gap_worst` | 0.1958 | 0.1491 | 0.1486 | **0.1489** | **0 rose**, 14 fell |
| `render~ref` | 0.9395 | 0.9295 | 0.9305 | **0.9382** | 6 up, 4 down |
| `field_iou_worst` | 0.9694 | 0.9373 | 0.9402 | **0.9691** | none down beyond 0.02 |
| `render~spec` | 0.9943 | 0.9868 | 0.9881 | **0.9943** | **none down at all** |
| cartons not separable | 0 | 2 | 2 | **0** | |

The primary criterion passes as written: **not one carton's colour gap rose**,
fourteen fell, and the largest falls are `157-min` −0.446, `272-min` −0.354 and
`362-min` −0.141.

The two intermediate columns are kept because they are the evidence for rules 1
and 3 rather than a search for a good number: rule 1 is worth +0.0010 of
`render~ref` and +0.0029 of `field_iou_worst` over rule 2 alone, and rule 3 is
worth +0.0077 and +0.0289 on top of that — almost all of it `64_Kamagra` and
`59_Cialis` returning to exactly their 1.8 figures.

### One carton loses beyond 0.02, and the criterion did not anticipate why

`362-min`'s `render~ref` falls 0.942 → 0.885. Its palette is separable, so the
explanation the criterion allowed for does not apply, and **the criterion as
written is not met — it was extended after the fact.** The evidence for
extending it, rather than an argument:

- the scored area is **bit-identical**, 1 335 854 px before and after;
- `render~spec` is unchanged, 0.9831 → 0.9830 — our render still draws what the
  spec says;
- its field's `region_colour_gap` improves **0.2493 → 0.0855**, the third
  largest gain in the group;
- and the share of the PHOTOGRAPH classified as that field rises from **15.69%
  to 21.33%** of the scored area.

The last line is the mechanism. The carton's small part is genuinely near-black
(`#200201`, and the photograph reads `#240200` there), so the palette gains a
dark entry — and a dark entry is a word for the reference's printed TYPE, which
the spec deliberately does not represent. `362-min` carries a print%/truth%
ratio of 5.6x, i.e. a lot of written-off print for that word to find. This is
the property `CLAUDE.md` already records — *a dark pixel where the spec draws
the substrate cannot be told from type* — reached by a new carton rather than a
new defect.

---

## The OCR gate moved one row each way, from one cause

`TestOCRAgainstAFreshRender` re-renders the whole 28-SKU sample and re-reads it,
and it is the only thing that notices the committed fixtures drifting. It
failed, which is what it is for.

- **`149-min` `dosage_display` started READING** — "200mg", reversed white out of
  its band, and it had been in `KNOWN_OCR_MISSES` since the list was written.
- **`149-min` and `344-min` `unit_count_display` stopped** — "30 Pills", the same
  string on the same photograph and two different carton shapes.

**One cause, two signs.** That band is `brand#1`, and contract 1.9 takes it from
its field's `#C84569` to its own `#7333B8`: **0.390 perceived luma to 0.291.**
Darker helps white type set ON it and hurts dark type set ACROSS it.

Filed as the reader and not the render, on the two checks `CLAUDE.md` requires
and not on the OCR return:

- **Looked at.** On `149-min`'s rectified face at native scale the row is dark on
  the board with the band's corner just touching the foot of the glyphs; every
  glyph is clear. (A 2x crop makes it look far worse, which is why the rule says
  the face and not a crop.) On `344-min` the row sits **entirely** on the board
  beside the small `#6009B0` square — nothing covers a glyph at all, which is the
  `365-min` pattern already recorded: a design edge ABUTTING a row perturbs the
  whole-face read.
- **`TestNoGridRowIsPrintedInInkItsOwnBackgroundHides` passes** on all 28. That
  guard judges the CAP BAND, and it says this row's cap band is on one surface.

So `KNOWN_OCR_MISSES` loses `("149-min", "dosage_display")` and gains the two
unit counts, and the fixtures were rebuilt afterwards rather than instead.

### And rebuilding falsified a claim the fixture set was resting on

With the fixtures rebuilt, the gate failed again on a third row — `62-min`'s
`unit_count_display`, this time **present in the fresh render and absent from the
fixture**. Both `make_ocr_fixtures.py` and the gate's own docstring asserted that
the committed WEBP at quality 92 "reads identically under Tesseract" to the PNG
it came from. That was true when it was written and is not true now: contract 1.9
moves that carton's badge from `#E9B44B` to `#EAB032`, a few levels, and the row
lands on Tesseract's decision boundary.

Re-measured over the sample's **112 rows**: q92 disagrees with the PNG on exactly
one, **q98 on none**. The fixtures are written at 98 and the set grows **1.87 MB
→ 2.79 MB**.

Worth keeping because it says what quality is and is not: **at q95 all four of
that carton's rows read, including two the PNG itself misses.** Quality is not a
dial that buys legibility — q98 and lossless both reproduce the PNG exactly, and
reproducing the PNG is the only property this fixture set is entitled to claim.

With the list corrected and the fixtures rebuilt at 98, `tests.test_render_qa`
passes whole under `PHARMAGEN_SLOW_TESTS=1` — 41 tests, including the gate that
re-renders all 28 and re-reads them.

---

## Two things the guard caught that were not part of the plan

**The calibration chart is a design block, and it carried no fills.** The
driver's new `SystemExit` refused it, so `calibrate_render.py` stopped producing
a curve — which is exactly what should happen, and it was found because
`driver_fingerprint()` then refused to let `design_qa` run against a stale one.
`scripts/calibrate_render.py` now states each patch's colour where the renderer
looks for it. Re-measured, the curve's `rows` are **numerically identical** to
the committed ones, so nothing in the comparison above is the curve moving.

**No measured row's ink changes polarity.** `_surface_fill` now reports the
PART's colour rather than its field's, so a row reversed out of a recoloured part
is set against what is actually printed under it. Eleven recoloured surfaces
carry a measured row; all eleven stay on the same side of `_reverse_ink`'s 0.5
threshold, the closest being `308-min`'s `brand#1` at 0.426 → 0.465.

---

## What is on disk

| path | what |
|---|---|
| `schemas/render_manifest.schema.json` | `manifest_version` 1.9; `parts[].fill` required |
| `scripts/fit_design_spec.py` | `_part_fills()` — the three rules |
| `05_assets/blender/render_driver.py` | per-part material, per-part surface fill, per-part block |
| `scripts/design_qa.py` | palette per painted colour, figures reported per field via `to_field` |
| `scripts/calibrate_render.py` | the chart's patches state their own colour |
| `scripts/measure_fit_colour.py` | `gap` and `gap_field` side by side — the before and after in one row |
| `tests/test_reference_templates.py` | the three rules, on synthetic masks with known colours |
| `tests/test_render_manifest.py` | a part with no `fill` is refused; the shipped manifests carry it |
| `tests/test_render_qa.py` | `KNOWN_OCR_MISSES` re-judged; the fixture-quality claim re-measured |
| `scripts/make_ocr_fixtures.py` | WEBP quality 92 → 98, with the measurement that forced it |
