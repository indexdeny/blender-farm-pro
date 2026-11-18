# Changelog

All notable changes to **PharmaGen PRO** are documented here.
Format inspired by [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased] — The grid learns about marks, and a revert is undone — 28 August 2026

`_prepared_parts` now carries `design.marks[]`, so both the INK a row is set in
and the search that places it can see one. Closes the defect contract 1.10 left
open, and corrects the measurement that closed it the wrong way.

### Corrected
- **"Eight OCR rows lost against three gained" was the price of DRAWING the
  marks, not of moving the rows.** Both runs of the reverted attempt are on
  record: with the mover blind the gate lost **nine** against the same three. The
  grid fix recovered `157-min`'s unit count and cost nothing — worth one row, not
  minus five.
- **`221_Inderal` never moved.** It was named as the case to look at; measured on
  the scene dump, none of its rows so much as touches one of its marks.

### Measured
- A seeing mover relocates **exactly three rows** across 28 design cartons plus a
  generic one, all horizontally, with cap height, size, condensation and ink
  untouched. The other 26 scenes are bit-identical.
  `157-min` unit count 0.170 of the face left off the Roche hexagon (**reads
  now**), `230-min` dosage 0.070 out of the Neptune frame, `152-min` dosage 0.085
  off the swash.
- OCR **+1 row, none lost**. `TestNoGridRowIsPrintedInInkItsOwnBackgroundHides`
  goes 2 straddling rows -> **0**, so `KNOWN_STRADDLING` stays empty.
- The guard understates a COLOURED mark: it compares ink lightness against
  surface lightness, so `230-min`'s orange rule passes while visibly cutting the
  digits of "15mg". Caught by looking, not by the figure.
- Calibration re-measured (the driver changed, so its fingerprint had to):
  **rows numerically identical**, as at contract 1.9 — the chart carries no marks.
- `design_qa` barely moves and only on the three: group `render~spec` and
  `field_iou_worst` unchanged to six decimals, `render~ref` **0.939786 ->
  0.939750**. Label rows sit outside the scored area, so a row that moves is
  almost invisible to it.
- **One figure fell and it is named.** `157-min`'s `render~ref` 0.9967 -> 0.9957,
  its third field's IoU 0.79 -> 0.73 — our render prints type where the spec
  draws none, so moving dark glyphs moves which region they are classified into,
  the property this project already records as *a dark pixel where the spec
  draws the substrate cannot be told from type*. Against it, the same carton's
  **mark colour gap improves 0.1237 -> 0.0932**: with "30 Pills" off the hexagon,
  the mark's pixels are the mark's.

### Changed
- The two audiences were split behind a `with_marks` parameter, measured apart,
  and the parameter REMOVED once nothing took the other branch — the objection
  this project already records against the joint two-axis search. The reasoning
  stays in `_prepared_parts` and `_one_ink_serves`; the seam is one flag away.
- `tests/test_blender_carton.py`'s independent surface lookup drifted twice and
  is fixed: it read fields alone, and it took a FIELD's fill where contract 1.9
  made a part's its own. The 1.9 half is measured to change **nothing** today —
  none of the 8 parts that differ from their field lies under a label row.

## [Unreleased] — Contract 1.10: the marks a person approved — 27 August 2026

`design.marks[]` is required and usually empty. 22 marks across 12 of the 28
folders: the 8 holes and 14 components the owner listed `yes` in
[`00_PROJECT_STATE/MARKS_DECISION.md`](00_PROJECT_STATE/MARKS_DECISION.md).
Write-up in [`00_PROJECT_STATE/MARKS_DRAWN.md`](00_PROJECT_STATE/MARKS_DRAWN.md).

### Added
- `src/marks_decision.py` — the only reader of the signed file, and it makes
  that file's own rule executable: `MarksNotDecided` when Purpose, Basis or
  Scope is blank. `yes` is the only value that permits anything, tested against
  `no`, `n/a`, empty, `maybe`, `YES?`, `yes, but only in print`. No class name is
  special-cased, so the holographic oval is refused by its `n/a` row and a
  reclassification cannot re-open it. An ABSENT file raises rather than
  returning empty, because "no to everything" is a valid signed outcome.
- `design.marks[]` and `parts[].mark_holes`; `manifest_version` 1.9 -> 1.10.
- `_reject_unpaired_marks` refuses BOTH directions on write and on read.
- `scripts/measure_mark_shapes.py` — solidity of every emitted polygon.

### Corrected
- **"A silhouette, not a legible mark" was wrong, and an owner decided on it.**
  `islands = 0` misses a glyph that TOUCHES the boundary -- it is a notch and it
  survives the trace -- and a wordmark's silhouette IS the wordmark. 11 of the
  22 marks carry letterform geometry; `152_Artvigil`'s swash is 0.190 solid and
  `74_Viagra`'s oval 0.918 with the "fi" ligature notched out.
