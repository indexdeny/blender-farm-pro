# Marks — the owner's decision

**Status: DECIDED 26 August 2026, and amended the same day on a corrected fact.
Phase 3 may proceed within the scope below and nowhere else.**

**Amendment — `59_Cialis brand#9` is now `no`.** It is not a Lilly wordmark
printed on the carton; it is the LETTERING OF the holographic sticker, whose own
region `secondary_1#0` was always out of scope. Measured: `brand#9`'s bounding
box, u 0.677–0.804 and v 0.743–0.854, lies entirely inside `secondary_1#0`'s
u 0.617–0.875 and v 0.650–0.948. The owner's instruction — do not draw the
holographic sticker, ignore such stickers — therefore covers it, and it is the
ONLY entry in the group that a containment check finds inside a refused one.

A security feature is refused whole, lettering included. Reproducing part of an
anti-counterfeiting element is the act this driver already refuses for LOT, EXP,
a product code and a 2D symbol.

The owner answered every row of both tables and then the header block, in two
messages on 26 August 2026. Everything below is transcribed verbatim; nothing
was inferred, no default was entered, and the header block was written by the
owner rather than by the implementer, which is what the original rule required.

The basis and the per-entry answers agree, and that is what makes this
consistent rather than merely complete: eleven rows were withdrawn precisely
because they were marks belonging to another company's product, and the basis
states that limit as the rule rather than as an exception.

Two further things were put to the owner when the answers were recorded.

