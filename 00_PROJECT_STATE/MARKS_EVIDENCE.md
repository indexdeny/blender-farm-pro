# What the 35 `mark` entries actually are

Phase 1 of the marks question. Read-only: nothing was reclassified, no spec,
manifest or figure changed. Produced by `scripts/render_mark_evidence.py`;
crops in `02_processing/marks_evidence/`, machine-readable index beside them.

This document states facts. It contains **no recommendation**, and the decision
belongs in `MARKS_DECISION.md`, which is the owner's to fill.

---

## Why the question was asked

`HOLE_CEILING.md` measured that holes classified `mark` are worth **+9.937
points** of group `truth_agreement` — 91% of everything reachable outside
`lettering`. Cutting one while drawing nothing into it is forbidden: it shows
board through our field in the shape of another company's logo, which is the
same act as cutting `404_Ritalin`'s lettering. The only coherent form is to cut
the hole **as part of** drawing the mark.

Before asking anyone to decide that, one thing had to be established, because
nobody had looked: **what is actually in these regions.** The truth file's own
note on `74_Viagra` calls its hole *"a logo container, printed white on the
band"* — a shape, that is, rather than artwork. If the set is containers the
decision is about filling regions; if it is artwork it is about reproducing
marks. Different questions.

---

## The finding

**Every one of the 8 holes is a solid region.** `islands = 0` and
`solid_frac = 1.000` on all eight: nothing is enclosed inside them, so there is
no internal structure to reproduce even in principle.

This is not only a property of the mask, it is a property of what ships.
`trace_holes()` traces the **outer boundary** of a hole and keeps no islands, so
what a cut hole can ever become is a filled outline. Measured on the two largest:

| | `74_Viagra` | `135_Ativan` |
|---|---|---|
| hole mask | 13 071 px | 17 554 px |
| same, holes filled | 13 071 px | 17 554 px |
| enclosed islands | **0** | **0** |
| what would be cut (outer ring) | 12 953 px, 47 vertices | 17 436 px, 56 vertices |

Both are Pfizer ovals. **What cutting them produces is a plain ellipse.** The
"Pfizer" script inside is not separated by the segmentation, is not carried by
the hole, and is not recoverable from this data. It would not appear in the
render.

What *would* appear is the ellipse — in that position, in those proportions, on
that navy band. That is the logo's silhouette without its wordmark. Whether that
is a thing this project should print is exactly the question this document
refuses to answer.

**The components are a different case and are mixed.** Of the 27, sixteen are
solid and eleven carry internal structure. A solid `mark` *component* is not a
container: it is the mark's own printed silhouette — `133_Ambien`'s eight
Hemofarm wordmarks each trace as one solid region, so drawing them as flat fills
would reproduce the wordmark's shape. The +9.937 does **not** come from these;
they were never priced.

---

## The eight holes, by what they are worth

| sku | key | area % of face | points | islands | what the label says |
|---|---|---|---|---|---|
| `74-min` | `brand#0/hole#0` | 1.418 | **+5.290** | 0 | the white Pfizer oval — a logo container |
| `135-min` | `brand#0/hole#0` | 0.942 | **+3.865** | 0 | the Pfizer oval in the navy bar |
| `221-min` | `brand#0/hole#0` | 0.258 | +0.631 | 0 | the LCI roundel |
| `357-min` | `highlight#0/hole#0` | 0.647 | +0.076 | 0 | **the C-II schedule symbol** |
| `221-min` | `brand#0/hole#13` | 0.028 | +0.056 | 0 | the LCI roundel |
| `221-min` | `brand#0/hole#25` | 0.010 | +0.022 | 0 | the LCI roundel |
| `357-min` | `highlight#0/hole#4` | 0.024 | −0.001 | 0 | the Shire logotype swash |
| `357-min` | `highlight#0/hole#5` | 0.014 | −0.002 | 0 | the Shire logotype swash |
| | | | **+9.937** | | |

**92% of the whole figure is two Pfizer ovals.** Everything below them together
is +0.782, and the two Shire fragments are worth slightly less than nothing.

---

## Two entries that are not manufacturer branding, and must be decided separately

**`357-min highlight#0/hole#0` — the C-II schedule symbol, +0.076.** This is a
regulatory marking: the DEA Schedule II designation that United States law
requires on the packaging of a controlled substance. It is not a trademark and
not anybody's branding. It belongs in a different category from the ovals and
should not be swept into one answer with them — in either direction. Note also
that it is a statement about the product's legal classification, which is a
reason to be careful about printing it on a carton that is not the real one, and
a reason not to omit it silently either.

**`59_Cialis secondary_1#0` — the Lilly HOLOGRAPHIC oval, 4.423% of the face.**
A component rather than a hole, so it carries none of the +9.937, and its label
already records *"excluded by the owner"*. It is named here because a hologram is
an **anti-counterfeiting security feature**, not decoration. Reproducing one —
even as a flat grey region, which is all this data could produce — moves against
the position the rest of this project holds: the driver refuses to print LOT and
EXP, refuses to invent a product code, refuses to draw a DataMatrix it cannot
make scannable. This entry is out of scope for the marks decision and is
recorded so it stays out rather than being picked up later by someone reading
the class name alone.

---

## All 35 entries

`kind` — whether the region is a component or a hole. `islands` — enclosed
regions inside the mask; 0 means solid. `solid` — mask area over filled area.