- Shown the drawn shapes, the owner withdrew `59_Cialis brand#9` -- it reads
  "Lilly" and is the LETTERING OF the holographic sticker, its bounding box
  wholly inside the sticker's -- and confirmed the rest. A security feature is
  refused whole, lettering included.

### Fixed
- **Five marks were painted solid where the carton prints an OUTLINE**, up to
  9.5x the ink they describe. `157_Valium`'s Roche mark inks 1 977 px and filled
  covered 16 619, declaring `#022E99` where the photograph read `#B8BEC3`. A mark
  now carries its own holes. All 22 fill 0.9-1.4x their ink.
- The substrate core excludes marks: `74_Viagra`'s oval is 0.0364 from its own
  substrate and was joining the illumination plane.
- Index-based figures exclude marks on both sides -- `230_Slimex` read 0.00%
  before, because its only content is two marks and the ground truth is keyed by
  field. `region_colour_gap` judges them instead; it needs no vocabulary.
- **The OCR fixtures are LOSSLESS, because q98 stopped reading like its own
  render.** Contract 1.9 measured q98 disagreeing with the PNG on none of the
  sample's 112 rows and the set was written at 98 on that evidence. Drawing the
  marks put three rows on Tesseract's boundary and q98 now disagrees on all
  three, in BOTH directions -- `230-min`'s ingredient and `357-min`'s brand are
  read by the render and lost by the encode, `357-min`'s ingredient is missed by
  the render and RECOVERED by it. Quality is not the dial: q100 disagrees on
  three as well, a different three. Lossless disagrees on none, at 2.82 ->
  **31.97 MB**. All 28 fixtures were verified to reproduce byte-for-byte from
  the renders on disk first, so this is the codec and not staleness.
- The disagreement made the ratchet lists unsatisfiable rather than merely
  wrong: `test_the_known_miss_list_is_not_stale` reads the fixture and demanded
  `357-min`'s ingredient be REMOVED while `test_..._still_match_a_fresh_render`
  reads the render and demanded it STAY. Two rows were briefly entered on the
  fixture's answer, which is the error the row-equality assertion exists to make
  impossible to paper over.

### Open
- **The label grid does not know marks exist and can print across one.**
  `157_Valium` sets "30 Pills" over the Roche hexagon. The fix was built and
  REVERTED: the OCR gate read eight rows lost against three gained, and
  `221_Inderal`'s "40mg" went from white on its band to dark on the band's edge.
  Separating `_surface_fill` (ink, useful) from `_clear_of_design` (movement,
  harmful) is the real work.

  **Closed below, and this reading of it was wrong** — kept because the entry it
  is written against shipped with it.

### Measured
- `render~ref` 0.9382 -> **0.9398**, 8 up and 0 down; `render~spec` 0.9943 ->
  0.9946, 0 down; `field_iou_worst` 0.9691 -> 0.9706.
- Index side: `pixel_agreement` 99.18 -> **99.27%**, `print_agreement` 52.79 ->
  **53.14%**, `truth_agreement` 95.36 -> **95.76%**, drawn-off-print 0.76 ->
  **0.72%**.
- **All 16 cartons carrying no mark moved by exactly zero on every figure.**
- The OCR barrier loses nine rows and gains three. Every one inspected on the
  rectified face; all glyphs legible, so filed as the reader.

## [Unreleased] — Contract 1.9: a colour is a statement about a SURFACE — 26 August 2026

`design.fields[].parts[].fill` is required. `print_truth.json` untouched, no
corner moved, and across three full re-fits **all 28 specs stay byte-identical to
their 1.8 selves once that one key is stripped** — geometry, `type_rows` and
`verification` all unchanged. Write-up in
[`00_PROJECT_STATE/SURFACE_COLOUR.md`](00_PROJECT_STATE/SURFACE_COLOUR.md).

The first attempt at this went in whole and came out whole (`PART_FILL.md`). It
closed by naming what a future one needed — an estimator that knows where a
part's rim is, and a comparison that survives the palette moving under it — and
both were built first (`PART_COLOUR.md`, `FIT_COLOUR.md`).

### Added
- `design.fields[].parts[].fill`, required, and `manifest_version` 1.8 → 1.9. A
  1.8 part read as 1.9 is not a part painted its field's colour, it is a part
  whose colour is unknown, so the version is pinned rather than the field
  defaulted.
- `_part_fills()` in `scripts/fit_design_spec.py` — **three rules, each added
  because a measurement demanded it.** Merge parts within `SAME_SURFACE_MAX`
  first; then threshold against the field; then refuse any colour landing within
  `SAME_SURFACE_MAX` of the substrate or another field.
- Per-part material, per-part `_surface_fill` and per-part colour block in
  `render_driver.py`, each raising `SystemExit` on a part with no `fill`.
