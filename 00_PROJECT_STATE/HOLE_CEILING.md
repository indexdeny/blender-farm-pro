# The hole ceiling — what cutting them would be worth, and why almost none may be cut

Measured 24 August 2026 on branch `corner-trial-74-viagra`, from commit
`f6972f2`. Companion to `TOOLING_MIGRATION.md`, which closed the question of
tools; this closes the question the figure underneath it raised.

**Outcome: the gate is passed on the number written into the brief and failed on
the question that number was standing in for.** Phase 2 is not started. The
reason is not that the potential is small — it is +10.92 points — but that 91%
of it is another manufacturer's logo, which is the same thing the rule already
refuses for another manufacturer's lettering.

---

## The question

`TOOLING_MIGRATION.md` §2.2 measured, over all 75 printed components:

| what is filled | mean IoU |
|---|---|
| polyline, outer ring only | 0.8855 |
| polyline, every hole cut | 0.9536 |

So the whole 6.8-point gap belongs to holes. Ten of the group's holes are
classified `window` and are cut; the rest are filled. The question this document
answers is **not** whether the rule should change — it should not — but whether
anything among the filled holes is worth a person's time to re-examine.

That is two questions, and the design of this phase keeps them apart. What
cutting a hole is worth is mechanical. Whether a hole is a window is a judgement
about somebody else's carton. `scripts/measure_hole_payoff.py` answers only the
first, and `tests/test_hole_payoff.py` pins that it can never answer the second.

---

## Phase 0 — Discovery

### 0.1 `truth_agreement` needs no render

The gate the brief placed on this phase — stop and re-cost if the metric
requires rendering — does not fire. `scripts/design_coverage.py` contains no
render, no PNG read, no subprocess: it scores the spec's region index against
the hand-made ground truth from the segmentation. Cutting a hole and re-scoring
is therefore cheap, and Phase 1 costs one `segment()` per folder.

### 0.2 How the figure is taken, and how one hole is priced

`coverage()` builds `s_idx` from `spec_index()` — which fields the spec draws at
each pixel, holes already cut per contract 1.8 — and `lt_idx` from
`truth_from_labels()`. `truth_agreement` is the share of agreeing pixels over
the union of "the reference prints here" and "the spec draws here".

Cutting one hole changes pixels only inside that hole's ring, and what they
become is whatever the spec paints there **with that part absent**. So `behind`
is computed once per part — 75 rasterisations for the group — and each of that
part's holes is then a masked substitution plus a numpy pass. Exact: outside the
ring nothing moves, and a later field overlapping the hole keeps its own index
in both maps.

### 0.3 The enumeration matches the labelling exactly

Verified on `64_Kamagra` before anything was measured: same six keys, same
classes, same areas to four decimals as `print_truth.json`. The script
enumerates with the floor read out of the truth file, in the role order `fit()`
uses, so `role#i/hole#j` addresses the same hole on both sides.

### 0.4 Three numbers that do not match, and why

| source | holes |
|---|---|
| entries across the 28 `print_truth.json` | **242** |
| enumerated by this measurement | **239** |
| `CLAUDE.md` | 238 |

The three-hole difference is `74_Viagra`'s `brand#0/hole#1`, `#2` and `#3`, all
carrying `"vanished": true` and the reason `speckle in the flat band`. They were
labelled against the corners that commit `6d37b89` corrected, no longer exist
above the floor, and `label_print` **keeps and flags** such a label rather than
deleting it, so its disappearance is visible. The measurement correctly ignores
them; the report now states the arithmetic so the next reader does not re-derive
it.

`CLAUDE.md`'s 238 is the count as of contract 1.8, before the Viagra corner fix.
Documentation drift, not a discrepancy in the data.

### 0.5 The floor is part of the number

Holes are enumerated by `enclosed_background()` above `MIN_HOLE_FRAC = 0.0001`
of the face — 92 px on Viagra, 169 px on Kamagra. "239 holes" means holes above
that floor, not every hole in the segmentation: Kamagra's `brand#0` mask carries
593 enclosed background regions and six of them clear it.

### 0.6 Baseline

All 28 truth files snapshotted to
`baseline_2026-08-24/print_truth_prehole/` before anything ran. The existing
`print_truth/` snapshot is the previous run's evidence and was not touched.

---

## Phase 1 — the measurement

`00_PROJECT_STATE/hole_payoff.json`. 239 holes, 10 already cut, 228 measured,
1 ring too small to represent.

### 1.1 By class

| class | holes | potential, points of `truth_agreement` |
|---|---|---|
| `lettering` | 199 | **+44.433** |
| `mark` | 8 | **+9.937** |
| `blend` | 10 | +0.847 |
| `object` | 12 | +0.136 |
| `window` | 10 | 0.000 — already cut |

Total across everything: **+55.353**. Excluding `lettering`: **+10.920**.

### 1.2 The distribution, excluding lettering

| band | holes |
|---|---|
| under 0.1 points | 23 |
| 0.1 to 1.0 | 4 |
| over 1.0 | **2** |

### 1.3 The two holes over a point, and the next four

