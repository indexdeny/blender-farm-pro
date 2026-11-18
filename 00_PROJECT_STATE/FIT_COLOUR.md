# The colour figure with the render taken out

Measured 26 August 2026, from commit `c807ee4`. **Nothing that is painted
changed.** Contract stays at 1.8, no `design_spec.json`, manifest, render or
`print_truth.json` was written, and `design_qa.json` is untouched.

`00_PROJECT_STATE/PART_COLOUR.md` closed by saying contract 1.9 could be
re-attempted because there was now something to judge it by. That was
`region_colour_gap`, and this document is the measurement that says it is not
enough — and the instrument that is.

---

## What `region_colour_gap` actually contains

It takes its regions from `spec_index`, i.e. from outlines, so it does not move
when paint does. That property holds. But it compares **our render** against the
photograph in raw values, and a raw difference between a render and a photograph
is not a colour error. Splitting each gap into the best neutral scale and the
remainder:

| sku | substrate gap | of it, colour | what the rest is |
|---|---|---|---|
| `230-min` | 0.3652 | **0.0187 (5%)** | the photograph is 1.29x darker |
| `346-min` | 0.3783 | 0.1493 (40%) | half exposure, half a cool board |
| `340-min` | 0.2988 | 0.0304 (10%) | exposure |
| `64-min` | 0.2906 | 0.0492 (17%) | exposure |
| `357-min` | 0.2667 | 0.0210 (8%) | exposure, our render 0.67x — the other way |

**Every substrate gap in the group above 0.26 is a level difference.** The
control was already in the table and went unread: `151-min` also carries zero
fields and reads 0.0713, so a one-entry palette does not produce a large gap by
itself.

This is the reading `CLAUDE.md` already records for ΔC — *"a neutral scale is an
exposure, not a colour"* — arriving at a figure that was published without it.

**Levelling it away does not work either.** A gain cannot represent the rig's
black lift, which is a measured constant of 0.133–0.141: referred to its own
substrate, `357-min`'s second field goes 0.0096 → **0.4951**, and `64-min`'s
`field0` 0.1585 → 0.2568. The lift is also the whole of that carton's apparent
colour error — red at 0.131 against a spec that says 0.000.

### Two findings survived, and they came out stronger

| sku | gap | levelled | render→spec | spec→photograph |
|---|---|---|---|---|
| `157-min` `field1` | 0.5834 | 0.549 | 0.168 | **0.663** |
| `272-min` `field0` | 0.4999 | 0.512 | 0.109 | **0.456** |

On both, **our render is four times closer to the spec than the spec is to the
photograph.** The renderer obeyed; the fitter chose wrong. Which is contract
1.9's thesis, now resting on a decomposition rather than on one conflated
number.

---

## The instrument: `scripts/measure_fit_colour.py`

A field's `fill` is `np.median(raw_px[cluster])`, taken off the rectified
photograph by `measure_reference_face.segment()`. So the declared paint and the
photograph are **the same measurement in the same space**. Nothing needs
levelling, no curve applies, there is no lift, and no render needs taking. What
is left is exactly the quantity contract 1.9 changes: the fill is the
**cluster's** median while the region it paints is one **part**.

Regions come from `part_index()`, which is `spec_index` kept per part and in
paint order, so a part lying under a later one is scored on the remainder that
actually reaches the carton.

It runs the whole group in **20 seconds** and renders nothing.

### Its floor is measured, and it is exactly zero

Measuring the substrate cluster back has to return `spec["substrate"]`. On all
28 cartons it does, to four decimals. There is no resampling term either: every
one of the 28 specs carries exactly the rectification's own aspect, so the
figure reads the photograph's own pixels. **A gap is the fit's, with nothing of
the instrument's in it.**

Getting there meant removing something. The first version compared against the
face with its illumination divided out, which put the plane's own error into the
headline. The check that caught it: **a part that IS its own cluster has to read
zero.**

| part | share of face | raw | levelled |
|---|---|---|---|
| `64-min` `brand#0` | 32.6% | **0.0039** | 0.0950 |
| `59-min` `highlight#0` | 14.7% | **0.0068** | 0.2052 |

The plane is fitted over "wherever the spec draws no field", which on those
cartons is the board **plus everything the labelling declined to represent**.
Its floor ran to 0.0842 — at the threshold the figure is judged against. The
levelled reading stays in the report as `gap_levelled`, beside the headline and
never in place of it, so the illumination term is visible rather than assumed
away.

An earlier floor was worse still and is worth recording, because it is the same
mistake one level up: taken over `spec_index == SUBSTRATE` — board plus every
letterform, object and photograph — it read **0.3442** on `64-min`, 3.6 times
that carton's worst finding, and 0.2738 on `346-min`, where the spec draws
nothing at all so the entire printed face went into the floor.

