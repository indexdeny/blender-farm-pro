# Architecture

## Runtime owners

Catalogue data remains in `03_knowledge_graph`; SKU passports remain in `04_passports/passports_json`. The renderer does not create a reduced second catalogue. `agent_1_router()` owns template routing; `src/render_manifest.py` owns both supported manifest-building paths and validates against the one JSON Schema.

The legacy facade selects the engine in `src/render_stage.py`. Physical demonstrations use `scripts/rebuild_carton.py` to build independent artwork and an explicit version-1.13 manifest, then invoke the same external Blender driver. `import bpy` belongs only to `05_assets/blender/render_driver.py`; physical adapters receive its API object. Fatal driver exceptions must reach `SystemExit`.

## Physical path

`baseline_rebuild` in the SKU's existing design spec describes geometry, authored dimensions, assets, elements, material estimates, cameras and rendering. Font outlines and independent SVG vectors generate UV maps through `src/carton_artwork.py`; carton construction and relief come from the `carton_*` modules. `build_baseline_manifest()` calls the canonical router and preserves passport dimensions independently from physical art geometry. The driver delegates physical assembly/rendering to `src/carton_scene.py`.

The historical owner-authorized exceptions apply only to physical mode: UV artwork for text/vectors and spec-defined stage settings. Legacy text geometry and common stage behavior are preserved. The photographic `reference_projection` mode is excluded; it is retained only in private development recovery.

## Outputs and evidence

Generated artwork, saved scenes, per-run manifests, masks, logs and validation reports are derived outputs. They do not replace runtime source data or the canonical manifest schema. Portfolio provenance JSON is documentation, not a render contract consumed by the application. Historically accepted PNGs remain unchanged in private recovery; optimized previews are lossless re-encodings verified by decoded-pixel equality.

## Verification boundaries

Schema/unit/driver checks establish local component behavior under their recorded environment. An image comparison establishes equality only for the compared files. Visual similarity, workplace acceptance and production authenticity are separate claims. A clean checkout must not rely on private generated caches; optional external photography checks must report NOT VERIFIED when their full dataset is absent and fail on incomplete/corrupt supplied data.
