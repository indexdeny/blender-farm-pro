# Next Steps

> Queue for whoever (or whichever Claude session) picks this up next. Move
> items to [CHANGE_LOG.md](CHANGE_LOG.md) as they're completed, and update
> [CURRENT_STATE.md](CURRENT_STATE.md).

**Ordering rule:** item 1 is the one that finds unknown failures; run it before
tuning anything it might move. Housekeeping is independent throughout.

## Next

1. **Run the catalogue and look at the results.** No full pass has ever been made.
   Budget ~5 h; measured 24-48 s per SKU on 2026-08-02. This is the step that finds
   the layout failures the nine curated templates cannot show — every correction pass
   in the driver exists because an earlier sweep found real breakage. The reshape
   changed the proportions of all 391 cartons, so the label grid is now fitted to
   faces it was not measured on.

2. **Settle which model quantity the art-direction target is matched against.**
   Full silhouette, visible faces and front face differ by 13-18% and no measurement
   of our own renders can choose between them — the top face has no edge a threshold
   can find. `01_input_raster/reference_analysis.md` §10, §11 and §11a hold the
   evidence. Not blocking: the vertical family is 36-77% out under all three, so its
   direction is settled either way.

3. **Give the light rig a metering model that covers more than two shapes.** Exposure
   has landscape and portrait buckets, and two sweeps on 2026-08-09 show that is not
   enough — the front face lands under the reference floor of 235.0 for:

   | | front face | what they share |
   |---|---:|---|
   | `T_BOTTLE_BOX` 411, 412 | 231.9 | the deepest carton relative to its face |
   | `T_MULTIPACK` 350, 351 | 233.9 | |
   | `T3` 111 | 234.0 | the flattest carton |
   | 6 of 30 in `top30` | 234.0 | all 18mm deep |

   **Depth is the missing variable**, and the 18mm group makes that plain: six SKU
   with identical 110x56.7x18 cartons all read exactly 234.0 while their deeper
   siblings sit at 238. Ratcheted in `TestRenderedLuminance.KNOWN_UNDER_BAND` so it
   cannot slip further, but the fix is metering that reads the carton rather than a
   two-way branch on its shape.

4. **Close the remaining lid clipping.** 9.2% of the flat T3's lid still saturates,
   and the portrait lids sit at 0.79-0.82 of their front face against a reference band
   of 0.969-1.042. One rig cannot satisfy both shapes; a per-shape key elevation would,
   at the cost of the "one studio" invariant.

5. **Make `film_exposure()` read the picture, not the box.** It picks its shape from
   `width_mm >= height_mm`, which since contract 1.3 is art-directed geometry:
   `T_VERT_VIAL` reshapes to 172x170 and meters as landscape although it photographs
   portrait. The driver cannot import `src.silhouette` to ask.

## Corners, and what they carried

12. **Six more cartons are suspected of the same corner error `74_Viagra` had.**
   Screened by the rectified face's aspect against the aspect our own carton is
   built to: seven of 28 sit at 2.20-3.70 and the rest at 1.60 and below, with
   nothing between. `74-min` is fixed; `151-min` 3.70, `135-min` 3.22, `64-min`
   3.09, `362-min` 2.77, `357-min` 2.68 and `60-min` 2.20 are not. Each costs a
   third pass of hand classification, because a label is only valid for the
   corners it was made against. Two of them -- `64-min` and `59-min`'s neighbour
   `74-min` -- carry figures other records cite as live.

13. **`type_rows` has no corner guard, and `fit()` carries it forward.**
   `print_truth.json` records its corners and `verify()` refuses when they move;
   `type_rows` records nothing. On `74_Viagra` that put all four measured rows
   where the old crop had them, three of them printing in ink their own
   background hides. Re-measuring fixed it, but nothing would have said so.
   Give `type_rows` the same corner record `print_truth.json` has.

14. **`label_print --init` merges old classes onto new components** while
   rewriting the corners it validates against, so a corner change silently
   re-attaches every label to a different region. Refuse the merge when the
   corners differ, or drop the classes and say so.

15. **Xanax.** `340-min` sits at the opposite end of the corner screen (0.698)
   and prints 64.40% of its face against 7.86% classified -- the group's worst
   labelling gap, 8.2x. A different defect from `74-min`'s; not diagnosed.