---

## What it finds

**33 of 75 parts sit at or beyond `SAME_SURFACE_MAX`, across 20 of the 28
cartons.** The threshold is reused deliberately: 0.08 is the distance at which
`segment()` merges two clusters as one surface, so a part beyond it differs from
its declared fill by more than the amount that would have made them different
surfaces in the first place.

| sku | floor | worst | mean | over | worst part |
|---|---|---|---|---|---|
| `152-min` | 0.0000 | **0.7389** | 0.2972 | 2 | `brand#1` `#E05506` → `#2D3336` |
| `157-min` | 0.0000 | **0.6735** | 0.2598 | 2 | `type#0` `#1F0A24` → `#083BC7` |
| `150-min` | 0.0000 | 0.5666 | 0.2364 | 2 | `brand#1` `#AE6335` → `#235359` |
| `149-min` | 0.0000 | 0.5427 | 0.4060 | 3 | `brand#2` `#C84569` → `#600BB0` |
| `344-min` | 0.0000 | 0.5427 | 0.4060 | 3 | `brand#2` `#C84569` → `#600BB0` |
| `272-min` | 0.0000 | 0.4330 | 0.4330 | 1 | `brand#0` `#09517A` → `#0178E1` |
| `365-min` | 0.0000 | 0.3706 | 0.2045 | 2 | `brand#1` `#FD7902` → `#F91B0B` |
| `308-min` | 0.0000 | 0.3595 | 0.2741 | 2 | `brand#1` `#01898F` → `#019F36` |
| `362-min` | 0.0000 | 0.3269 | 0.3066 | 2 | `brand#1` `#6A072D` → `#240200` |
| `74-min` | 0.0000 | 0.2970 | 0.1512 | 1 | `brand#1` `#012958` → `#2B2A97` |

Full table in `00_PROJECT_STATE/fit_colour.json`.

`157-min`'s `type#0` reads `#083BC7`. `PART_COLOUR.md` recorded that same part as
`#083BC7` through `region_colour_gap` and the part-colour bench, which share no
code path with this. Two routes, one answer.

### `spread` separates two failures that 1.9 treats alike

A fill is a claim that the part is one colour. Reported beside each gap is the
part's own spread (median absolute deviation, scaled), and it splits the 33:

- **25 are uniform and simply wrong** — spread under half the gap. `152-min`'s
  `brand#1` is the extreme: spread **0.0000** over 6.47% of the face, declared
  orange, and charcoal in the photograph. These are what contract 1.9 exists
  for.
- **5 have a spread at or above their own gap** — `404-min` `highlight#1`
  (0.1689 / 0.1880), `304-min` `highlight#0` (0.1510 / 0.1511), `357-min`
  `highlight#1` (0.1382 / 0.2839), `155-min` `highlight#0` (0.1104 / 0.2074),
  `157-min` `type#1` (0.1019 / 0.2334). **No fill is right for these**, however
  the colour is estimated. A per-part fill would move them and not fix them.
- 3 sit between.

That distinction did not exist before. `measure_part_colour.py` chose an
estimator; this says which parts an estimator can help at all.

---

## Two cartons are one photograph

`149_Modalert` and `344_Modafinil_Generic` hold the **same image file**, byte for
byte — SHA-256 `49349a4244ba7d53…`, 42 764 bytes, under two names — with the
same hand-set corners and the same fitted spec. Their rows here are identical to
four decimals, which is what drew attention to it.

`344`'s own metadata says so plainly (`"product_name": "Modalert 200 (Sun
Pharma)"`), and `CLAUDE.md` already records that its photograph is a Modalert
pack. What is not recorded is the consequence: **the group's 28 folders are 27
distinct references**, and every group-level mean counts that carton twice.
Small, and it should not be found again by surprise.

---

## What this does not do

- **It is not wired into `fit()`.** Nothing is fixed by it; it is a judge.
- **It inherits the outlines.** Regions are the spec's, and the spec
  approximates the reference. This is a measurement inside the spec's idea of
  where things are.
- **It says nothing about our render.** That is the point — but it means a
  carton can pass here and still render wrong, and `render~spec` remains the
  figure for that.
- **It does not touch the five mixed parts.** Naming them is all it does.

---

## What is on disk

| path | what |
|---|---|
| `scripts/measure_fit_colour.py` | the instrument; `--sku` prints and writes nothing |
| `00_PROJECT_STATE/fit_colour.json` | every part of every carton |
| `tests/test_fit_colour.py` | the zero floor, paint order, null-not-zero, spread |
| `scripts/measure_reference_face.py` | `segment()`'s docstring said three return values and returns five |