| folder | key | kind | area % | islands | solid | label's reason |
|---|---|---|---|---|---|---|
| 59_Cialis | secondary_1#0 | component | 4.423 | 96 | 0.870 | Lilly holographic oval, excluded by the owner |
| 74_Viagra | brand#0/hole#0 | hole | 1.418 | 0 | 1.000 | the white Pfizer oval — a logo container |
| 60_Cialis_Professional | highlight#2 | component | 1.125 | 0 | 1.000 | Cialis e-swoosh device |
| 135_Ativan | brand#0/hole#0 | hole | 0.942 | 0 | 1.000 | the Pfizer oval in the navy bar |
| 60_Cialis_Professional | brand#2 | component | 0.688 | 0 | 1.000 | Cialis e-swoosh device |
| 357_Adderall | highlight#0/hole#0 | hole | 0.647 | 0 | 1.000 | the C-II schedule symbol |
| 272_Valium_Brand | brand#1 | component | 0.411 | 1 | 0.112 | Roche hexagon logo |
| 64_Kamagra | highlight#7 | component | 0.395 | 37 | 0.986 | Kamagra family device |
| 150_Waklert | brand#4 | component | 0.321 | 36 | 0.677 | SUN Pharma logo |
| 59_Cialis | brand#9 | component | 0.321 | 4 | 0.860 | Lilly script inside the holographic oval |
| 230_Slimex | brand#8 | component | 0.303 | 1 | 0.291 | Neptune Laboratories logo |
| 133_Ambien | brand#2 | component | 0.297 | 0 | 1.000 | Hemofarm wordmark |
| 133_Ambien | brand#3 | component | 0.275 | 0 | 1.000 | Hemofarm monogram |
| 221_Inderal | brand#0/hole#0 | hole | 0.258 | 0 | 1.000 | the LCI roundel |
| 157_Valium | type#8 | component | 0.231 | 1 | 0.118 | Roche hexagon logo |
| 133_Ambien | brand#4 | component | 0.208 | 0 | 1.000 | Hemofarm wordmark |
| 133_Ambien | brand#5 | component | 0.203 | 0 | 1.000 | Hemofarm wordmark |
| 64_Kamagra | highlight#17 | component | 0.184 | 44 | 0.938 | Kamagra family device |
| 230_Slimex | brand#9 | component | 0.154 | 1 | 0.105 | Neptune Laboratories logo |
| 155_Imovane | highlight#2 | component | 0.152 | 21 | 0.780 | sanofi aventis wordmark |
| 60_Cialis_Professional | highlight#15 | component | 0.138 | 5 | 0.711 | Lilly script |
| 133_Ambien | brand#6 | component | 0.123 | 1 | 0.894 | Hemofarm wordmark |
| 64_Kamagra | highlight#18 | component | 0.119 | 1 | 0.999 | Kamagra family device |
| 152_Artvigil | brand#26 | component | 0.119 | 8 | 0.669 | Signature script logo |
| 272_Valium_Brand | brand#13 | component | 0.116 | 1 | 0.772 | Roche hexagon logo |
| 404_Ritalin | type#19 | component | 0.115 | 0 | 1.000 | Novartis wordmark |
| 133_Ambien | brand#7 | component | 0.109 | 0 | 1.000 | Hemofarm wordmark |
| 404_Ritalin | type#20 | component | 0.106 | 1 | 0.411 | Novartis wordmark |
| 64_Kamagra | highlight#21 | component | 0.103 | 15 | 0.982 | Kamagra family device |
| 133_Ambien | brand#8 | component | 0.102 | 1 | 0.650 | Hemofarm wordmark |
| 133_Ambien | brand#9 | component | 0.101 | 1 | 0.862 | Hemofarm wordmark |
| 221_Inderal | brand#0/hole#13 | hole | 0.028 | 0 | 1.000 | the LCI roundel |
| 357_Adderall | highlight#0/hole#4 | hole | 0.024 | 0 | 1.000 | the Shire logotype swash |
| 357_Adderall | highlight#0/hole#5 | hole | 0.014 | 0 | 1.000 | the Shire logotype swash |
| 221_Inderal | brand#0/hole#25 | hole | 0.010 | 0 | 1.000 | the LCI roundel |

Rights holders named across the set: Pfizer, Lilly, Roche, Novartis, Shire,
sanofi-aventis, Sun Pharma, Hemofarm, Neptune Laboratories, LCI, plus the
Kamagra and Cialis product devices.

---

## What the project's existing position is

Not an argument, a fact that belongs in front of whoever decides. The driver
already refuses several things on the grounds that inventing them would make a
render pass for genuine packaging:

- **LOT and EXP** are drawn as empty labels with a rule. The project holds no lot
  or expiry data, and a real carton carries none either — they are inkjetted at
  packing. Printing a plausible value would be inventing data on pharmaceutical
  packaging.
- **`product_code` is deliberately not a GTIN, PZN or national drug code.** The
  project holds none, and inventing one is the act it already refuses for LOT
  and EXP. The driver raises rather than falling back to `sku_id`.
- **No 2D symbol is built.** The module width is below what a scanner needs on
  most panels; the driver warns rather than faking one.
- **Contract 1.8 refuses to cut 228 of 239 holes**, because `404_Ritalin`'s
  seventy-two spell "Ritalin® 10 mg Tabletten" and "50 Tabletten/N2", and
  showing board through our field in that shape prints another package's brand
  and dose.

Adding manufacturer marks moves in the opposite direction from all four. That is
a fact about consistency, not a verdict — the four above are about *fabricated*
identifiers, and a mark is not fabricated. The comparison is offered so the
decision is made against the whole picture.

---

## What is on disk

| path | what |
|---|---|
| `scripts/render_mark_evidence.py` | produces the crops; writes only under the evidence directory |
| `tests/test_mark_evidence.py` | pins that it never writes the labelling and carries no verdict field |
| `02_processing/marks_evidence/*.png` | one contact sheet per folder, plain crop beside classified pixels |
| `02_processing/marks_evidence/index.json` | the 35 entries with their measured structure |

`print_truth.json` is unchanged in all 28 folders.