16. **A fourth printed colour does not fit the segmentation.** `74_Viagra`
   prints `#ADC5DE` between its band and its substrate, u 0.233-0.269, and the
   k-means at k=4 has no cluster left for it. Raising k moves every published
   figure for all 28 cartons.

## Throughput, when it starts to hurt

6. **Keep one Blender process alive for a batch.** About 20 s of each render is
   fixed startup, roughly 2 h wasted across a full pass. Worth doing before the
   catalogue is rendered repeatedly, not before it is rendered once.

7. **Let Stage 3 consume Blender output.** `image_processor.source_dir` still points
   at the Gemini directory, so producing final WEBP from Blender renders needs a
   manual `--config`. Make the source follow the engine.

## Housekeeping

8. **Give `08_ops/` a Blender chapter.** Its paths were remapped onto this fork's
   layout on 2026-08-02, so the runbooks no longer send an operator to
   directories that do not exist — but they still describe a Gemini-only
   pipeline. `ACCEPTANCE_TEST.md` calls `src.rpa_orchestrator` directly, bypassing
   the facade and contradicting the architecture. (`DEPENDENCY_INVENTORY.md` now
   has rows for the Blender executable and Tesseract OCR — that part is done.)

9. **Rewrite `06_docs/experiments/BLENDER_RENDERER_ROADMAP.md`.** It still claims
   "Phase 0 complete, Phase 1 foundation in place" and describes Phases 2–4 as not
   started, when most of Phase 2 has shipped.

10. **Write ADR-007 for the Blender engine.** `00_governance/DECISIONS/` stops at
   ADR-006 and has nothing on why this fork exists.

11. **Put a floor under the small print — now a string-length problem, not a
   geometry one.** The driver fits a long label row by shrinking it, with no lower
   bound, so a long ingredient on a narrow face sets below legibility rather than
   overflowing. The references hold small print to 4.4-5.5mm.

   **The 2026-08-09 reshape fixed most of it as a side effect.** Widening the
   vertical family's faces to their reference proportions gave the type room:
   `393-min`, previously the catalogue's worst at **2.42mm**, now sets at
   **4.60mm** — above the floor and inside the reference range — because its face
   went from 50mm to 95.1mm. Scanning the 40 longest strings leaves **7 below
   4.0mm**, where the old scan had 9 of the 15 longest:

   | SKU | Template | Face mm | Chars | Type mm |
   |---|---|---:|---:|---:|
   | `177-min` | T1 | 45.0 | 27 | **2.86** |
   | `410-min` | T_BOTTLE_BOX | 72.1 | 33 | 3.21 |
   | `348-min` | T_MULTIPACK | 110.0 | 61 | 3.24 |
   | `350-min` | T_MULTIPACK | 110.0 | 54 | 3.59 |
   | `351-min` | T_MULTIPACK | 110.0 | 55 | 3.60 |
   | `349-min` | T_MULTIPACK | 110.0 | 51 | 3.88 |
   | `347-min` | T_MULTIPACK | 110.0 | 50 | 3.93 |

   Five of the seven are **all five** `T_MULTIPACK` SKU in the catalogue, and their
   faces are not narrow — 110mm — they simply carry 50-61 character ingredient
   names (`Sildenafil / Tadalafil / Vardenafil / Avanafil (Specimen Mix)`).
   `177-min` is the opposite case: a short string on a 45mm face.

   So the fix is no longer one thing. Deciding what gives — wrapping to a second
   line, abbreviating a combination product, or accepting a smaller floor — is an
   art-direction call, and it is now needed for two distinct situations rather than
   a spread across the catalogue. Reproduce with
   `python scripts/catalogue_sweep.py --legibility-scan 40`.

## Deliberately not doing

- **`T2`** — zero SKU in this catalogue.
- **A fake DataMatrix.** The passports declare a `DataMatrix_Zone` and the module
  width is below scanner tolerance on panels shorter than ~90 mm. A real symbol is
  worth adding later; a decorative one is not.
- **Hand-authored `.blend` templates.** The loader still honours them if they appear
  in `05_assets/blender/scenes/`, but procedural generation is the chosen path and that
  directory is empty on purpose.
