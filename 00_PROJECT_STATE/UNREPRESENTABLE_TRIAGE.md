# `unrepresentable` is four different problems, and the metric cannot see three of them

Measured 24 August 2026, from commit `bf1309c`. Read-only: nothing was
reclassified, no spec, manifest or figure changed.

Three cartons — `151_Provigil`, `230_Slimex`, `346_Modvigil` — render with no
design at all, and 26 components across the group carry the class
`unrepresentable`. This triages them, because "the vocabulary cannot hold it" has
been standing in for four distinct causes with four different answers.

---

## The four causes

Taken from the `reason` each component already carries in `print_truth.json`.

| cause | components | area, summed | what it would need |
|---|---|---|---|
| photographic insert | **19** | 54.80% | an image texture — and a question of its own |
| continuous tone or pattern | 3 | 21.18% | a gradient / pattern primitive |
| **merged into another cluster** | **3** | **5.48%** | **a per-part fill — no new primitive** |
| lost to the simplify tolerance | 1 | 0.31% | a per-part tolerance |

### Photographic insert — 19 components

`346_Modvigil` carries fifteen of them, "photographic insert of a surfer in a
wave", together 35.38% of its face; `230_Slimex` three, "photographic insert of a
person", 19.03%. A flat region cannot be a photograph, and the primitive that
could is an image texture — which would mean lifting a photograph out of the
reference and printing it on our carton. That is a different question from
drawing a coloured field, and it is not answered here.

### Continuous tone or pattern — 3 components

`362_Hydrocodone`'s `secondary_1#0` is 20.23% of its face: *"printed vertical
gradient on the panel; a flat fill cannot carry it."* `365_Tapentadol` carries two
columns of *"fine green checkerboard"*. These are the case a gradient or pattern
primitive would actually serve, and they are the honest argument for building
one.

### Merged into another cluster — 3 components, and these are misfiled

The reason names the **model**, not the shape:

| sku | key | area % | reason |
|---|---|---|---|
| `150-min` | `brand#1` | 5.08 | teal Waklert badge merged into the orange cluster; one fill per cluster cannot express it |
| `158-min` | `highlight#1` | 0.28 | red do-not-substitute pictogram merged into the green cluster |
| `64-min` | `highlight#19` | 0.12 | salmon dosage box merged into the dark-teal cluster |

Nothing about these shapes is unrepresentable. Each is a solid region of one
colour. What blocks them is that **`fill` lives on the field and a part has
none** — the schema gives a part `outline`, `holes`, `area_pct` and `smoothness`,
and its colour comes from the cluster it landed in. A teal badge that k-means put
in the orange cluster can be traced perfectly and cannot be painted.

All three are the product's own design: a brand badge, a dispensing pictogram, a
dosage box. No third party's mark is involved, so unlike the `mark` question
this one has no owner decision behind it.

---

## What fixing it would be worth, and why the answer is not what it looks like

`unrepresentable` sits **outside the scored area**. `truth_from_labels()` scores
the board plus the components a person called `print`, so these three cost
nothing today and can earn nothing either. Recovering one means reclassifying it
`print` — which brings its pixels into the scored area — and then drawing it.
Three states have to be separated:

| carton | component | area % | now | reclassified, **not** drawn | reclassified **and** drawn |
|---|---|---|---|---|---|
| `150-min` | teal Waklert badge | 5.08 | 0.9676 | **0.6678** (−29.98) | 0.9776 (**+1.005**) |
| `158-min` | do-not-substitute pictogram | 0.28 | 0.9435 | 0.9320 (−1.15) | 0.9442 (**+0.069**) |
| `64-min` | salmon dosage box | 0.12 | 0.9893 | 0.9864 (−0.29) | 0.9893 (**+0.003**) |

The middle column is the cost of doing half of it: reclassifying Waklert's badge
without being able to paint it takes that carton from 96.8% to **66.8%**. The
two halves are one change, the same shape as the `mark` hole and its mark.

**And the right-hand column is the whole point.** Drawing all three correctly is
worth +1.005, +0.069 and +0.003 points on their own cartons — about **+0.04
points of the group figure**. For a badge covering 5.08% of a printed face that a
viewer would notice missing at a glance.

That is not an argument that the change is worthless. It is a measurement of the
instrument: **`truth_agreement` is blind to whatever the labelling wrote off,
because writing it off removes it from the scored area on both sides.** The
project already knows this shape of error — `pixel_agreement` scores a face that
is 87–96% substrate and so is "very nearly a statement about the BOARD" — and it
has the same consequence here: *a fix nothing can measure is a fix nobody can
defend.*

The screen that does see it already exists and already ranks these cartons. From
the baseline coverage report, printed cluster against labelled print:

| sku | print % | truth % | ratio |
|---|---|---|---|
| `346-min` | 40.07 | 0.00 | ∞ — renders blank |
| `151-min` | 35.48 | 0.00 | ∞ — renders blank |
| `230-min` | 26.89 | 0.00 | ∞ — renders blank |
| `304-min` | 7.02 | 0.12 | 58.5 |
| `155-min` | 11.65 | 0.67 | 17.4 |
| `340-min` | 64.40 | 7.86 | 8.2 |
| `362-min` | 62.83 | 11.28 | 5.6 |
| `150-min` | 32.47 | 11.31 | 2.9 |

The three blank cartons report `truth_agreement` as **null** rather than as a
number, and an infinite ratio. Nothing is hidden; the figure declines to score a
carton it has nothing to score. That is the right behaviour and it is why they
are visible at all.

---

## What follows

Stated as findings, not as a plan, because two of the four need a decision that
is not a measurement's to make.

1. **Per-part fill** is the cheap, uncontested one: three components, the
   product's own design, no new primitive, no third party. Its justification is
   completeness rather than the figure — `truth_agreement` will move about +0.04
   group points and that is not the reason to do it.
2. **A gradient primitive** is argued for by three components and 21.18% of area,
   almost all of it `362_Hydrocodone`'s panel.
3. **Photographic inserts** are 19 components and the largest area of all, and
   the question they raise is whether a photograph from the reference should be
   printed on our carton. Not answered here.
4. **The simplify tolerance** costs one 6px rule on `230_Slimex`.

Whatever is done, the pattern that held for the `mark` holes holds here too: the
reclassification and the ability to draw are **one change**, and shipping the
first without the second costs `150_Waklert` thirty points.