- `design_qa`'s palette is now one entry per painted COLOUR, with `to_field`
  mapping every reported figure back to fields — which is what keeps
  `field_iou_worst` a statement about fields while the classifier works in
  colours. `palette_entries` names each index.
- `gap_field` beside `gap` in `measure_fit_colour`, so one row holds both the
  before and the after.
- Tests: the three rules on synthetic masks with known colours; a manifest part
  with no `fill` is refused; the shipped manifests carry it.

### Measured
- **33 of 75 parts → 8**, mean gap 0.1377 → 0.0319, worst 0.7389 → 0.1689. Six
  of the eight left are mixed regions with no single colour to estimate —
  predicted from the 1.8 measurement before the producer was switched, and it
  held — and two are what rule 3 deliberately withheld.
- Render side over fresh renders of all 28: `region_colour_gap` **0.1958 →
  0.1489 with not one carton rising**, `render~spec` unchanged at 0.9943,
  `field_iou_worst` 0.9694 → 0.9691, `render~ref` 0.9395 → 0.9382, and **zero
  cartons not separable** against the rolled-back attempt's eight.
- **Rule 1 exists because ten pairs across four cartons were one surface in the
  photograph and painted differently**, worst `64_Kamagra`'s `highlight#1` and
  `highlight#3` at 0.0039 apart. Merging takes it to two.
- **Rule 3's price was measured before it was paid**: emitting `64_Kamagra`'s
  colour anyway buys 0.0032 of `region_colour_gap` and costs `render~spec` IoU
  of 0.975 and 0.959, falling to 0.633 and 0.340.
- **`64_Kamagra` says where the real defect is.** Its brand and highlight sit
  **0.0251 apart in the photograph and 0.1221 apart in the spec** — one surface
  by this project's own constant, split by the segmentation and inherited by the
  spec. No fill repairs a partition.
- **One carton loses beyond 0.02 and the criterion did not anticipate why.**
  `362-min` falls 0.942 → 0.885 on `render~ref` with a separable palette, so the
  criterion as written was NOT met and was extended after the fact. Evidence:
  scored area bit-identical at 1 335 854 px, `render~spec` unchanged, its field's
  colour gap 0.2493 → 0.0855, and the share of the PHOTOGRAPH read as that field
  rising 15.69% → 21.33%. Its part is genuinely near-black, so the palette gains
  a dark entry — a word for the reference's printed TYPE, which the spec does not
  represent.
- Plumbing neutrality, landed separately on purpose: 28/28 specs and 391/391
  manifests identical stripping the version and the key, `design_coverage`
  unmoved on every column, and `157-min` re-rendered with every IDAT chunk
  byte-identical.

- **The OCR gate moved one row each way, from one cause.** `149-min`'s
  `dosage_display` started reading; `149-min` and `344-min`'s
  `unit_count_display` stopped. The band under both goes from the field's
  `#C84569` to its own `#7333B8` — 0.390 perceived luma to 0.291 — which helps
  white type ON it and hurts dark type ACROSS it. Filed as the reader on the two
  checks the project requires and not on the OCR return: looked at on the
  rectified face at native scale, and
  `TestNoGridRowIsPrintedInInkItsOwnBackgroundHides` passes on all 28. Fixtures
  rebuilt afterwards rather than instead.

### Fixed
- **`make_ocr_fixtures` wrote WEBP at quality 92 on a claim that stopped being
  true.** Both that script and the gate asserted q92 reads identically to the
  PNG; contract 1.9 moved `62-min`'s badge `#E9B44B` -> `#EAB032` and took its
  unit count across Tesseract's boundary. Re-measured over the sample's 112
  rows, q92 disagrees with the PNG on exactly one and **q98 on none**; the set
  grows 1.87 -> 2.79 MB. At q95 all four of that carton's rows read, including
  two the PNG itself misses — quality is not a dial that buys legibility.
- **The calibration chart is a design block and carried no fills.** The driver's
  new `SystemExit` refused it, so `calibrate_render.py` silently stopped
  producing a curve — caught only because `driver_fingerprint()` then refused to
  let `design_qa` run against a stale one. Patches now state their own colour;
  the re-measured curve's `rows` are numerically identical.
- `measure_fit_colour` read `part.get("fill", field["fill"])` — a silent
  substitution that would have scored a part with no colour as one that agrees
  with its field, i.e. reported the error it exists to find as absent.

## [Unreleased] — The colour figure with the render taken out — 26 August 2026

Nothing that is painted changed: contract stays at 1.8, and no spec, manifest,
render, `print_truth.json` or `design_qa.json` was written. Write-up in
[`00_PROJECT_STATE/FIT_COLOUR.md`](00_PROJECT_STATE/FIT_COLOUR.md).