| sku | hole | class | area % of face | points |
|---|---|---|---|---|
| `74-min` | `brand#0/hole#0` | **mark** | 1.418 | **+5.290** |
| `135-min` | `brand#0/hole#0` | **mark** | 0.942 | **+3.865** |
| `221-min` | `brand#0/hole#0` | mark | 0.258 | +0.631 |
| `133-min` | `brand#0/hole#0` | blend | 0.219 | +0.566 |
| `340-min` | `brand#0/hole#0` | object | 0.141 | +0.150 |
| `357-min` | `brand#0/hole#1` | blend | 0.063 | +0.146 |

`74-min`'s is recorded in the truth file as *"the white Pfizer oval — a logo
container, printed white on the band, not board left unprinted"*. `135-min`'s is
Ativan's Pfizer oval, `221-min`'s the LCI roundel — the three examples
`label_print.py` names in its own definition of the class.

---

## Phase 1 verdict

**The brief's gate: continue if the potential excluding `lettering` exceeds 1.0
point. Measured +10.920. Passed.**

**The question that gate stood in for: is there anything a person mis-classified?
Answered no.**

Both readings have to be stated, because acting on the first alone is precisely
the failure this phase was designed to avoid.

`mark` is not a misfiling of `lettering`. `label_print.py` defines it as *"a
manufacturer's logo or a regulatory symbol sitting in the field. Not cut
either"*, and says why it is kept apart: *"the owner excluded logos by decision,
not because a renderer draws them from a string."* Cutting a `mark` hole while
drawing nothing into it shows board through our field in the shape of another
company's logo — the same act, pixel for pixel, as cutting `404_Ritalin`'s 72
holes to show its brand and dose.

So the reachable figure is not +10.920. Removing everything that is a third
party's branding leaves `blend` and `object`:

> **+0.983 points, spread over 22 holes — 10 `blend` and 12 `object`.** Of the
> 29 measured holes outside `lettering`, 23 are worth under 0.1 point each.

That is below the brief's own threshold. **Phase 2 is not started.** A person
re-examining 228 holes to recover under a point, on classes whose definitions
(`blend` — an edge or a gradient; `object` — something lying in front of the
carton) give no reason to expect a window among them, is not a good use of the
most expensive artefact in the project.

### The one thing this does open, and it is not an engineering decision

`mark` holes and `mark` components are **one decision, not two**. The group
carries 27 components classified `mark` and 8 holes; `label_print.py` records
that the hole class exists because *"Phase G's `design.marks[]` needs exactly
this set."*

Cutting a mark's hole without drawing the mark is forbidden for the reason
above. Cutting it **as part of drawing the mark** is coherent — the hole is then
a window onto the logo, which is what the carton actually prints. That path is
worth **+9.937 points** on this figure, it is fully labelled and waiting, and it
is blocked on a decision about reproducing third-party trademarks that belongs
to the owner rather than to any measurement here.

---

## Phase 3 — the resolution ceiling, declared

Independent of the above, and completed.

`OUT_WIDTH` is 1100 for every folder whatever the photograph, so every spec is
traced from the face enlarged to that width. `scripts/measure_face_resolution.py`
reports the real size, taken from the same `front_face_px` corners
`rectified_face()` warps from.

| folder | face, source px | enlargement |
|---|---|---|
| `357_Adderall` | 134x172 | **8.21x** |
| `151_Provigil` | 147x248 | **7.48x** |
| `156_Xanax` | 260x179 | 4.23x |
| `304_Sonata` | 278x182 | 3.96x |
| `135_Ativan` | 302x465 | 3.64x |
| `362_Hydrocodone` | 322x406 | 3.42x |
| — threshold, 350px — | | |
| `308_Lexotanil` | 387x154 | 2.85x |
| … | | |
| `346_Modvigil` | 1128x526 | 0.97x |

`MIN_FACE_PX = 350` is taken from the distribution rather than chosen: sorted by
face width the group runs 134, 147, 260, 278, 302, 322, **387**, 393, 398, …,
1128. The one real gap in the low half is the 20% step between 322 and 387,
where every neighbouring step above it is under 8%.

`SIMPLIFY_TOLERANCE` is a thousandth of the rectified width, so on `357_Adderall`
it is **0.13 of a source pixel** — finer than the grid the evidence is on.

`tests/test_reference_templates.TestTheFaceResolutionCeilingIsDeclared` names the
six by name and fails in both directions. It is a declaration, not a gate: these
folders keep their specs, stay in `TEMPLATE_SAMPLE` and go on rendering. What
they may not do is be a surprise the next time one of their figures moves.

---

## What is on disk after this run

| file | what it is |
|---|---|
| `scripts/measure_hole_payoff.py` | the measurement; writes only its own report |
| `tests/test_hole_payoff.py` | pins that it never writes the labelling and never proposes a class |
| `00_PROJECT_STATE/hole_payoff.json` | every hole, its class, its area, what cutting it is worth |
| `scripts/measure_face_resolution.py` | the resolution instrument |
| `00_PROJECT_STATE/face_resolution.json` | every folder's real face size |
| `baseline_2026-08-24/print_truth_prehole/` | all 28 truth files as they stood |

**Nothing was reclassified.** No `print_truth.json`, `design_spec.json`,
manifest or figure changed. `hole_reclass_log.md` does not exist because Phase 2
did not run.
