# Blender Farm Pro — Technical Case Study

## Problem
Browser-based image generation did not provide sufficient control over pharmaceutical packaging geometry, printed elements, lighting and composition. The project explored a more inspectable process with explicit SKU inputs, editable scenes and recorded validation evidence.

## Requirements
- Keep catalogue data, routing and the Stage 1 → Stage 2 manifest under their canonical owners.
- Generate packaging from structured SKU data, physical design specifications and traceable vector/font artwork inputs.
- Retain editable geometry, material maps, cameras, lighting and render settings.
- Distinguish historical acceptance, saved-scene replay, fresh procedural generation and production authenticity.
- Preserve accepted images and historical diagnostic masks without replacing them with fresh outputs.

## Architecture
Catalogue and SKU passport → canonical manifest provider → JSON Schema validation → headless Blender driver → editable scene and PNG → scene/image verification.

Physical design specifications and SVG/TTF inputs supply artwork and material maps. The manifest contract is defined in schemas/render_manifest.schema.json and implemented by src/render_manifest.py. Template routing remains owned by agent_1_router() in src/passport_generator.py. The catalogue remains in 03_knowledge_graph/.

The explicit physical branch uses manifest version 1.13 and coexists with legacy rendering. Its artwork and scene rules are mode-specific; they do not redefine legacy rules. Blender is an external executable.

## Implementation Approach
My contribution covered requirements, architecture, technical specifications, AI-agent orchestration, render evaluation and quality assurance. I directed AI-assisted implementation and iterative visual refinement; I do not claim to have manually written all code.

The physical builder creates an artwork atlas from vendored fonts and independent SVG contours, constructs carton geometry and relief, compiles the manifest and invokes the existing Blender driver. The examples use authored material approximations, including foil and surface treatments. Geometry, camera, artwork and visual design were refined together, so development-stage comparisons do not isolate an automation effect.

The final portfolio preserves two historical 2048×2048 accepted PNGs, their lossless previews, editable scenes and resources. These examples are not claimed as legacy Stage 3 WEBP deliverables. No new packshots or paid image-generation calls were required for this text package. AI-assisted engineering here does not imply a machine-learning model was trained or developed.

## Validation
The canonical scene/masks audit records separate checks for historical image preservation, editable-scene integrity, fresh procedural rendering and visual regression. Final derived scene files were opened and rendered in a clean clone. Geometry, UVs, materials, camera/light settings, resource dependencies and hashes were checked. These are previously recorded checks; this document does not report a new execution.

In Blender 5.1.2/ec6e62d40fa9 with Cycles CPU, the saved scenes reproduced all accepted RGBA pixels. After the existing color-only PNG metadata policy, their PNG hashes also matched. Raw Blender PNG bytes are evaluated separately because timing/text chunks can vary.

Fresh procedural renders were assessed independently. They matched the previous release's fresh baseline, while differing from historical accepted images at 652 pixels for Viagra and 501 for Cialis, with a maximum channel difference of 1/255.

The previously recorded full unittest result was 611 passed, 0 failed, 0 errors and 14 skip records. It remains historical evidence; no new full-suite run is claimed for the binary/documentation addendum or this LinkedIn package. Optional/slow checks and the historical R-004 issue remain limitations.

## Verified Results
- Exactly two owner-reported workplace-accepted SKU examples: Viagra (74-min) and Cialis (59-min).
- Both accepted images and decoded-pixel-identical previews preserved with provenance hashes.
- Editable scenes retained: Viagra has 87 objects, including 80 meshes; Cialis has 52 objects, including 45 meshes. Each has four cameras and three lights.
- Saved-scene replay recovered the accepted pixels in the checked environment; normalized PNG hashes also matched under the documented policy.
- Fresh procedural rendering retained its prior baseline, with the separate accepted-image differences stated above.
- All 19 historical masks preserved byte-for-byte. Small raw differences in new hero masks remain unresolved; exact mask regeneration is not claimed.

## Limitations
Further catalogue development stopped because of budget constraints. The retained 391-SKU catalogue is legacy compatibility data, not evidence of 391 accepted products; only the two named examples reached the stated acceptance.

The examples are authored adaptations, not manufacturer-certified carton masters. Materials, optics and some dimensions are approximations or estimates. DEMO barcode treatment and blank LOT/EXP fields are not production identifiers. Whole-frame OCR did not recover every brand/dose field, and complete automated physical-view acceptance is not established.

Exact historical creation Git revisions are unknown because rendering used uncommitted code. The saved-scene replay result applies to the checked Blender 5.1.2 CPU environment; cross-version and cross-machine determinism are not established. Historical mask associations lack original mask-hash pinning, so preservation and exact regeneration are separate findings.

The carousel uses real early sources baseline_before.png and 59-min-baseline_before.png. Capture dates are unknown and views differ. It illustrates development stages without a controlled chronological comparison or an isolated automation-effect claim.

Portfolio publication permission is owner-confirmed, including the recorded scope for branded inputs and derived scene resources. Permission instruments were not independently inspected. Source-site licensing uncertainties remain recorded in the asset-rights ledger; publication grants no blanket downstream commercial or trademark licence, manufacturer certification or endorsement.

## Lessons Learned
Explicit data contracts make rendering decisions inspectable. Scene preservation enables a different verification question from rebuilding a scene procedurally. Pixel equality, file-byte equality, visual acceptance and production authenticity require separate evidence. AI-agent orchestration benefits from clear requirements and render QA, while accepted output must remain traceable to the preserved source artifacts.

[GitHub project](https://github.com/indexdeny/blender-farm-pro) · [Canonical README](../../README.md) · [Scene and masks audit](../../FINAL_SCENE_AND_MASKS_AUDIT.md) · [Asset-rights ledger](../portfolio/ASSET_RIGHTS.md)
