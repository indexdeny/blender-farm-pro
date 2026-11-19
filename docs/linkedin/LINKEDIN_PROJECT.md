# LinkedIn Project

## Title
Blender Farm Pro — AI-Assisted 3D Packaging Visualization

## Short description
Designed and directed an inspectable Blender/Cycles packaging pipeline. Two SKU examples reached owner-reported workplace acceptance; further catalogue development stopped because of budget constraints.

## Problem
Browser-based image generation offered insufficient control over carton geometry, printed elements, lighting and composition. Packaging visualization needed explicit inputs and a process that could be inspected and verified.

## Solution
A Python pipeline compiles SKU data and physical design inputs into a validated render manifest, then generates editable Blender scenes and renders them through Cycles. Preserved scenes, artwork resources and image evidence support inspection and controlled replay.

## My role
Requirements definition, system architecture, technical specifications, AI-agent orchestration, render evaluation and quality assurance. I coordinated AI-assisted implementation and iterative visual refinement; this is not a claim that I manually wrote all code.

## Technologies
Python, Blender 5.1.2, Cycles CPU, JSON Schema, Pillow, NumPy, CairoSVG, fontTools, PyYAML and stdlib unittest.

## Verified results
- Exactly two owner-reported workplace-accepted examples: Viagra (74-min) and Cialis (59-min).
- Preserved editable scenes recovered every accepted RGBA pixel in the checked Blender 5.1.2 CPU environment. Applying the existing color-only PNG metadata policy also recovered the accepted PNG hashes.
- Fresh procedural renders separately matched the prior release baseline. They differed from the accepted images at 652 pixels for Viagra and 501 for Cialis, with a maximum channel difference of 1/255.
- All 19 historical masks were preserved. Exact raw-mask regeneration is not established.
- A previously recorded full unittest run reported 611 passed, 0 failed, 0 errors and 14 skip records. This is historical evidence, not a new test run for this portfolio package.

## Limitations
R&D prototype; only two accepted examples. The retained 391-SKU catalogue is compatibility data, not 391 approved renders. Further catalogue development stopped because of budget constraints. Materials and some dimensions are authored or estimated; manufacturer approval, calibrated production dimensions and complete automated OCR acceptance are not established. Exact historical creation revisions are unknown. Replay equality is limited to the checked environment, without a cross-version or cross-machine guarantee.

Portfolio publication permission is owner-confirmed; permission instruments were not independently inspected. Brand names, vectors, fonts and derivatives retain their respective rights. No blanket commercial or trademark licence is granted.

## GitHub link
[Source, editable examples and verification evidence](https://github.com/indexdeny/blender-farm-pro)

Evidence: [README](../../README.md), [scene and masks audit](../../FINAL_SCENE_AND_MASKS_AUDIT.md), [asset-rights ledger](../portfolio/ASSET_RIGHTS.md).
