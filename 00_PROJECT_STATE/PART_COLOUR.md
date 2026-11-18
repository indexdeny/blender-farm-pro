# Two instruments the next attempt needs, built and validated separately

Measured 25 August 2026, from commit `01dd401`. **Nothing that is painted
changed.** Contract stays at 1.8, `part.fill` was not reintroduced, and no
`design_spec.json`, manifest, render or `print_truth.json` was written. Every
prior field of `design_qa.json` is byte-identical to the baseline.

Contract 1.9 was rolled back for two reasons (`PART_FILL.md`): the colour of a
part was taken as the median of its pixels, and the figure judging the result was
computed against a palette made of the very paints being changed. This builds one
instrument for each, and — deliberately — validates them without letting either
stand as evidence for the other.

---

## Phase 0 — Discovery

### Every existing boundary exclusion is applied to a LARGE region

| site | radius | applied to |
|---|---|---|
| `calibrate_render.ERODE_PX` | 11 | a chart patch, ~1/24 of the face |
| `design_qa._substrate_core` | 19 | the substrate, 87–96% of the face |
| `design_qa._seam` | 3 | 1 px either side of a region boundary |
| `fit_design_spec._despeckle` | 1 erode + 1 dilate | filaments |
| `measure_type_rows.BOUNDARY_ERODE_PX` | 3 | inside a type block |

The idiom exists five times over and **not one instance was ever asked to work on
a part covering 0.16% of a face.** That is the gap, and it explains why reaching
for "just erode it" produced a constant that could not serve both ends.

### `render_vs_reference` is palette-dependent by construction

    render_vs_reference = _agreement(o_idx, ref_idx, scored & ref_mask, len(palette))

Both index maps are produced by classifying against `palette`, and `palette` is
built from the spec's fills. Change a fill and the classifier changes. That is
the whole of the second problem, in one line.

`design_coverage.spec_index()` is the opposite: it builds its region map from
`part_region`, that is from **outlines**. It already existed and is what the new
figure is built on.

---

## Phase 1 — the estimator

### The bench, and why it is synthetic

A real part has no known colour, so accuracy cannot be measured on one. The bench
composites a KNOWN part colour against a KNOWN neighbour, blurs the seam at
`RIM_PX = 2.0` — the width `CLAUDE.md` already records the glyph-rim exclusion
saturating at, "which is all it is: the face is rectified to 1100px from a 2048
render" — and then **assigns each blurred pixel to the nearer paint**, because
that is what k-means does and it is why a real mask carries rim pixels at all.

Three shapes at the sizes that occur (a ~39% field, a thin strip, a ~0.16% blob)
against four neighbours (lighter and darker, far and near in colour).

### Result: adaptive erosion, by a factor of four

| candidate | mean error | worst | do-no-harm worst |
|---|---|---|---|
| `median_full` — the baseline | 0.0076 | 0.0453 | 0.0000 † |
| **`median_eroded_adaptive`** | **0.0020** | **0.0047** | 0.0055 |
| `modal_peak` — mean-shift | 0.0105 | 0.0247 | 0.0068 |
| `unmixed` — reject the mixtures | 0.0073 | 0.0453 | 0.0039 |

† by construction: the five do-no-harm parts were selected as those where the
median already equals the cluster colour, so that column means nothing for the
baseline and everything for the other three. All three pass the 0.01 bar.

`median_eroded_adaptive` erodes by 0.35 of the part's own thickness
(`2·area/perimeter`, the figure `_simplify_to_a_region` already reaches for),
so it takes the same FRACTION off a 39% field and a 0.16% sliver instead of the
same number of pixels.

`unmixed` — reject pixels lying on the segment between the part and a neighbour,
the per-pixel form of `palette_on_line` — was the candidate this was expected to
need, and it is not better than the median. On a thin strip it rejects so much
that it falls back to its own provisional colour.

### The bench fails the median in exactly one place, and that place is the point

`median_full` scores 0.0018 on the 0.16% blob and **0.0453 on the 6px strip**.
So the median is not broken by small parts. It is broken by **thin** ones.

### Which corrects a reading in `PART_FILL.md`

That document records erosion "half working" — helping `404_Ritalin`'s part,
leaving `60_Cialis_Professional`'s `highlight#1` alone, and moving `64_Kamagra`'s
the wrong way — and concludes it cannot tell the two causes apart. Measured
thickness says otherwise:

| part | area % | thickness px | what erosion did |
|---|---|---|---|
| `60_Cialis_Professional` `highlight#12` | 0.16 | **3.4** | 0.259 → 0.137 |
| `404_Ritalin` `highlight#1` | 0.42 | **5.4** | 0.182 → 0.059 |
| `64_Kamagra` `highlight#3` | 0.97 | 8.7 | 0.064 → 0.083 |
| `150_Waklert` `brand#1` | 5.08 | 21.1 | — |
| `60_Cialis_Professional` `highlight#1` | 1.68 | **60.2** | 0.290 → 0.286 |
| `152_Artvigil` `brand#1` | 6.49 | **65.6** | — |

Erosion moves the thin parts and leaves the thick ones. **That is correct
behaviour, not confusion**: a 60px-thick part has almost no rim, so its median
was already right and its distance from the cluster is a real difference in
paint. The earlier reading treated *closeness to the cluster* as correctness —
which is the thing this whole line of work established to be wrong.

**So the rim explanation for the contract-1.9 regression is now too small to
carry it.** The median's error on the bench averages 0.0076, and adaptive erosion
would have moved only the thin parts. What actually caused nine cartons to
regress is not established, and the most likely remaining candidate is the
palette shift — which is what the second instrument exists to remove.

---

## Phase 2 — the figure that survives the palette moving

`region_colour_gap`, added **beside** the existing fields and replacing nothing.
Regions come from `spec_index` — geometry. Inside each, both sides are measured
and differenced, both levelled on the substrate. No classification, no palette,
no nearest-colour anything.

What it inherits, stated rather than discovered later: the regions are the
spec's, and the spec approximates the reference to `spec~ref` (95–100%). It is a
measurement inside the spec's idea of where things are.

### Invariance is demonstrated, not asserted

`tests/test_region_colour_gap.py`. Two fields, two rectangles; one fill is moved
to within **0.001** of the other, outlines untouched.

- `spec_index` is byte-identical before and after.
- The classified map is **not**: through a deterministic 0.010 wobble standing in
  for render and photograph noise, nearest-colour recovers the geometry at
  >99% when the paints are far apart and **<95%** when they are 0.001 apart.

The second half is what makes the first mean anything. It also reproduces in
miniature what was measured on the group: `221_Inderal` carries two paints 0.002
apart, and splitting them took that carton's worst field to 0.0% and
`357_Adderall`'s `render~ref` to 37.8% on renders that had not changed.

A first version of this test classified the CLEAN rasterisation and failed —
correctly. With no noise, nearest-colour separates paints a thousandth apart
perfectly, so nothing moves. The collapse is noise crossing a small gap, and a
demonstration without noise demonstrates nothing.

### What it sees on the first run

Every prior field of `design_qa.json` unchanged across all 28 cartons; the new
field present on all 28. Ranked by the new figure, the top of the table has
almost nothing to do with the old one:

| sku | `render~ref` | `dC worst` | **`gap worst`** | what it is |
|---|---|---|---|---|
| `157-min` | 0.995 | 0.168 | **0.583** | the bright blue bar painted near-black purple |
| `272-min` | 0.914 | 0.109 | **0.500** | the blue Roche hexagon painted dark navy |
| `346-min` | **1.000** | 0.117 | **0.378** | no fields at all — this is the BOARD |
| `230-min` | **1.000** | 0.128 | **0.365** | no fields at all — this is the BOARD |
| `340-min` | 0.947 | 0.116 | 0.299 | |
| `64-min` | 0.890 | 0.174 | 0.291 | |

Two findings fall out immediately.

**It sees the mispainted parts the old figures hide.** `157_Valium`'s `type#0` is
`#083BC7` in the photograph and painted `#1F0A24` — 0.673 apart — and
`render~ref` reads **99.5%** on that carton. The new figure reads 0.583 on that
region.

**And it catches a perfect score on a blank carton.** `346_Modvigil` and
`230_Slimex` carry zero fields, so their palette is one entry, everything on both
sides classifies to it, and `render~ref` is **1.000** by construction — while
their board differs from the photograph by 0.37. This is the same shape of error
`CLAUDE.md` already records for `pixel_agreement` ("`155-min`, `304-min` and
`308-min` each scored a perfect 1.0000 while carrying zero fields"), arriving at
a second figure and found by an instrument built for something else.

---

## What is on disk

| path | what |
|---|---|
| `scripts/measure_part_colour.py` | four estimators, the synthetic bench, the group run |
| `00_PROJECT_STATE/part_colour.json` | the bench table and every part through every candidate |
| `scripts/design_qa.py` | `region_colour_gap` added beside the existing fields |
| `tests/test_region_colour_gap.py` | invariance, and the demonstration that the old path moves |
| `00_PROJECT_STATE/baseline_2026-08-24/*.pre_part_colour.json` | the before |

Neither instrument is wired into `fit()`. The estimator is chosen and measured;
the figure is computed and reported. Reintroducing contract 1.9 is a separate
decision, and it now has something to be judged by.