### Corrected
- **`region_colour_gap` was published as a ranking of paint and it is not one.**
  It compares OUR RENDER against the photograph in raw values, so it carries the
  exposure difference, the rig's measured black lift, and the fit error. Split
  off the best neutral scale: `230_Slimex`'s headline 0.3652 is **0.0187** and
  the rest a 1.29× level; every substrate gap in the group above 0.26 is a level
  difference, while `151-min` also carries zero fields and reads 0.0713.
  `64_Kamagra`'s 0.128 chromatic residual is the lift — red 0.131 against a spec
  that says 0.000. As a before/after the exposure term cancels and the figure
  stands; as a ranking it misleads. The reading this file already carried for ΔC,
  arriving at a figure that shipped without it.
- Two findings survive and come out stronger: `157_Valium` 0.549, `272_Roche`
  0.512 — and on both **our render is four times closer to the spec than the
  spec is to the photograph.** The renderer obeyed; the fitter chose wrong.
- `segment()`'s docstring declared three return values and returns five.

### Added
- `scripts/measure_fit_colour.py` — the fitter's declared fill against the pixels
  the part covers, with no render in the comparison. A `fill` is
  `np.median(raw_px[cluster])` off the rectified photograph, so both sides are
  one measurement in one space: nothing to level, no curve, no lift. Whole group
  in 20 seconds. `--sku` prints and writes nothing.
- `part_index()` — `spec_index` kept per PART and in paint order, since contract
  1.9 is a statement about parts and a part under a later one must be scored on
  what remains visible.
- `spread` beside each gap — whether the part is one colour at all, which splits
  "the fitter chose wrong" from "there is no single right answer here".
- `tests/test_fit_colour.py` — the zero floor over the committed report, paint
  order, null-never-zero, and that `spread` separates the two failures.

### Measured
- **The floor is exactly zero on all 28.** Measuring the substrate cluster back
  returns `spec["substrate"]` to four decimals, and every spec carries exactly
  the rectification's own aspect so nothing is resampled.
- Getting there meant dropping the illumination flattening from the headline. The
  check: **a part that IS its own cluster has to read zero.** `64-min`'s
  `brand#0`, 32.6% of the face, read 0.0039 raw against 0.0950 levelled;
  `59-min`'s `highlight#0` 0.0068 against 0.2052. The plane is fitted over
  "wherever the spec draws no field", which on those cartons is the board plus
  everything the labelling wrote off. Kept as `gap_levelled`.
- **33 of 75 parts at or beyond `SAME_SURFACE_MAX`, on 20 of 28 cartons.**
  25 are uniform and simply wrong — `152-min`'s `brand#1` has spread **0.0000**
  over 6.47% of the face, declared orange, charcoal in the photograph. 5 have a
  spread at or above their own gap, where no fill is right however estimated.
- `157-min`'s `type#0` reads `#083BC7`, the same answer `PART_COLOUR.md` reached
  by two other routes that share no code with this one.
- **`149_Modalert` and `344_Modafinil_Generic` are one photograph**, byte for
  byte under two names, same corners, same spec. The 28 folders are **27
  distinct references** and every group mean counts that carton twice.

## [Unreleased] — Two instruments for the question 1.9 failed on — 25 August 2026

Nothing that is painted changed: contract stays at 1.8, `part.fill` was not
reintroduced, no spec, manifest, render or `print_truth.json` written, and every
prior field of `design_qa.json` is byte-identical. Write-up in
[`00_PROJECT_STATE/PART_COLOUR.md`](00_PROJECT_STATE/PART_COLOUR.md).

### Added
- `scripts/measure_part_colour.py` — four part-colour estimators and a synthetic
  bench with KNOWN answers at the sizes that occur, because a real part has no
  known colour and agreement with the cluster is the thing already shown wrong.
  Winner: erode by **0.35 of the part's own thickness**, 0.0020 mean error
  against the median's 0.0076, worst 0.0047 against 0.0453.
- `region_colour_gap` in `design_qa`, beside the existing fields and replacing
  none. Regions from `spec_index` — outlines, not colours — so the figure does
  not move when paint does. Inherits the fit error and says so.
- `tests/test_region_colour_gap.py` — invariance demonstrated rather than
  asserted: `spec_index` unmoved when one fill is brought within 0.001 of
  another, while the classified map drops below 95% agreement with the geometry.

### Measured
- **Thinness breaks the median, not smallness.** 0.0018 on a 0.16% blob, 0.0453
  on a 6px strip. Real thicknesses agree: erosion moves the 3.4px and 5.4px
  parts and leaves the 60.2px and 65.6px ones, whose distance from their cluster
  is a real difference in paint.
- **This corrects `PART_FILL.md`.** Erosion was recorded as "half working" and
  unable to tell rim from real; it separates them cleanly once thickness is
  measured. The earlier reading took closeness to the cluster as correctness.
  Consequently the rim explanation is too small to carry the 1.9 regression,
  whose cause is **not established** — the palette shift is the remaining
  candidate.