1. **Two entries attached a manufacturer's mark to a product that manufacturer
   does not make** — `133_Ambien`'s eight **Hemofarm** wordmarks, on a SKU this
   catalogue labels *Ambien* (sanofi's brand), and `60_Cialis_Professional`'s
   **Lilly** marks, on a designation Lilly does not produce. That is the act
   this project already refuses for LOT and for dose: carrying package A's
   identity onto package B.

   **ANSWERED 26 August 2026: all of them changed to `no`.** The owner's rule
   for the rest was "those that genuinely belong to the corresponding products",
   and every remaining `yes` satisfies it — Roche on Valium, Novartis on
   Ritalin, sanofi-aventis on Imovane, Sun Pharma on Waklert, Lilly on Cialis
   itself, and the Kamagra, Slimex and Artvigil devices on their own packs.

   **One reading was mine and is flagged as mine.** The owner wrote "both
   `60_Cialis_Professional`" and that folder carries THREE rows — two
   `Cialis (Lilly) device` and one plain `Lilly` (`highlight#15`, 0.138%). All
   three are set `no`, because the owner's own criterion decides it: Cialis
   Professional is not a Lilly product, so no Lilly mark belongs to it. If that
   is not what was meant, `highlight#15` is the row to revisit.
2. ~~**What would be drawn is a silhouette, not a legible mark.**~~ **THIS WAS
   WRONG AND THE OWNER DECIDED PARTLY ON IT.** Corrected 26 August 2026 by
   drawing the emitted polygons and looking at them.

   `islands = 0` does not mean the lettering is absent: a glyph TOUCHING the
   region's boundary is not an island, it is a notch, and it survives the trace.
   And a silhouette of a wordmark IS that wordmark — a filled outline of Lilly's
   script reads "Lilly". Measured over the 23 emitted marks, **twelve have a
   solidity below 0.83**, i.e. carry letterform geometry rather than a blob:
   `152_Artvigil brand#26` 0.190 (a script swash), `64_Kamagra highlight#7`
   0.323, `59_Cialis brand#9` 0.355 (the word "Lilly"), `155_Imovane
   highlight#2` 0.593 ("ven"), `74_Viagra brand#0/hole#0` 0.918 (an oval with
   the "fi" ligature notched out of it). Eleven really are convex blobs.

   The owner was told the corrected fact, shown the drawn polygons, and
   re-decided on it: `59_Cialis brand#9` was withdrawn as the sticker's
   lettering, and the **eleven remaining letterform marks were confirmed** on
   26 August 2026. They all satisfy the basis — each belongs to the manufacturer
   of the product it is drawn on — and the owner confirmed them knowing they
   render as letterforms rather than as blobs. Recorded here so the confirmation
   is not mistaken later for the original, mistaken, understanding.

---

## What is being decided

Whether this project's renders may draw the regions classified `mark` in
`print_truth.json`, and — paired with that and inseparable from it — whether the
holes classified `mark` may be cut.

The two halves are one decision. Cutting a `mark` hole while drawing nothing
into it shows board through our field in the shape of another company's logo,
which is the act contract 1.8 already refuses for another company's lettering.
Cutting it *as part of* drawing the mark is coherent. Neither half may ship
alone.

## What the facts are

Established in [`MARKS_EVIDENCE.md`](MARKS_EVIDENCE.md), summarised here because
a decision should not require chasing a second document:

- The measured gain is **+9.937 points** of group `truth_agreement`, and **92% of
  it is two Pfizer ovals** (`74-min` +5.290, `135-min` +3.865).
- **All eight holes are solid regions.** What cutting one produces is a filled
  ellipse or roundel. The wordmark inside is not separated by the segmentation,
  is not carried by the hole, and would not appear in the render. What would
  appear is the mark's silhouette in its printed position.
- The 27 **components** are a different case and carry none of the +9.937.
  Sixteen are solid, and a solid `mark` component is the mark's own printed
  shape — drawing `133_Ambien`'s eight Hemofarm wordmarks as flat fills would
  reproduce those wordmarks' silhouettes.
- Rights holders across the set: Pfizer, Lilly, Roche, Novartis, Shire,
  sanofi-aventis, Sun Pharma, Hemofarm, Neptune Laboratories, LCI, plus the
  Kamagra and Cialis product devices.
- The project already refuses to print LOT, EXP, an invented product code, or a
  fake 2D symbol, on the grounds that they would make a render pass for genuine
  packaging.

## Two entries that are not branding and are decided separately

| key | what it is | why separate |
|---|---|---|
| `357-min highlight#0/hole#0` | the **C-II schedule symbol**, +0.076 | a regulatory marking required by US law on a controlled substance, not a trademark |
| `59_Cialis secondary_1#0` | the **Lilly holographic oval**, 4.423% of face | an anti-counterfeiting security feature; carries none of the +9.937 and is out of scope — recorded so it is not picked up later by class name alone |

---

## To be completed by the owner

**Decided by:** the repository owner, by message

**Date:** 26 August 2026

**Purpose the catalogue serves:** The catalogue serves to create visual 3D
renders of product packaging for the project catalogue.

**Basis — authorisation, licence, or the reasoning relied on:**

Owner decision to reproduce packaging marks only where the mark belongs to the
manufacturer or rights holder of the specific product being rendered. Marks that
would falsely associate a product with another manufacturer or rights holder are
not reproduced. This follows the project's existing rule against transferring
identifying packaging elements from one product to another.

**Scope in one sentence:** Only the mark regions explicitly marked "yes" in this
decision file may be drawn, and a mark hole may be cut only when its
corresponding mark is emitted in the same build; the holographic security
feature remains out of scope.

### Per-entry decision

`draw?` — write `yes` or `no`. Leave nothing blank; a blank is not an answer and
the implementer must stop on one.

#### Holes — these carry the +9.937 and are cut only if the paired mark is drawn

| sku | key | points | what it is | draw? |
|---|---|---|---|---|
| 74-min | brand#0/hole#0 | +5.290 | Pfizer oval, solid |  yes |
| 135-min | brand#0/hole#0 | +3.865 | Pfizer oval, solid |  yes |
| 221-min | brand#0/hole#0 | +0.631 | LCI roundel, solid |  yes |
| 357-min | highlight#0/hole#0 | +0.076 | **C-II schedule symbol** (regulatory, not branding) |  yes |
| 221-min | brand#0/hole#13 | +0.056 | LCI roundel, solid |  yes |
| 221-min | brand#0/hole#25 | +0.022 | LCI roundel, solid |  yes |
| 357-min | highlight#0/hole#4 | −0.001 | Shire logotype swash |  yes |
| 357-min | highlight#0/hole#5 | −0.002 | Shire logotype swash |  yes |

#### Components — the marks themselves as printed regions; none was priced

| folder | key | area % | rights holder | draw? |
|---|---|---|---|---|
| 60_Cialis_Professional | highlight#2 | 1.125 | Cialis (Lilly) device |  **no** |
| 60_Cialis_Professional | brand#2 | 0.688 | Cialis (Lilly) device |  **no** |
| 272_Valium_Brand | brand#1 | 0.411 | Roche |  yes |
| 64_Kamagra | highlight#7 | 0.395 | Kamagra device |  yes |
| 150_Waklert | brand#4 | 0.321 | Sun Pharma |  yes |
| 59_Cialis | brand#9 | 0.321 | Lilly — the LETTERING OF the holographic sticker | **no** |
| 230_Slimex | brand#8 | 0.303 | Neptune Laboratories |  yes |
| 133_Ambien | brand#2 | 0.297 | Hemofarm |  **no** |
| 133_Ambien | brand#3 | 0.275 | Hemofarm |  **no** |
| 157_Valium | type#8 | 0.231 | Roche |  yes |
| 133_Ambien | brand#4 | 0.208 | Hemofarm |  **no** |
| 133_Ambien | brand#5 | 0.203 | Hemofarm |  **no** |
| 64_Kamagra | highlight#17 | 0.184 | Kamagra device |  yes |
| 230_Slimex | brand#9 | 0.154 | Neptune Laboratories |  yes |
| 155_Imovane | highlight#2 | 0.152 | sanofi-aventis |  yes |
| 60_Cialis_Professional | highlight#15 | 0.138 | Lilly |  **no** |
| 133_Ambien | brand#6 | 0.123 | Hemofarm |  **no** |
| 64_Kamagra | highlight#18 | 0.119 | Kamagra device |  yes |
| 152_Artvigil | brand#26 | 0.119 | Signature script |  yes |
| 272_Valium_Brand | brand#13 | 0.116 | Roche |  yes |
| 404_Ritalin | type#19 | 0.115 | Novartis |  yes |
| 133_Ambien | brand#7 | 0.109 | Hemofarm |  **no** |
| 404_Ritalin | type#20 | 0.106 | Novartis |  yes |
| 64_Kamagra | highlight#21 | 0.103 | Kamagra device |  yes |
| 133_Ambien | brand#8 | 0.102 | Hemofarm |  **no** |
| 133_Ambien | brand#9 | 0.101 | Hemofarm |  **no** |
| 59_Cialis | secondary_1#0 | 4.423 | **holographic — out of scope, see above** | n/a |

---

## What happens after this file is filled

Phase 3 of the brief, and only within the scope written above:

1. contract 1.9 gains `design.marks[]`; a manifest at 1.8 is rejected;
2. `fit()` emits marks only for keys marked `yes` here — a key absent from this
   file is not emitted;
3. a `mark` hole is cut **iff** its paired mark was emitted in the same build,
   derived from the emission rather than from any reclassification;
4. `validate_manifest` rejects, by name, a manifest carrying a cut `mark` hole
   without its mark, on write and on read;
5. every figure is re-measured. **The +9.937 is not carried forward** — it was
   measured by cutting a hole with nothing behind it, and drawing a mark into
   the hole is a different measurement.

If the decision is `no` throughout, that is a complete outcome: it is recorded in
`CLAUDE.md` and `HOLE_CEILING.md` so the +9.937 is never again read as available
headroom, and no code changes.

`print_truth.json` is not edited either way. It records what a thing **is**; this
file records what may be done with it.
