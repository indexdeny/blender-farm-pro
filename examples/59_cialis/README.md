# 59-min editable historical scene

Open [the Blender scene](scenes/59-min-historical.blend) with Blender 5.1.2. The active view is `camera_hero`; the scene also includes front/top/end cameras, UV-mapped carton geometry, materials and the three-light studio. These are editable scenes, not image planes.

The immutable original scene is tied to the accepted historical PNG by SHA-256 in [historical evidence](evidence/59-min-proportion-final.scene.json). The portable file is a derived save with dependency/output paths remapped; it is not named or claimed to be an independently approved scene. Original creation Git revision remains unknown. [Scene provenance](scene-provenance.json) records original/derived hashes and validation scope.

Four file textures are packed. The normal map is stored at `textures/normal.png` and referenced by `//../textures/normal.png`; keep that sibling directory with the scene. Its bytes exactly match the original packed image. No original machine directory is required. The compositor writes regenerated Object Index masks under the checkout's `reports/editable-59-min/masks` directory; it does not overwrite the preserved historical masks.

## Render the saved scene

From the repository root, using the external Blender executable:

```powershell
blender --background --disable-autoexec "examples/59_cialis/scenes/59-min-historical.blend" -o "//../../../reports/editable-59-min/hero" -f 1
```

Blender must be on PATH or replaced by its full executable path. The output is `reports/editable-59-min/hero0001.png`. For the independently generated procedural path, use the corresponding two-SKU command in the root README. Historical image preservation, saved-scene integrity, procedural generation and visual regression have separate verdicts in [the audit](../../FINAL_SCENE_AND_MASKS_AUDIT.md).

## Masks and rights

The masks in `masks/` are preserved historical Object Index/compositing outputs, including studies; they are not material, roughness, normal or height inputs. Their names do not establish acceptance. Original hashes and associations are listed in [the inventory](../../RENDER_ASSET_INVENTORY.json).

The same [asset rights](../../docs/portfolio/ASSET_RIGHTS.md) and prototype limitations apply to the editable model and its packed/external derived artwork. Publication does not grant a blanket brand/trademark or commercial licence.