- **The new figure sees what the old ones hide.** `157_Valium`'s blue bar is
  painted near-black purple, 0.583 apart, where `render~ref` reads 99.5%. And
  `346_Modvigil` and `230_Slimex` score `render~ref` **1.000** carrying zero
  fields — one palette entry, everything classifies to it — while their board
  sits 0.37 from the photograph.
- Every existing boundary erosion in the tree (11, 19, 3, 3, 1) is applied to a
  large region; none was ever asked to work on a 0.16% part.

## [Unreleased] — Contract 1.9 built, measured and rolled back — 25 August 2026

The wide per-part-fill change was implemented in full and reverted. No code,
spec, manifest or figure carries anything from it; `print_truth.json` was never
touched. Suite green at 392. Full write-up appended to
[`00_PROJECT_STATE/PART_FILL.md`](00_PROJECT_STATE/PART_FILL.md).

### Measured
- **The plumbing is provably neutral.** Landed in two stages on purpose. With
  every part's `fill` set to its field's — the value it had always been painted —
  all 29 specs are byte-identical after stripping the new key, all 391 manifests
  move only by the version string and that key, and `design_coverage` over 28
  cartons moves on **no column at all**.
- **`design_coverage` moved by zero in Stage B as well**, exactly as predicted:
  its figures are field INDICES and colour never enters them. A part went from
  orange to charcoal and `truth_agreement` did not notice.
- **`design_qa` says the change does not pass.** Mean `render~ref` **0.9395 →
  0.9346**, 5 cartons improved, **9 regressed beyond the 0.02 rule**. Best
  `64-min` **+8.8** (0.890 → 0.978); worst `59-min` −7.7, `62-min` −6.8,
  `362-min` −5.8. Rolled back whole rather than tuned.
- **Why: small parts' medians carry their antialiased rim.** Large parts barely
  moved — Ritalin's 39.1% part by 0.000, Kamagra's 32.5% by 0.004 — while
  Ritalin's 0.42% part moved 0.182 and Cialis Professional's 0.16% part 0.259.
  Eroding the mask half works and cannot tell the two causes apart: it takes
  Ritalin's sliver 0.182 → 0.059, leaves Cialis Professional's genuinely
  different `highlight#1` at 0.290 → 0.286, and moves `64_Kamagra` — the one
  carton that gained — the wrong way.
- **And the deeper problem is structural.** `design_qa`'s palette is both the set
  of colours `rasterise` paints and the vocabulary both sides are classified
  against, so changing what a part is painted changes the classifier. Before and
  after are two instruments, not two renders. Not fixable with more care.

### Solid, and worth keeping in mind
- **A per-part palette must collapse at `SEPARABLE_MIN`.** One entry per part
  regardless left eight cartons "palette not separable": `221_Inderal`'s
  `highlight#2` sits **0.002** from its `highlight#0`, taking that carton's worst
  field to **0.0%** and `357_Adderall`'s `render~ref` to **37.8%** on renders that
  had not changed. Collapsing recovered Inderal to 89.3% / 93.3%.
- `64_Kamagra` **+8.8** is the one clean signal that the diagnosis underneath is
  right: its `highlight` parts sit 0.055–0.094 from the merged cluster colour and
  are large enough to measure without rim contamination.
- `scripts/calibrate_render.py` needed the new key too, and the schema test
  caught it — the chart is a design like any other.

## [Unreleased] — A part is painted its cluster's colour — 24 August 2026

Read-only. No code changed, no spec, manifest or figure changed,
`print_truth.json` untouched in all 28 folders. Write-up in
[`00_PROJECT_STATE/PART_FILL.md`](00_PROJECT_STATE/PART_FILL.md).

Set out to recover three components misfiled `unrepresentable` because `fill`
lives on the field and a part has none. The emission threshold was to come from
the distribution of part-versus-cluster colour distance. **There is no
threshold**, and the reason is that they are not three cases.

### Measured
- Over the 75 components classified `print`, the distance between a part's own
  colour (median of its RAW pixels, exactly how `segment()` measures a cluster's)
  and the colour it is painted runs 0.000 to **0.7389** in a smooth ramp with no
  gap. The largest is `152_Artvigil brand#1`, class `print` and shipping.
- **31 of 75 shipping parts — 41% — sit further from their paint than
  `SAME_SURFACE_MAX`**, the threshold at which this project already calls two
  clusters one surface. Their summed area is 109.6% of face-equivalents against
  446.5% for all printed parts, across **18 of 25 cartons**. Roughly a quarter of
  all printed design area is painted a colour that is not its own.
- Verified by looking, not by the number: Artvigil's dark charcoal S-curve is
  painted orange, Valium's bright blue bar near-black purple, Valium Brand's blue
  Roche hexagon dark navy. All three are class `print`.
- **Why nothing caught it.** `design_coverage.py` compares field INDICES, so a
  part painted orange where the reference is charcoal still agrees. `design_qa`
  classifies the render against the SPEC's own palette, so a render told to paint
  orange and painting orange scores a colour error of zero; only `render~ref`
  disagrees, thinly, over 18 cartons.
- Eleven sites read "what colour is this region", two of them not named in the
  brief: `measure_type_rows.py` and `type_qa.py` both pair a field's fill with a
  part's outline, and three sites decide a measured row's INK from it.

### Not done
- The narrow change the brief authorised does not exist. The honest shape is
  every part carrying its own measured fill, which is a re-measurement event for
  every colour figure on 25 cartons rather than 3. That is a scoping call, not a
  measurement, and the work stopped at the brief's own edge case.

## [Unreleased] — `unrepresentable` triaged — 24 August 2026

Read-only. Nothing reclassified, no spec, manifest or figure changed. Write-up in
[`00_PROJECT_STATE/UNREPRESENTABLE_TRIAGE.md`](00_PROJECT_STATE/UNREPRESENTABLE_TRIAGE.md).

### Measured
- **The class is four problems, not one**, taken from the reasons the labelling
  already carries: 19 components are photographic inserts (54.80% summed, almost
  all `346_Modvigil` and `230_Slimex`), 3 are continuous tone or pattern (21.18%,
  almost all `362_Hydrocodone`'s gradient panel), 3 were **merged into another
  cluster**, and 1 was lost to the simplify tolerance.
- **The three merged ones are misfiled.** Nothing about them is unrepresentable:
  each is a solid region of one colour, and what blocks them is that `fill` lives
  on the FIELD and a part has none — a teal Waklert badge that k-means put in the
  orange cluster traces perfectly and cannot be painted. All three are the
  product's own design (a brand badge, a do-not-substitute pictogram, a dosage
  box), so unlike the `mark` question there is no owner decision behind them.
- **Recovering them is worth about +0.04 group points, and that is a fact about
  the instrument rather than about the change.** `unrepresentable` sits outside
  the scored area, so these cost nothing today and can earn nothing; drawing all
  three correctly moves their own cartons +1.005, +0.069 and +0.003. For a badge
  covering 5.08% of a printed face. `truth_agreement` is blind to whatever the
  labelling wrote off, the same shape of error as `pixel_agreement` being nearly
  a statement about the board.
- **Reclassifying without being able to draw costs `150_Waklert` thirty points**
  — 96.8% to 66.8%. The reclassification and the ability to draw are one change,
  the same pairing as a `mark` hole and its mark.
- The screen that does see these already exists: printed cluster against labelled
  print. The three blank cartons report `truth_agreement` as **null** and an
  infinite ratio rather than a number, which is why they are visible at all.

## [Unreleased] — What the marks actually are — 24 August 2026

Phase 1 of the marks question: establish what the 35 `mark` entries contain
before anyone is asked to decide about them. Read-only. Nothing reclassified, no
spec, manifest or figure changed, `print_truth.json` byte-identical in all 28
folders. Evidence in
[`00_PROJECT_STATE/MARKS_EVIDENCE.md`](00_PROJECT_STATE/MARKS_EVIDENCE.md).

### Added
- `scripts/render_mark_evidence.py` — crops every `mark` component and live
  `mark` hole out of the rectified face at magnification, plain beside the
  classified pixels tinted, and measures each region's internal structure.
  `tests/test_mark_evidence.py` pins that it writes only under its evidence
  directory, opens nothing for writing, never imports `label_print`, carries no
  verdict field in its index, and that every mark in the labelling has a crop —
  a decision may not be taken on an entry nobody was shown.
- `00_PROJECT_STATE/MARKS_DECISION.md` — the decision template, facts filled and
  **the decision column deliberately empty**. It is the owner's to complete; a
  blank is not an answer and the implementer stops on one.

### Measured
- **All eight `mark` holes are solid.** `islands = 0`, `solid_frac = 1.000` on
  every one. Since `trace_holes()` keeps no islands, a cut `mark` hole can only
  ever become a filled outline: the "Pfizer" script inside Viagra's and Ativan's
  ovals is not separated by the segmentation and would not appear in a render.
  What is being decided is whether to draw the silhouette, not whether to
  reproduce the artwork.
- 92% of the +9.937 is those two ovals — +5.290 and +3.865. The rest totals
  +0.782, and Adderall's two Shire fragments are worth −0.001 and −0.002.
- Held out of the branding question by name: `357-min`'s **C-II schedule
  symbol** (a regulatory marking, not a trademark) and `59_Cialis`'s **Lilly
  holographic oval** (an anti-counterfeiting feature, and a component, so it
  carries none of the figure).

### Not done
- Phase 3 — `design.marks[]`, the paired hole rule and the driver — is blocked on
  `MARKS_DECISION.md` being filled in by a person. No code was written against it.

## [Unreleased] — The hole ceiling — 24 August 2026

The tooling migration closed with the observation that the whole 6.8-point gap
between "outer ring only" and "every hole cut" belongs to holes, and that ten of
the group's holes are cut. This priced the rest. Nothing was reclassified; no
spec, manifest or figure changed. Full write-up in
[`00_PROJECT_STATE/HOLE_CEILING.md`](00_PROJECT_STATE/HOLE_CEILING.md).

### Added
- `scripts/measure_hole_payoff.py` — cuts each hole alone and re-scores
  `truth_agreement`, which needs no render. `behind` is computed once per part
  and each hole is then a masked substitution, so pricing all 239 costs one
  `segment()` per folder. It answers what a cut would be WORTH and never whether
  to make it: `tests/test_hole_payoff.py` pins by static scan that it writes only
  its own report, opens nothing for writing, never imports `label_print`, and
  that every class in the report is a join onto the hand-made labelling.
- `scripts/measure_face_resolution.py` and
  `TestTheFaceResolutionCeilingIsDeclared` — the real size of every reference
  face, and the six folders below 350px named. A declaration, not a gate: they
  keep their specs and go on rendering.

### Measured, and no action taken
- **The 228 filled holes are worth +10.920 points excluding `lettering`, and 91%
  of that is `mark`.** Two holes carry +5.290 and +3.865 — Viagra's and Ativan's
  Pfizer ovals — with Inderal's LCI roundel third. Cutting a `mark` hole while
  drawing nothing into it shows board through our field in the shape of another
  company's logo, which is the act contract 1.8 already refuses for another
  company's lettering. **Outside every third party's branding the reachable
  figure is +0.983 points over 22 holes**, 23 of the 29 non-lettering holes worth
  under 0.1 each. Below the threshold set before measuring, so the
  re-classification pass was not run.
- What it opens is not an engineering decision: a `mark` hole and a `mark`
  component are one decision, the 27 components are already labelled for
  `design.marks[]`, and cutting the hole *as part of drawing the mark* is
  coherent. Worth the +9.937, blocked on reproducing third-party trademarks.
- **The face resolution ceiling.** `OUT_WIDTH` is 1100 whatever the photograph,
  so `357_Adderall`'s 134x172 face is enlarged 8.21x and `SIMPLIFY_TOLERANCE`
  works out at 0.13 of a source pixel there.

### Fixed
- Three counts of the group's holes disagreed — 242 entries in the truth files,
  239 in the partition, 238 in `CLAUDE.md`. The difference is three `74_Viagra`
  holes flagged `"vanished": true`, labelled against the corners `6d37b89`
  corrected and kept rather than deleted so the disappearance stays visible.
  Stated in the report and in `CLAUDE.md` instead of being re-derived next time.

## [Unreleased] — Tooling migration — 24 August 2026

Four installed-but-unwired libraries were to be brought into the design-transfer
chain, one at a time, each with a measured delta. Three of the four are still
unwired and now for a recorded reason. Full evidence in
[`00_PROJECT_STATE/TOOLING_MIGRATION.md`](00_PROJECT_STATE/TOOLING_MIGRATION.md);
the baseline every "before" column is read from is
`00_PROJECT_STATE/baseline_2026-08-24/`.

Each bullet is one measuring event, and the negative results are kept
deliberately — the cost of this work was mostly in establishing what does *not*
help, and deleting that leaves the next attempt to pay it again.

### Added
- **The Cycles compute device is stated rather than inherited.**
  `setup_render()` never assigned `scene.cycles.device`, so the device was
  whatever the process started with — and Blender accepts more than one
  `--python`, so a script running ahead of the driver could move an entire
  render onto the GPU with nothing in the log to say so. New
  `blender.device` / `device_backend` / `denoising_device` in `config.yaml`,
  a `setup_device()` that raises `SystemExit` on an unavailable back-end rather
  than falling back, and a `device` block in `--dump-scene` read back off the
  scene rather than echoed from the flags. **Pixel-neutral: `max_channel_delta
  = 0`** against the baseline render, confirmed three ways.
- `scripts/probe_render_device.py` — measures whether a device change moves the
  picture. `scripts/probe_partition_shift.py` — measures whether a segmentation
  change invalidates the hand-made labelling. Both kept as instruments.
- `src/vectorise.py` and 18 tests — the rejected tracer, kept unwired as the
  only implementation of two SVG parsing traps, and now guarded by tests that
  fail if anything imports it.

### Measured and rejected
- **GPU rendering.** OptiX sampling 1.17–1.45× faster and up to 43 levels apart
  on 0.2–0.9% of pixels; CUDA 1.18–1.45× and up to 23 levels on 0.2–0.7%; GPU
  denoising up to **5.4×** and up to 43 levels on **14–18%** of pixels. None
  reproduces the CPU image, so none was enabled. The cheap win and the expensive
  change are the same setting.
- **vtracer as the design tracer.** Wired in, it took the group's
  `truth_agreement` **95.36% → 94.19%**, with `304_Sonata` −17.4 and
  `155_Imovane` −5.7 points. **The premise did not reproduce**: the "0.954
  against 0.888" that motivated the work is the *same polyline* scored two ways
  — every hole cut (0.9536) against the outer ring alone (0.8855). Like for
  like vtracer is worse on both footings (0.8649 and 0.9236), on 75 of 75
  components, at every one of eight parameter settings tried. The 0.954 is
  unreachable regardless: it needs every hole cut, which contract 1.8 forbids.
- **Perceptual colour in the segmentation — both events.** Replacing the
  lightness estimator (`rgb.max(-1)` is V of HSV, not a lightness) moved the
  partition on **21 of 28** folders; clustering in OKLab instead of sRGB moved
  it on **27 of 28**. Neither reached a figure, because both fail the
  precondition every figure rests on: `print_truth.json` keys 661 hand-made
  classifications to `role#i`, and both halves of that key are outputs of the
  partition. **The segmentation is frozen by its labelling**, and improving it
  costs a deliberate manual re-classification of 28 folders, not a code change.

### Fixed
- **`render_calibration.json` carried one stale row.** It was written at
  `68961a6` and `74_Viagra`'s face corners changed at `6d37b89`, after it — so
  its chart was built from a carton that no longer existed. Re-measured:
  `colour_residual_median` 0.0230 → 0.0149, worst 0.0585 → 0.0406, and in
  `design_qa` that carton's second field went from matching its own photograph
  on 0.312 of its pixels to 0.806. The other 27 rows came back byte-identical.
- **`00_PROJECT_STATE/design_qa.json` retaken** against the current driver and
  the fresh calibration. One row of 28 moved — the same `74-min`.

### Known gaps, named not fixed
- `calibrate_render.driver_fingerprint()` hashes the driver file plus the render
  settings, but **not the manifest the chart is built from**, so a carton
  reshape or a corner re-set leaves it matching while the curve goes stale. This
  is how the row above went unnoticed. Repairing it means covering the design
  spec's own `verification` block or the manifest hash.
- `config.yaml`'s three device keys are welded to the driver's flag defaults by
  a test rather than passed on the command line; wiring them through needs one
  line in `src/blender_renderer.py`.

## [v1.0.1] — Patch — June 2026

### Fixed
- **Declared the missing `pydantic` runtime dependency** in `requirements.txt`.
  `pydantic` is required by Stage 1 (`schemas/common.py`, via `pharma_pkg`
  routing) but was absent from the dependency list, so a from-scratch install
  per the README would fail Stage 1 with `ModuleNotFoundError`. Found by a
  clean-machine reproducibility test. No pipeline/architecture/logic change — a
  pure packaging fix (SemVer patch).

## [v1.0.0] — Initial Production Release — June 2026

**PharmaGen PRO — Version 1.0 — Production Release.**

### Highlights
- **391 SKU rendered** to PNG; **389 delivered** as final WEBP assets (`output/`).
- **Unified Pipeline** — one entry point (`main.py`) over three stages (passports → render → final images).
- **Resume** — interruption-safe; re-running continues without duplicating work.
- **QA** — rule-based verifier plus a unit-test suite.
- **WEBP** — final assets at 1600×1600, ≤500 KB.
- **CLI** — `--full` / `--passports-only` / `--render-only` / `--process-images-only` with `--resume`, `--limit`, `--from`, `--headless`, `--debug`, `--config`.
- **Documentation** — architecture, ADRs, audits, deployment, operations, disaster recovery, backup, dependency inventory, acceptance test, design rationale, and a business/CRM brief.
- **Production Ready.**

### Release composition
This release groups four hardening phases (see the corresponding commits):
1. **Architecture Unification** — `main.py` + `config.yaml` + `src/` package + back-compat shims; stale absolute paths fixed.
2. **Repository Cleanup** — `scripts/`, archival `trash/`, bilingual README, Mermaid diagrams, repo audit.
3. **Production Hardening** — Bus Factor / Production Readiness / CRM Readiness audits, ADR-001..006, project history.
4. **Operations Documentation** — deployment, operations, disaster recovery, backup, dependency inventory, acceptance test, design rationale, business value & integration.

### Known limitations
- Rendering is browser-driven (Gemini RPA): requires a logged-in session, runs non-headless, and is single-threaded.
- Rendered images are **non-deterministic**; `output/` is the system of record (not reproducible by re-running).

## [0.x] — Pre-release development — May–June 2026

Foundational development (squashed into a single baseline commit): OCR/CV
groundwork, the passport compiler, the template system, renderer experiments,
the Gemini RPA renderer, and catalogue work (P20–P22) that rendered all 391 SKU.
See [PROJECT_HISTORY.md](PROJECT_HISTORY.md) for the full narrative.
