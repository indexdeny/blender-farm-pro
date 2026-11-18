"""PharmaGen PRO — Blender scene driver (EXPERIMENTAL, runs INSIDE Blender).

Invoked headless by src/blender_renderer.py:
    blender --background --factory-startup --python render_driver.py -- \
        --job <job.json> --out <out.png> --engine-type CYCLES --samples 64 \
        --res-x 2048 --res-y 2048

The job file is a RENDER MANIFEST conforming to
schemas/render_manifest.schema.json, validated on the project side before it
gets here. This script therefore trusts its shape and does not re-derive
anything from it — notably, carton dimensions arrive resolved, so there is no
aspect-ratio guessing in this file.

Builds a PROCEDURAL packshot scene from the job's structured data (no
hand-authored .blend asset required — see the roadmap §1 "design choice").
An OPTIONAL hand-authored "{template_id}.blend" in blender.scenes_dir can be
added later (Phase 2) and loaded instead of the procedural build; this script
already looks for one and prefers it when present.

Camera pitch/rotation reuse the SAME optical language documented for the
Gemini prompt templates (25 deg pitch / 35 deg rotation for most families,
20/25-30 deg for the vertical family) so both engines target comparable
framing — see 06_docs/DESIGN_RATIONALE.md.
"""
import bpy
import mathutils
import os
import sys
import json
import math
from pathlib import Path

# ── argv (everything after the bare "--") ────────────────────────────────────
_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _arg(flag: str, default=None):
    if flag in _argv:
        return _argv[_argv.index(flag) + 1]
    return default


JOB_PATH   = _arg("--job")
OUT_PATH   = _arg("--out")
ENGINE     = _arg("--engine-type", "CYCLES")
SAMPLES    = int(_arg("--samples", "64"))
RES_X      = int(_arg("--res-x", "2048"))
RES_Y      = int(_arg("--res-y", "2048"))
# Which device Cycles samples on, which back-end it reaches the GPU through, and
# where the denoiser runs. STATED, not inherited: until 2026-08-24 setup_render()
# never assigned `scene.cycles.device`, so the render used whatever device the
# process started with. Under `--factory-startup` that is CPU, which is why
# nothing was visibly wrong — but a second `--python` argument ahead of this
# script could move the whole render onto the GPU, and the packshot would come
# back up to 43 levels different on a fraction of a percent of its pixels with
# nothing in the log to say which device drew it.
#
# The defaults are today's measured behaviour, so a caller that passes neither
# flag renders exactly what it rendered before.
DEVICE          = (_arg("--device", "CPU") or "CPU").upper()
DEVICE_BACKEND  = (_arg("--device-backend", "OPTIX") or "OPTIX").upper()
DENOISE_DEVICE  = (_arg("--denoising-device", "CPU") or "CPU").upper()
# Diagnostic seam: build the scene, write its measured geometry to this path as
# JSON, and skip rendering. Exists because carton/stripe placement can only be
# verified inside Blender, and a packshot is far too slow and too indirect to
# assert on in a unit test — see tests/test_blender_carton.py.
DUMP_SCENE = _arg("--dump-scene")
OBJECT_MASK_PATH = _arg("--object-mask")
SHADOW_MASK_PATH = _arg("--shadow-mask")
# Diagnostic sensitivity seam: the production path is always the common
# receiver; tests may switch only that receiver off for a matched comparison.
SHADOW_OFF = "--shadow-off" in _argv
# Diagnostic-only path used by scripts/render_reference_blanks.py.  The job is
# still manifest-shaped and carries the measured carton profile, but all printed
# content must be absent from both the render and the scene dump.
BLANK_CARTON = "--blank-carton" in _argv
# A source-label study is explicitly diagnostic; ordinary jobs retain the passport.
SAVE_BLEND = _arg("--save-blend")

if not JOB_PATH or not (OUT_PATH or DUMP_SCENE):
    raise SystemExit(
        "[render_driver] --job is required, plus --out to render "
        "(or --dump-scene to only measure the built scene)")

with open(JOB_PATH, "r", encoding="utf-8") as f:
    JOB = json.load(f)

# Camera calibration per template family — same numbers used in the Gemini
# prompt templates (src/passport_generator.py TEMPLATE_* constants).
VERTICAL_FAMILY = {"T_VERT_VIAL", "T_VERT_DROPPER", "T_VERT_INHALER"}
if JOB.get("template_id") in VERTICAL_FAMILY:
    PITCH_DEG, ROTATION_DEG = 20.0, 27.5   # 20 deg pitch, ~25-30 deg rotation
else:
    PITCH_DEG, ROTATION_DEG = 25.0, 35.0


def hex_to_rgba(hex_str: str, default=(0.9, 0.9, 0.9, 1.0)):
    """sRGB hex -> approximate linear RGBA for Principled BSDF base_color."""
    if not hex_str or not str(hex_str).startswith("#"):
        return default
    h = hex_str.lstrip("#")
    if len(h) != 6:
        return default
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return default
    srgb_to_linear = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), 1.0)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)


def make_material(name: str, hex_color: str, roughness=0.35) -> "bpy.types.Material":
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = hex_to_rgba(hex_color)
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
    return mat


def make_carton_material(name, hex_color, finish=None):
    """Carton colour with optional deterministic, normal-only paper grain."""
    if not finish:
        return make_material(name, hex_color, roughness=MATTE_ROUGHNESS)
    mat = make_material(
        name, hex_color, roughness=float(finish["roughness"]))
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")

    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.name = "Carton Coordinates"
    texcoord.object = bpy.data.objects.get("carton")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.name = "Carton Seed Mapping"
    noise = nodes.new("ShaderNodeTexNoise")
    noise.name = "Carton Paper Grain"
    bump = nodes.new("ShaderNodeBump")
    bump.name = "Carton Micro Bump"

    micro = finish["micro_bump"]
    seed = int(micro["seed"])
    mapping.inputs["Location"].default_value = (
        ((seed * 17) % 1009) / 1009.0,
        ((seed * 29) % 1013) / 1013.0,
        ((seed * 43) % 1019) / 1019.0,
    )
    coordinate_scale = float(finish.get("_coordinate_scale", 1.0))
    mapping.inputs["Scale"].default_value = (
        coordinate_scale, coordinate_scale, coordinate_scale)
    noise.inputs["Scale"].default_value = float(micro["scale"])
    bump.inputs["Strength"].default_value = float(micro["strength"])
    bump.inputs["Distance"].default_value = float(
        finish.get("_distance_m", micro["distance_frac"]))

    links.new(texcoord.outputs["Object"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


PROFILE_SURFACES = {"front", "top", "left"}


def _profile_surface_frame(surface, bounds):
    """Origin and unit-square axes for one supported carton surface."""
    x0, y0, z0 = bounds["min"]
    x1, y1, z1 = bounds["max"]
    if surface == "front":
        return (mathutils.Vector((x0, y0, z1)),
                mathutils.Vector((x1 - x0, 0.0, 0.0)),
                mathutils.Vector((0.0, 0.0, z0 - z1)),
                mathutils.Vector((0.0, -1.0, 0.0)))
    if surface == "top":
        return (mathutils.Vector((x0, y0, z1)),
                mathutils.Vector((x1 - x0, 0.0, 0.0)),
                mathutils.Vector((0.0, y1 - y0, 0.0)),
                mathutils.Vector((0.0, 0.0, 1.0)))
    if surface == "left":
        return (mathutils.Vector((x0, y0, z1)),
                mathutils.Vector((0.0, y1 - y0, 0.0)),
                mathutils.Vector((0.0, 0.0, z0 - z1)),
                mathutils.Vector((-1.0, 0.0, 0.0)))
    raise SystemExit(
        f"[render_driver] unsupported carton_profile surface {surface!r}")


def _parent_carton_detail(obj, box, kind, surface):
    obj["carton_detail_kind"] = kind
    obj["carton_detail_surface"] = surface
    obj.parent = box
    obj.matrix_parent_inverse = box.matrix_world.inverted()


def build_full_surface_materials(design, finish=None):
    """Materials proven to cover an entire measured carton surface.

    A flap or seam is separate geometry, so it cannot inherit ink from the
    coplanar design curve.  Propagation is allowed only when the manifest
    already proves one solid, hole-free part covers the whole 0..1 surface;
    anything partial remains substrate rather than becoming an inferred wrap.
    """
    materials = {}
    for field_index, field in enumerate((design or {}).get("fields") or []):
        surface = field.get("surface", "front")
        parts = field.get("parts") or []
        if (surface not in PROFILE_SURFACES
                or float(field.get("coverage_pct", 0.0)) < 99.9
                or len(parts) != 1):
            continue
        part = parts[0]
        outline = part.get("outline") or []
        if (float(part.get("area_pct", 0.0)) < 99.9
                or part.get("holes")
                or len(outline) < 4
                or not part.get("fill")):
            continue
        us = [float(point[0]) for point in outline]
        vs = [float(point[1]) for point in outline]
        if (abs(min(us)) > 1e-6 or abs(max(us) - 1.0) > 1e-6
                or abs(min(vs)) > 1e-6 or abs(max(vs) - 1.0) > 1e-6):
            continue
        role = field.get("role", field_index)
        materials[surface] = make_carton_material(
            f"design_{role}_0_mat", part["fill"], finish)
    return materials


def build_visible_carton_details(box, profile, face_w, face_h, depth, bounds,
                                 surface_materials=None):
    """Build only the measured external carton construction.

    The profile owns visible exterior facts. No hidden/internal flap is inferred,
    and no SKU branch exists here: a manifest without a profile takes the former
    cube path without modifiers or child geometry.
    """
    if not profile:
        return []
    if profile.get("profile_version") != "1.0":
        raise SystemExit(
            "[render_driver] unsupported carton_profile profile_version "
            f"{profile.get('profile_version')!r}")
    for section in ("visible_flaps", "visible_seams"):
        for row in profile.get(section) or []:
            if row.get("surface") not in PROFILE_SURFACES:
                raise SystemExit(
                    "[render_driver] unsupported carton_profile surface "
                    f"{row.get('surface')!r}")

    base = min(face_w, face_h, depth)
    edge_radius = base * float(profile["edge_radius_frac"])
    board_thickness = base * float(profile["board_thickness_frac"])
    if edge_radius > 0:
        bevel = box.modifiers.new(name="carton_edge_radius", type="BEVEL")
        bevel.width = edge_radius
        bevel.segments = 3
        bevel.limit_method = "ANGLE"
        bevel.harden_normals = True
    box["carton_profile_version"] = "1.0"
    box["carton_board_thickness_m"] = board_thickness

    body_mat = box.data.materials[0] if box.data.materials else None
    surface_materials = surface_materials or {}
    gap_mat = make_material("carton_gap_mat", "#20242A",
                            roughness=MATTE_ROUGHNESS)
    built = []

    def rectangular_detail(name, row, kind):
        surface = row["surface"]
        origin, u_axis, v_axis, normal = _profile_surface_frame(surface, bounds)
        u0, u1 = float(row["u0"]), float(row["u1"])
        v0, v1 = float(row["v0"]), float(row["v1"])
        stand_off = base * float(row["stand_off_frac"])
        centre = (origin + u_axis * ((u0 + u1) / 2.0)
                  + v_axis * ((v0 + v1) / 2.0)
                  + normal * (stand_off + board_thickness / 2.0))
        du = u_axis.length * (u1 - u0)
        dv = v_axis.length * (v1 - v0)
        if surface == "front":
            dimensions = (du, board_thickness, dv)
        elif surface == "top":
            dimensions = (du, dv, board_thickness)
        else:  # left
            dimensions = (board_thickness, du, dv)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=centre)
        obj = bpy.context.active_object
        obj.name = name
        obj.scale = dimensions
        bpy.ops.object.transform_apply(scale=True)
        detail_mat = surface_materials.get(surface, body_mat)
        if detail_mat is not None:
            obj.data.materials.append(detail_mat)
        _parent_carton_detail(obj, box, kind, surface)
        built.append(obj)

    def line_detail(name, surface, points, width_m, normal_offset,
                    kind, material, uv_shift=(0.0, 0.0)):
        origin, u_axis, v_axis, normal = _profile_surface_frame(surface, bounds)
        curve = bpy.data.curves.new(name, type="CURVE")
        curve.dimensions = "3D"
        curve.resolution_u = 1
        curve.bevel_resolution = 1
        curve.bevel_depth = width_m / 2.0
        curve.use_fill_caps = True
        spline = curve.splines.new("POLY")
        spline.points.add(len(points) - 1)
        for index, uv in enumerate(points):
            u = float(uv[0]) + uv_shift[0]
            v = float(uv[1]) + uv_shift[1]
            point = (origin + u_axis * u + v_axis * v
                     + normal * normal_offset)
            spline.points[index].co = (*point, 1.0)
        obj = bpy.data.objects.new(name, curve)
        bpy.context.scene.collection.objects.link(obj)
        obj.data.materials.append(material)
        _parent_carton_detail(obj, box, kind, surface)
        built.append(obj)

    for index, flap in enumerate(profile.get("visible_flaps") or []):
        rectangular_detail(f"carton_flap_{index}", flap, "flap")

    for index, seam in enumerate(profile.get("visible_seams") or []):
        surface = seam["surface"]
        points = seam["polyline"]
        seam_width = base * float(seam["width_frac"])
        gap_width = base * float(seam["gap_frac"])
        normal_offset = board_thickness + max(seam_width, gap_width) / 2.0
        if gap_width > 0:
            line_detail(f"carton_gap_{index}", surface, points, gap_width,
                        normal_offset, "gap", gap_mat)
        # The lip runs directly beside the gap. The current measured seam is
        # horizontal, but the dominant-axis branch also gives vertical evidence
        # an unambiguous adjacent side without inventing a topology.
        first, last = points[0], points[-1]
        if abs(float(last[0]) - float(first[0])) >= abs(
                float(last[1]) - float(first[1])):
            shift = (0.0, -float(seam["width_frac"]))
        else:
            shift = (float(seam["width_frac"]), 0.0)
        seam_mat = surface_materials.get(surface, body_mat)
        if seam_width > 0 and seam_mat is not None:
            line_detail(f"carton_seam_{index}", surface, points, seam_width,
                        normal_offset, "seam", seam_mat, shift)

    if len(built) > 32:
        raise SystemExit(
            f"[render_driver] carton_profile built {len(built)} visible detail "
            "objects; maximum is 32")
    return built


# Row 6 of the front-panel grid (src/passport_generator.py) specifies a ~4mm
# band. reference_analysis.md §5 put it at "roughly 8-12%" of the front-face
# height, but §9 flagged that as eyeballed rather than pixel-measured — and it
# was too generous: measuring the accent band in all nine curated references
# gives 2.9-6.1% (median 4.0%). At 8% the band came out ~50% too thick on T1 and
# ~135% too thick on T_VERT_VIAL. The millimetre figure stays the target and the
# measured percentages bound it.
STRIPE_TARGET_M = 0.004
STRIPE_MIN_FRAC = 0.03
STRIPE_MAX_FRAC = 0.06

# Matte, uncoated cardstock (reference_analysis.md §4: "roughness reads high
# ~0.6-0.8 in a Principled-BSDF sense", §8: raise the body from 0.5). The stripe
# and badge are printed ink on that same board, and §3 records no hard specular
# highlight anywhere on the carton, so every carton surface takes this value —
# leaving the stripe semi-gloss would put a sheen on it the references lack.
# The background plane is deliberately rougher still and keeps its own 0.9.
MATTE_ROUGHNESS = 0.7
# Cap height and width the dosage takes inside its colour block. Measured off
# the Cialis reference: "10 mg" sets to roughly half the block's height and
# runs to about four fifths of its width.
DOSAGE_BLOCK_CAP_FRAC = 0.5
DOSAGE_BLOCK_FILL_FRAC = 0.82
# A block narrower than this cannot hold a dosage legibly, whatever its area.
# Valium's largest filled rectangle is the navy bar down its edge, and reversing
# "5mg" into it set the string at a few millimetres against the carton's side --
# the reference puts that dosage in the pink band across the face instead.
DOSAGE_BLOCK_MIN_WIDTH_FRAC = 0.10

# The top-right brand badge (reference_analysis.md §5, second of the two places
# brand colour is allowed to appear). Measured across the nine references: the
# square runs 21-37% of the SHORTER front-face edge — a tighter fit than either
# face-height (12-29%) or face-width (7-37%) alone — inset ~5% of face width from
# the right edge and ~3% of face height from the top.
BADGE_SIDE_FRAC         = 0.25
BADGE_MARGIN_RIGHT_FRAC = 0.05
BADGE_MARGIN_TOP_FRAC   = 0.03

# ── the front-panel label grid ───────────────────────────────────────────────
# Fonts are VENDORED, not taken from the system. The project's determinism
# invariant (see the world-background and film-response comments) says the same
# input must give the same pixel on any machine, and a system font silently
# changes the render on a machine that lacks it. DejaVu is redistributable —
# 05_assets/blender/fonts/LICENSE_DEJAVU. It reads wider and rounder than the
# neo-grotesque in the references; that is a known, accepted difference.
FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT_REGULAR = "DejaVuSans.ttf"
FONT_BOLD    = "DejaVuSans-Bold.ttf"

# Near-black rather than pure black: the references measure ~#1A1A1A on the
# darkest glyph interiors, and pure black on matte board reads artificially hard.
LABEL_INK = "#1A1A1A"

# The grid, measured off the references in the FRONT FACE's own coordinates —
# u across (0 = near vertical corner, 1 = far edge), v down (0 = top, 1 = bottom).
# See reference_analysis.md §6 for the row order and the measurement pass that
# produced these numbers.
LABEL_LEFT_FRAC  = 0.07     # every row starts here
LABEL_RIGHT_FRAC = 0.95     # the right-aligned unit count ends here

# TYPE SIZE IS NOT ONE RULE. Measuring the references shows two different laws,
# and using either one for everything is what made the first attempt wrong:
#
#   brand name  scales with the carton — 6.3mm on a T3 to 30.6mm on a
#               T_VERT_VIAL (4.9x), but a steady 0.131-0.209 of the FACE HEIGHT
#               (1.6x). It is the hero element, sized to the package.
#   small print holds its size in MILLIMETRES — the bottom row measures 4.4-5.5mm
#               on eight of nine templates (1.9x) while varying 3.5x as a
#               fraction of the face. It is set to be read, not to fill space.
#
# Driving the small print off face height, as this originally did, gives 2.9mm on
# a T1 (unreadably small against a 5.5mm reference) and 8.8mm on a T_VERT_VIAL,
# where "2000iu" and "10 Vials" then close on each other in the bottom row.
BRAND_TOP_FRAC   = 0.10     # measured 0.07-0.12 across templates
BRAND_LINE_FRAC  = 0.15     # cap height, fraction of face height (0.131-0.209)
# Baseline-to-baseline distance when the name wraps, as a multiple of cap height.
# The reference's two brand lines sit at v 0.110 and 0.260 over a 0.12 cap, so
# 1.25 — tighter than Blender's default single spacing, which at this cap height
# would push the second line into the ingredient row.
BRAND_LINE_PITCH = 1.25
BRAND_MAX_LINES  = 2
# Clear space the brand block must leave above the ingredient row.
BRAND_INGREDIENT_GAP_FRAC = 0.01
# The brand block shares its rows with the badge in the top-right corner, so it
# has to stop short of it. This gap is measured from where the badge ACTUALLY
# lands rather than assumed: the badge is sized off the shorter face edge, so on
# a portrait carton it eats a much larger share of the width (u from 0.70 on
# T_VERT_VIAL) than on a landscape one (0.84 on T_MULTIPACK). A single fixed
# limit that clears one shape runs straight into the other.
BRAND_BADGE_GAP_FRAC = 0.03

INGREDIENT_TOP_FRAC = 0.46  # measured 0.44-0.48
INGREDIENT_CAP_M    = 0.0055   # reference 3.8-7.7mm, median 5.5

# ...but an absolute size still has to yield on a shallow face. A T3 carton is
# only 35mm tall, and 5.5mm of ingredient plus 5mm of bottom row inside the
# 11.9mm the grid leaves between those two rows leaves them touching. The
# references do the same thing: T3 carries the smallest type in the set, 3.8mm.
# Capping the small print at this fraction of face height reproduces that
# (0.12 x 35 = 4.2mm) and changes nothing on a normal carton, where the absolute
# size is already the smaller of the two.
SMALL_PRINT_MAX_FRAC = 0.12

BOTTOM_ROW_TOP_FRAC = 0.80  # measured 0.76-0.83; dosage left, unit count right
BOTTOM_ROW_CAP_M    = 0.0050   # reference 4.4-8.5mm, eight of nine at 4.4-5.5
# The bottom row holds two strings that grow toward each other from opposite
# margins, so each is capped at half the space with this gutter between them.
# Sizing them independently lets them meet in the middle on a narrow face: a
# 50mm-wide T_VERT_DROPPER put "2000iu" and "10 Vials" through each other.
# Absolute, not a fraction of the face: on a 55mm-wide T_VERT_INHALER a 4%
# gutter is 2.2mm, which between two 5mm capitals reads as no gap at all.
BOTTOM_ROW_GUTTER_M = 0.006
# Clear space between the bottom row's descenders and the accent stripe.
BOTTOM_ROW_CLEARANCE_FRAC = 0.02


# ── the side panel ───────────────────────────────────────────────────────────
# The visible side panel is the carton's local -X face. The camera looks along
# +Y, the carton is rotated by +ROTATION_DEG about Z, and that turns the -X
# normal to (-cos, -sin, 0): the negative Y component means it faces the camera
# and the negative X puts it on the left of frame. The +X face turns away and is
# never seen. True for both rotation angles the project uses, 35 and 27.5.
#
# WHAT THE REFERENCE PANEL ACTUALLY CONTAINS, and why most of it is not copied:
# magnifying the side panel of the curated renders shows a 2D code that is a blob
# of organic noise with no quiet zone, no finder pattern and no clock track; a
# LOT/EXP block whose values read "BAWNL TE9?" and "SLAQF FD9T"; and a microprint
# paragraph that is not text at all. That is the same failure reference_analysis
# §7 records as "Datels". The reference is evidence of LAYOUT, not of CONTENT.
#
# So: the barcode is a real, decodable Code 128 of the SKU id; LOT and EXP are
# printed as empty field labels, which is what a real carton carries because the
# batch and expiry are inkjetted at packing time (and the T_VERT_VIAL reference
# shows exactly that — a boxed LOT and a bare EXP with no values); and the small
# block prints strings the manifest already holds. Nothing here is invented.
PANEL_MARGIN_FRAC   = 0.10   # of panel width, kept clear at both edges
BARCODE_TOP_FRAC    = 0.06   # of panel height, where the symbol starts
BARCODE_LEN_FRAC    = 0.40   # of panel height the symbol spans
BARCODE_BAR_FRAC    = 0.55   # of panel width the bars run across
BARCODE_HRI_CAP_M   = 0.0025 # human-readable line under the symbol
FIELD_TOP_FRAC      = 0.56   # LOT / EXP block
FIELD_CAP_M         = 0.0035
FIELD_RULE_FRAC     = 0.45   # rule length, of panel width
DATA_BLOCK_TOP_FRAC = 0.74
DATA_BLOCK_GAP_FRAC = 0.03   # clear space under the LOT/EXP block
PANEL_BOTTOM_MARGIN_FRAC = 0.02  # clear space above the carton's bottom edge
DATA_BLOCK_CAP_M    = 0.0022
# Code 128 cannot be printed below roughly this module width and still scan.
BARCODE_MIN_MODULE_M = 0.00019


# Code 128 bar/space widths, symbol values 0..106. Each entry is six digits: the
# widths of bar, space, bar, space, bar, space in modules, totalling 11.
_CODE128_PATTERNS = (
    "212222", "222122", "222221", "121223", "121322", "131222", "122213",
    "122312", "132212", "221213", "221312", "231212", "112232", "122132",
    "122231", "113222", "123122", "123221", "223211", "221132", "221231",
    "213212", "223112", "312131", "311222", "321122", "321221", "312212",
    "322112", "322211", "212123", "212321", "232121", "111323", "131123",
    "131321", "112313", "132113", "132311", "211313", "231113", "231311",
    "112133", "112331", "132131", "113123", "113321", "133121", "313121",
    "211331", "231131", "213113", "213311", "213131", "311123", "311321",
    "331121", "312113", "312311", "332111", "314111", "221411", "431111",
    "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114",
    "413111", "241112", "134111", "111242", "121142", "121241", "114212",
    "124112", "124211", "411212", "421112", "421211", "212141", "214121",
    "412121", "111143", "111341", "131141", "114113", "114311", "411113",
    "411311", "113141", "114131", "311141", "411131", "211412", "211214",
    "211232", "233111",
)
_CODE128_STOP = "2331112"          # seven elements: the stop bar is 2 wide
_CODE128_START_B = 104


def encode_code128b(text: str):
    """Encode *text* as Code 128 subset B and return its module widths.

    Returns a list of integers: alternating bar, space, bar, space ... starting
    with a bar, each the width of that run in modules. Quiet zones are NOT
    included; the caller adds them, because they are part of laying the symbol
    out rather than of encoding it.

    A real, decodable symbol rather than a decorative one. That is not vanity:
    the reference renders put a 2D code on this panel that cannot be scanned, and
    reproducing an unscannable barcode would be re-creating by hand exactly the
    hallucination this engine exists to eliminate. tests/test_blender_carton.py
    decodes what comes out of here with an independent reader.
    """
    for ch in text:
        if not 32 <= ord(ch) <= 126:
            raise ValueError(
                f"[render_driver] {ch!r} (U+{ord(ch):04X}) is outside Code 128 "
                f"subset B, which covers ASCII 32-126; cannot encode {text!r}")
    values = [_CODE128_START_B] + [ord(c) - 32 for c in text]
    checksum = values[0]
    for i, v in enumerate(values[1:], start=1):
        checksum += i * v
    values.append(checksum % 103)
    widths = []
    for v in values:
        widths.extend(int(d) for d in _CODE128_PATTERNS[v])
    widths.extend(int(d) for d in _CODE128_STOP)
    return widths


def _load_font(filename: str):
    """Vendored font, loaded once per Blender session."""
    existing = bpy.data.fonts.get(filename)
    if existing is not None:
        return existing
    font = bpy.data.fonts.load(str(FONT_DIR / filename))
    font.name = filename
    return font


def _text_dimensions(obj):
    """World-space size of a text object, after evaluation.

    Text has no mesh until the depsgraph builds one, so `obj.dimensions` is zero
    until it is evaluated. Because the object is rotated upright, the returned
    axes read (width, thickness, height).
    """
    dg = bpy.context.evaluated_depsgraph_get()
    return obj.evaluated_get(dg).dimensions


_CAP_RATIO_CACHE = {}
_CAP_DROP_CACHE = {}

# How far a MEASURED row may be narrowed before its size gives way instead. The
# printed faces on the references are narrower than DejaVu -- measured over the
# twenty measured rows, DejaVu needs a median of 1.29 times the width the same
# string occupies on the photograph -- so a row set at the reference's measured
# cap height often will not fit the box it was measured in. 0.80 is where
# artificial condensing starts to distort stems.
CONDENSE_FLOOR = 0.80


def _cap_ratio(font) -> float:
    """Cap height per unit of Blender's text `size`, measured for this font.

    `size` is not the cap height and the two are not related by any documented
    constant — for the vendored DejaVu the ratio comes out near 0.49. Measuring
    it rather than hardcoding it means the grid constants below can be stated as
    what they actually are, fractions of the face that a capital letter fills,
    directly comparable to the numbers measured off the references. It also means
    swapping the font does not silently resize every label in the catalogue.
    """
    key = font.name
    if key not in _CAP_RATIO_CACHE:
        bpy.ops.object.text_add(location=(0.0, 0.0, 0.0))
        probe = bpy.context.active_object
        probe.data.body = "H"
        probe.data.font = font
        probe.data.size = 1.0
        _CAP_RATIO_CACHE[key] = _text_dimensions(probe).y or 1.0
        bpy.data.objects.remove(probe, do_unlink=True)
    return _CAP_RATIO_CACHE[key]


def _balanced_two_lines(text: str) -> str:
    """Split on the word break that leaves the two lines closest in length."""
    words = text.split()
    if len(words) < 2:
        return text
    best, best_diff = None, None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        diff = abs(len(a) - len(b))
        if best_diff is None or diff < best_diff:
            best, best_diff = (a, b), diff
    return "\n".join(best)


def _reverse_ink(fill_hex: str):
    """Ink that reads against *fill_hex*: white on a dark surface, near-black on a light one.

    Chosen from the surface's own measured colour rather than fixed, because the
    sample carries both -- Cialis and Ativan reverse white out of a dark green,
    Lexotanil sets dark type on a mid teal band.

    Judged in sRGB, NOT in the linear values Blender is fed. Linear luminance of
    a mid sRGB tone is far below its perceived one -- sRGB 0.5 is linear 0.21 --
    so a threshold applied to linear values calls almost everything dark and
    reverses to white. That stayed hidden while this only ran on blocks, which in
    this sample happen to be genuinely dark; measured on the surfaces a MEASURED
    row can land on, it flips three of them wrongly. Imovane's `#BCBCB2` is a
    light grey at 0.734 perceived and 0.499 linear -- a hair under the old bar,
    and white type on it would be all but invisible.
    """
    h = (fill_hex or "#000000").lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return make_material(f"reversed_{('dark' if luma < 0.5 else 'light')}",
                         "#FFFFFF" if luma < 0.5 else LABEL_INK,
                         roughness=MATTE_ROUGHNESS)


def _point_in_polygon(u, v, outline) -> bool:
    """Ray cast in face coordinates. Written out; the driver imports nothing."""
    inside = False
    n = len(outline)
    for i in range(n):
        x0, y0 = float(outline[i][0]), float(outline[i][1])
        x1, y1 = float(outline[(i + 1) % n][0]), float(outline[(i + 1) % n][1])
        if (y0 > v) != (y1 > v) and y1 != y0:
            if u < x0 + (v - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
    return inside


#: Bounding boxes per design, keyed by the design dict's identity. One scene is
#: built per process, so the design object outlives every lookup against it.
_PART_CACHE = {}


def _drawable_mark_parts(mark):
    """Base, then colour overlays; mirrors src.mark_geometry without imports.

    Blender runs outside the project interpreter. Keep this accessor limited to
    paint order; validation and approved-mark ownership remain at the boundary.
    """
    return [mark] + list(mark.get("parts") or [])


def _prepared_parts(design):
    """(u0, u1, v0, v1, outline, holes, fill) per drawable surface, in paint order.

    Fields first, then contract 1.10's MARKS, which is the paint order: a mark's
    `z` continues past the last field's on all twelve cartons that carry one, so
    "the last containing surface wins" reads the same sequence the driver draws.

    TWO AUDIENCES, ONE LIST, AND THE SECOND ONE WAS MEASURED RATHER THAN
    ASSUMED. This lookup serves an INK -- `_band_fill` and the measured row's
    point test -- and a MOVE, `_one_ink_serves`, the predicate
    `_clear_of_design` accepts a position by. They are not the same question and
    they do not have to have the same answer:

    - the ink's is a principle. A row stands on a surface and a mark IS one;
      inking against a surface you refuse to look at is simply wrong.
    - the mover's is contingent. Nothing says the grid should walk a row across
      the face to dodge a logo, and whether it should is a fact about the
      cartons in front of it.

    So they were split behind a parameter and measured apart -- and the mover
    wants marks too, so the parameter is gone and this is one list again. If a
    carton ever enters the group whose mark makes the mover move a row somewhere
    worse, the seam is a `with_marks` flag away; the reason it is not here now is
    that nothing takes the other branch, and an unused value that decides where
    type goes is the same objection this file already records against the joint
    two-axis search.
    """
    key = id(design)
    got = _PART_CACHE.get(key)
    if got is None:
        got = []
        for field in (design or {}).get("fields") or []:
            if field.get("surface", "front") != "front":
                continue
            for part in field.get("parts") or []:
                outline = part.get("outline") or []
                if len(outline) < 3:
                    continue
                us = [float(q[0]) for q in outline]
                vs = [float(q[1]) for q in outline]
                holes = [ring for ring in (part.get("holes") or [])
                         if len(ring) >= 3]
                if "fill" not in part:
                    # SystemExit for the same reason `z` and `holes` are:
                    # Blender exits 0 after an ordinary uncaught exception, so a
                    # KeyError here reads as a successful render.
                    raise SystemExit(
                        f"[render_driver] design field "
                        f"{field.get('role')!r} carries a part with no `fill`. "
                        f"That is contract 1.9 and it is required; a manifest "
                        f"written before it must be regenerated by Stage 1 "
                        f"rather than painted its field's colour, which is what "
                        f"33 of the group's 75 parts should not be.")
                # The PART's fill, not the field's: a measured row reversed out
                # of a part is set against what is actually printed under it,
                # and under contract 1.9 that is not always the field's colour.
                got.append((min(us), max(us), min(vs), max(vs),
                            outline, holes, part["fill"]))
        # CONTRACT 1.10's marks. This went in once, came out whole on a misread
        # measurement, and went back in: `_one_ink_serves` carries the figures,
        # because that is the function the misreading was about.
        for m_i, mark in enumerate((design or {}).get("marks") or []):
            for p_i, part in enumerate(_drawable_mark_parts(mark)):
                outline = part.get("outline") or []
                if len(outline) < 3:
                    continue
                if "fill" not in part:
                    raise SystemExit(
                        f"[render_driver] design mark {m_i} "
                        f"({mark.get('key')!r}) part {p_i} carries no `fill`; "
                        f"regenerate the manifest from Stage 1.")
                us = [float(q[0]) for q in outline]
                vs = [float(q[1]) for q in outline]
                holes = [ring for ring in (part.get("holes") or [])
                         if len(ring) >= 3]
                got.append((min(us), max(us), min(vs), max(vs),
                            outline, holes, part["fill"]))
        _PART_CACHE[key] = got
    return got


def _surface_fill(design, u, v):
    """The design surface printed under (u, v), or None where the board shows.

    A measured row lands wherever the reference puts it, and on these cartons
    that is often ON the design rather than beside it: Kamagra sets its dosage
    inside a teal field covering the lower half of the pack, and our render
    printed "100mg" in near-black on it -- present, correct in position and size,
    and invisible. It was the one measured row the reader could not find in our
    own render.

    Later parts paint over earlier ones, so the last containing part wins, the
    same order build_design_fields draws them in.

    Each part is tried against its bounding box before its outline. That is an
    exact early-out, not an approximation -- a point outside a polygon's box is
    outside the polygon -- and it is worth having because the clearing search
    calls this function a few tens of thousands of times per carton, while a
    single outline here runs to 488 vertices. The boxes are computed once per
    design and kept in `_PART_CACHE`, in the order the parts are drawn, so the
    "last containing part wins" rule reads off the same sequence as before.

    Contract 1.10's marks are in that sequence, last. `_prepared_parts` records
    why, and why the two callers that wanted different answers turned out not to.
    """
    found = None
    for u0, u1, v0, v1, outline, holes, fill in _prepared_parts(design):
        if u < u0 or u > u1 or v < v0 or v > v1:
            continue
        if not _point_in_polygon(u, v, outline):
            continue
        # Contract 1.8: inside a hole is not inside the part. The board shows
        # there -- or a field behind it, which the parts already drawn will have
        # reported, so leaving `found` alone is exactly right rather than
        # merely convenient.
        if any(_point_in_polygon(u, v, ring) for ring in holes):
            continue
        found = fill
    return found


def _add_text(name, body, font, cap_h, ink_mat, x, z, y, align="LEFT"):
    """One row of the label, standing on the front face.

    A text object is created lying in the XY plane facing +Z. The carton's front
    face points -Y, so rotating +90 deg about X turns the glyph plane to face it
    while leaving the reading direction on +X and the ascenders on +Z.

    `cap_h` is the height a capital letter should occupy, not Blender's `size` —
    see _cap_ratio(). Sizing rows by cap height keeps the type consistent between
    rows whose strings happen to contain different ascenders and descenders.
    """
    bpy.ops.object.text_add(location=(x, y, z))
    t = bpy.context.active_object
    t.name = name
    t.data.body = body
    t.data.font = font
    t.data.size = cap_h / _cap_ratio(font)
    t.data.align_x = align
    t.data.align_y = "TOP"
    t.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    t.data.materials.append(ink_mat)
    return t


def _fit_above(t, floor_z):
    """Shrink a row until its lowest point clears `floor_z`, top left in place.

    Needed for the brand name once it wraps. Two lines at the single-line cap
    height do not fit the band the grid leaves above the ingredient row: measured
    over the catalogue, 18 of 391 names wrap, and every one of them ran past
    v 0.46 and into the row below. The references do the same thing — T1's
    two-line name is set at a 0.12 cap where a one-liner gets more.

    The correction is exact in one pass. Text scales about its origin, which
    align_y="TOP" puts at the top of the block, so shrinking by
    (allowed / actual) lands the bottom precisely on the floor.
    """
    from mathutils import Vector
    dg = bpy.context.evaluated_depsgraph_get()
    lowest = min((t.matrix_world @ Vector(c)).z
                 for c in t.evaluated_get(dg).bound_box)
    if lowest >= floor_z:
        return t
    actual, allowed = t.location.z - lowest, t.location.z - floor_z
    if actual > 0 and allowed > 0:
        t.data.size *= allowed / actual
    return t


def _required_lift(t, floor_z):
    """How far this row would have to rise to clear `floor_z`. Never negative."""
    from mathutils import Vector
    dg = bpy.context.evaluated_depsgraph_get()
    lowest = min((t.matrix_world @ Vector(c)).z
                 for c in t.evaluated_get(dg).bound_box)
    return max(floor_z - lowest, 0.0)


def _line_breaks(t) -> int:
    """How many line breaks this row carries, i.e. its line count minus one."""
    return (t.data.body or "").count(chr(10))


def _overlaps_block(t, block) -> bool:
    """Does this built row's box stand over that colour block?

    The BOX and not the cap band, and that is the whole point here: what runs
    into a block is the row's descenders and the space its second line takes,
    not its capitals. On `62-min` the brand's cap band clears the dosage's own
    band inside the block by 0.1mm while its box covers 68.3% of the block, and
    the render shows "Active" lying across the bar.
    """
    x_lo, x_hi = _x_span(t)
    z_lo, z_hi = _z_span(t)
    return not (x_hi <= block["x0"] or x_lo >= block["x1"]
                or z_hi <= block["z0"] or z_lo >= block["z1"])


def _block_is_taken(block, texts, font, cap_frac, fill_frac):
    """Would a dosage set in this colour block run into a row already placed?

    `dosage_block` is `blocks[0]` -- the first block the design happens to yield
    -- and nothing checked what else stands there. On `221-min` that is the
    salmon panel behind the wordmark, so "40mg" was reversed into it on top of
    "Inderal" and the two printed through one another: measured on the built
    scene `label_brand` spanned v 0.141-0.291 and `label_dosage` v 0.164-0.285,
    the OCR barrier read `Indepal`, and brand, dosage and unit count were all
    unfindable.

    The question is whether the DOSAGE would collide, not whether anything at
    all touches the block. Asking the looser question moved the dosage off two
    further cartons (`133-min`, `362-min`) whose blocks are merely grazed by a
    row's cap band and where nothing was wrong. So the band tested here is the
    one the placement below actually uses: the block's cap height, centred in
    it, across the width the text is fitted to.

    Cap bands throughout, not bounding boxes -- a box carries descender space
    that reaches where no glyph does.
    """
    bh = block["z1"] - block["z0"]
    bw = block["x1"] - block["x0"]
    cap = bh * cap_frac
    # Exactly where the placement below puts it: the same origin z, then
    # down by the font's cap drop, because the row is set align_y="TOP".
    # Taking the block-centred band instead sits the test a cap-drop too
    # high and it collides with the row above -- which moved the dosage on
    # `133-min` and `362-min`, where nothing was wrong.
    origin_z = block["z1"] - 0.5 * (bh - cap)
    z_hi = origin_z - _cap_drop(font) * (cap / _cap_ratio(font))
    z_lo = z_hi - cap
    mid = 0.5 * (block["x0"] + block["x1"])
    x_lo = mid - 0.5 * bw * fill_frac
    x_hi = mid + 0.5 * bw * fill_frac
    for t in texts:
        o_x_lo, o_x_hi = _x_span(t)
        if o_x_hi <= x_lo or o_x_lo >= x_hi:
            continue
        o_top = t.location.z - _cap_drop(t.data.font) * t.data.size
        # EVERY line of the row, not the first. A wrapped brand reaches a whole
        # line pitch further down for each line after the first, and testing
        # only the first band declared `62-min`'s amber bar free: "Cialis Super
        # Active" wraps, its second line descends to v 0.450, the bar sits at
        # v 0.412-0.465, and "20mg" was reversed into it under the tail of the
        # brand -- 2.64mm of overlap, which the catalogue sweep flags and
        # nothing else did.
        #
        # `space_line` is a multiple of `size`, so the pitch in world units is
        # the product. One carton in the group wraps its brand AND offers a
        # block, which is why this had gone unseen.
        o_bot = (o_top - _cap_ratio(t.data.font) * t.data.size
                 - _line_breaks(t) * t.data.space_line * t.data.size)
        if os.environ.get("PHARMAGEN_CLEAR_DEBUG"):
            print(f"[block] {t.name} x {o_x_lo:.4f}..{o_x_hi:.4f} "
                  f"band {o_bot:.4f}..{o_top:.4f} breaks={_line_breaks(t)} "
                  f"vs block x {x_lo:.4f}..{x_hi:.4f} band {z_lo:.4f}..{z_hi:.4f}",
                  flush=True)
        if o_bot >= z_hi or o_top <= z_lo:
            continue
        return True
    return False


def _lift_row(texts, floor_z, spans=(), gap=0.0):
    """Raise a whole row by one amount so it clears `floor_z` and any measurement.

    The bottom row is positioned from the top of the face while its size is an
    absolute millimetre value, so on a short face the two assumptions collide:
    5mm of type hung from v=0.80 of a 55mm carton drives the descender of "40mg"
    through the accent stripe. Anchoring against the obstacle beats guessing a v
    that happens to clear it for every carton in the catalogue.

    A measured row is the other obstacle, and it is the one that cannot be
    guessed at: on `340-min` the reference sets the unit count at v 0.869-0.912
    in the bottom-LEFT corner, which is where the grid hangs the dosage, and
    "0.5mg" and "30 Pills" were printed through one another. Here the grid row
    rises rather than drops — at the foot of the face there is nowhere below to
    go — which is why this is not the same call as `_clear_below`.

    Crucially the lift is shared. Measuring each string separately moves "40mg",
    which has a descender, further than "10 Pills", which has none — and the two
    stop sharing a baseline, which is exactly what a reader notices.
    """
    if not texts:
        return texts
    lift = 0.0
    for t in texts:
        floor = floor_z
        lo, hi = _z_span(t)
        x_lo, x_hi = _x_span(t)
        for o_lo, o_hi, o_x_lo, o_x_hi in spans:
            # Both axes, and the row must actually RUN INTO the measurement:
            # clearing every measured row that merely shares some column threw
            # Kamagra's whole bottom row to the top of the carton, above an
            # ingredient row it sat 0.6 of the face below and never touched.
            if x_hi <= o_x_lo or x_lo >= o_x_hi:
                continue
            if hi <= o_lo or lo >= o_hi:
                continue
            floor = o_hi + gap if floor is None else max(floor, o_hi + gap)
        if floor is not None:
            lift = max(lift, _required_lift(t, floor))
    if lift:
        for t in texts:
            t.location.z += lift
    return texts


def _z_span(t):
    """The row's built extent up the face: (lowest, highest) in world Z."""
    from mathutils import Vector
    dg = bpy.context.evaluated_depsgraph_get()
    zs = [(t.matrix_world @ Vector(c)).z for c in t.evaluated_get(dg).bound_box]
    return min(zs), max(zs)


def _x_span(t):
    """The row's built extent across the face: (left, right) in world X."""
    from mathutils import Vector
    dg = bpy.context.evaluated_depsgraph_get()
    xs = [(t.matrix_world @ Vector(c)).x for c in t.evaluated_get(dg).bound_box]
    return min(xs), max(xs)


def _cap_drop(font) -> float:
    """How far below the align_y="TOP" origin a capital's top sits, per unit size.

    `align_y="TOP"` pins the top of the font's LINE box, which stands above the
    tallest glyph by the font's own ascent-above-cap. Anchoring a measured row
    by that origin put every one of them BELOW its own target: measured off the
    built geometry, eight rows on three cartons, 0.109 to 0.231 of a cap height,
    none above.

    Unlike a row's INK, a row's cap line does not depend on the string — it is a
    position in the font's line box — so this is one measurement per face rather
    than one per row, and it stays exact after `_fit_width` rescales the object.
    """
    key = font.name
    if key not in _CAP_DROP_CACHE:
        bpy.ops.object.text_add(location=(0.0, 0.0, 0.0))
        probe = bpy.context.active_object
        probe.data.body = "H"
        probe.data.font = font
        probe.data.size = 1.0
        probe.data.align_y = "TOP"
        dg = bpy.context.evaluated_depsgraph_get()
        top = max(c[1] for c in probe.evaluated_get(dg).bound_box)
        _CAP_DROP_CACHE[key] = -top
        bpy.data.objects.remove(probe, do_unlink=True)
    return _CAP_DROP_CACHE[key]


def _align_cap_top(t, cap_top_z):
    """Set the row so its CAPITALS start where the reference's do."""
    t.location.z = cap_top_z + _cap_drop(t.data.font) * t.data.size
    return t


def _clear_below(t, spans, gap, floor_z=None):
    """Lower a grid row until it clears every measured row it runs into.

    A measured row lands where the reference puts it, which is anywhere; a grid
    row lands where the grid puts it, which is fixed. `135-min` is where the two
    met: its reference sets the brand at v 0.432-0.562 and the grid sets the
    ingredient at v 0.46, so "Ativan" printed straight through "Lorazepam" and
    the face carried neither legibly — the OCR barrier read nothing at all off
    it, upright or reversed.

    The existing guard covers only the opposite pairing, a grid brand above the
    measured rows. This is the other half of it.

    The obstacles are the MEASURED boxes rather than the built objects, so the
    answer does not depend on which rows happen to have been built yet: a grid
    row placed second must clear a measured row placed fourth just the same.

    Both axes are tested, and the second one is not caution. On `135-min` the
    measured dosage block sits at the right of the same band the brand occupies
    at the left; they share their whole height and touch nowhere. Dropping a row
    for an obstacle it never meets is a wrong layout too, just a quieter one.
    """
    lo, hi = _z_span(t)
    x_lo, x_hi = _x_span(t)
    drop = 0.0
    for o_lo, o_hi, o_x_lo, o_x_hi in spans:
        if x_hi <= o_x_lo or x_lo >= o_x_hi:
            continue
        if hi > o_lo - gap and lo < o_hi:
            drop = max(drop, hi - (o_lo - gap))
    if drop <= 0:
        return t
    t.location.z -= drop
    if floor_z is not None and lo - drop < floor_z:
        sys.stderr.write(
            f"[render_driver] {t.name}: cleared a measured row by dropping "
            f"{drop:.4f}, which puts it below the face. The measurement and the "
            f"grid cannot both be satisfied on this carton.\n")
    return t


def _fit_width(t, max_width, condense=False):
    """Fit a row into the space allowed for it.

    Font size scales the glyphs linearly, so one corrective pass is exact rather
    than iterative. Real data needs this: brand names reach 30 characters and the
    ingredient row reaches 61 ("Sildenafil / Tadalafil / Vardenafil / Avanafil
    (Specimen Mix)"), against faces as narrow as 35mm.

    `condense` narrows the glyphs before reducing the size, and it is passed only
    for a MEASURED row. The reason is which of the two numbers came from a
    measurement: the reference's cap height did, and the width the same string
    needs in DejaVu did not — our face is wider than the printed ones, by a
    median of 1.29 over the twenty measured rows. Shrinking throws away the
    figure that was measured to protect one that was not. Condensing keeps it.

    The floor is where artificial condensing starts to distort stems, which is
    also where a typographer stops using it; past that the size gives way after
    all. Half the shrunk rows need less than 1.25 and come back to their measured
    cap height exactly.

    Deliberately off for the grid path — those 380 cartons' widths are this
    project's own art direction, not a measurement of anything, so there is
    nothing there to protect.
    """
    width = _text_dimensions(t).x
    if not (width > max_width > 0 and width > 0):
        return t
    need = max_width / width
    if not condense:
        t.data.size *= need
        return t
    t.scale.x = max(need, CONDENSE_FLOOR)
    if need < CONDENSE_FLOOR:
        t.data.size *= need / CONDENSE_FLOOR
    return t


def _place_measured_row(name, body, font, row, ink, face_w, face_h, left_x,
                        top_z, y):
    """One label row, set where the real carton sets it.

    Contract 1.4's `type_rows` carries a box per role in face coordinates,
    measured off the reference photograph. Partial by nature: only rows the
    reference could be READ for are measured, so a role with no entry falls
    through to the generic grid below rather than being placed by guesswork.

    The string is the manifest's. The measurement supplies position, size and
    alignment only -- the reference and the catalogue carry different products on
    four of the eleven, and printing the reference's own words would put another
    manufacturer's name on our carton.
    """
    x = {"LEFT": left_x + row["u0"] * face_w,
         "RIGHT": left_x + row["u1"] * face_w,
         "CENTER": left_x + 0.5 * (row["u0"] + row["u1"]) * face_w}[row["align"]]
    if "cap_top_v" not in row:
        raise SystemExit(
            f"[render_driver] {name}: the design's type_rows carry no "
            f"'cap_top_v', which contract 1.5 marks required. An older manifest "
            f"would set this row against its INK box instead of its cap line and "
            f"come out up to 38% oversized. Regenerate via Stage 1.")
    cap_top_z = top_z - row["cap_top_v"] * face_h
    t = _add_text(name, body, font, row["cap_frac"] * face_h, ink,
                  x, cap_top_z, y, align=row["align"])
    # Width first, then the vertical anchor: fitting the width scales the glyphs
    # about the origin, which moves the cap line with it. Aligning before that
    # would be aligning a row that is about to change size.
    _fit_width(t, max((row["u1"] - row["u0"]) * face_w, 0.08 * face_w), condense=True)
    return _align_cap_top(t, cap_top_z)


def build_label(box, label_content: dict, face_w, face_h, left_x, front_y, top_z,
                half_thick, unit_scale, badge_left_x=None, stripe_top_z=None,
                dosage_block=None, type_rows=None, design=None):
    """The printed front panel: brand, ingredient, dosage and unit count.

    Every string is rendered as real text geometry carrying the manifest's bytes
    verbatim. That is the whole point of the Blender engine over a prompt-driven
    one: reference_analysis.md §7 caught the Gemini renders printing "Datels", a
    word that does not exist, on the Lumigan sample. A text object cannot
    hallucinate — it draws the string it is given or nothing at all.

    Rows are placed in the FRONT FACE's own coordinates and the objects are
    parented to the carton before it rotates, exactly like the stripe and badge.
    """
    # A job with no label_content did not come through the contract: the field
    # is `required` in the schema. Rendering an unlabelled carton is a silent
    # content failure, so stop instead — the same reasoning that makes a missing
    # carton block fatal a few lines up.
    if label_content is None:
        raise SystemExit(
            "[render_driver] job has no 'label_content' block, which the render "
            "manifest schema marks required. Rendering an unlabelled packshot "
            "would fail silently. Regenerate the manifest via Stage 1.")
    if not label_content:
        return []

    ink = make_material("label_ink", LABEL_INK, roughness=MATTE_ROUGHNESS)
    regular, bold = _load_font(FONT_REGULAR), _load_font(FONT_BOLD)
    # Sat just proud of the face so the glyphs cannot z-fight with it. The stripe
    # and badge straddle the plane instead; text is flat, so it goes in front.
    #
    # TWICE the standoff, because the design fields straddle the plane too and
    # their front surface lands at exactly one. Cialis is where that showed:
    # its dosage is set inside an olive block, the ink was correctly reversed to
    # white -- the scene dump says (1.0, 1.0, 1.0) -- and the render came back
    # with dark glyphs, because the block's own surface was winning the depth
    # test across them. Nothing about the label was wrong; it was simply behind.
    y = front_y - 2.0 * half_thick
    left = left_x + LABEL_LEFT_FRAC * face_w
    right = left_x + LABEL_RIGHT_FRAC * face_w
    rows = []
    # The rows the GRID placed, as opposed to the ones a measurement placed.
    # Only these get their ink settled from where they finally stand; see the
    # pass at the end of this function.
    grid_rows = []          # (text object, the right limit it may not overrun)

    def v_to_z(v):
        return top_z - v * face_h

    def small_print_cap(cap_m):
        """Absolute size, but never enough to crowd a shallow face."""
        return min(cap_m * unit_scale, SMALL_PRINT_MAX_FRAC * face_h)

    measured = type_rows or {}

    def _ink_for(row):
        """Ink that reads against whatever this row is printed on.

        Marks count, because the reference puts a measured row where the real
        carton puts it, and on `157_Valium` that is across the Roche hexagon.
        A point test at the row's own centre, so it can change what a row is
        printed IN and never where it is.
        """
        fill = _surface_fill(design, 0.5 * (row["u0"] + row["u1"]),
                             0.5 * (row["v0"] + row["v1"]))
        return _reverse_ink(fill) if fill else ink

    # A row placed by measurement and a row placed by the grid know nothing about
    # each other, and on Viagra they collided: the measured unit count sits at
    # v0.224 while the grid sets the brand from v0.10 at a cap that reaches past
    # it, so "Viagra" and "30 Pills" were printed over one another. Any grid row
    # above the topmost measurement now shrinks to clear it, which is what
    # _fit_above already does for the wrapped-brand case.
    # max, not min: the HIGHEST measured row is the first thing a grid row above
    # it can run into. Taking the lowest let the Viagra brand grow straight
    # through the unit count sitting above it, which is the collision this is
    # here to stop.
    measured_top_z = max(
        (top_z - r["v0"] * face_h for r in measured.values()), default=None)
    # Where every measured row stands, so a row still on the grid can be kept
    # out of it. Taken from the measurement rather than from the built objects
    # for the reason _clear_below records.
    measured_spans = [(top_z - r["v1"] * face_h, top_z - r["v0"] * face_h,
                       left_x + r["u0"] * face_w, left_x + r["u1"] * face_w)
                      for r in measured.values()]

    brand = (label_content.get("brand_name_display") or "").strip()
    if brand and "brand_name_display" in measured:
        rows.append(_place_measured_row(
            "label_brand", brand, bold, measured["brand_name_display"],
            _ink_for(measured["brand_name_display"]),
            face_w, face_h, left_x, top_z, y))
    elif brand:
        t = _add_text("label_brand", brand, bold, BRAND_LINE_FRAC * face_h, ink,
                      left, v_to_z(BRAND_TOP_FRAC), y)
        # Run to the badge if there is one, otherwise to the normal right margin.
        brand_right = (badge_left_x - BRAND_BADGE_GAP_FRAC * face_w
                       if badge_left_x is not None else right)
        allowed = max(brand_right - left, 0.1 * face_w)
        if _text_dimensions(t).x > allowed and BRAND_MAX_LINES > 1:
            # Wrapping buys height in exchange for width, so try it before
            # shrinking: a two-line name at full size reads better than a
            # one-line name squeezed to half the cap height.
            t.data.body = _balanced_two_lines(brand)
            t.data.space_line = (BRAND_LINE_PITCH * BRAND_LINE_FRAC * face_h) / t.data.size
        _fit_width(t, allowed)
        # Only ever shrinks, so a one-line name that already fits is untouched.
        floor = v_to_z(INGREDIENT_TOP_FRAC - BRAND_INGREDIENT_GAP_FRAC)
        if measured_top_z is not None:
            floor = max(floor, measured_top_z + BRAND_INGREDIENT_GAP_FRAC * face_h)
        _fit_above(t, floor)
        # A DESIGN's dosage block stops the brand for the same reason the badge
        # does -- it is the thing standing in that column -- and on a design
        # carton no generic badge is drawn, so `badge_left_x` is None and
        # nothing stopped it. `62-min` is the case: "Cialis Super Active" wraps,
        # its second line runs to u 0.801 and the amber bar the design sets the
        # dosage in sits at u 0.634-0.734, so "Active" was printed across the
        # bar with "20mg" reversed into what was left of it -- the brand's box
        # covering 68.3% of the block. The reference shows what that column is
        # for: "Cialis" on one line with "10 mg" in the bar BESIDE it.
        #
        # Corrected from the BUILT row rather than by narrowing `brand_right`
        # up front, and the difference is a regression this already caused once:
        # `brand_right` is also the clearing search's right limit, and narrowing
        # it took away the +0.184 indent that lifts `59-min`'s brand out of its
        # green swoosh -- 0.0% hidden back to 31.0%. Measured over the group, a
        # built brand overlaps its carton's block on exactly one carton, and the
        # two others whose rows touch a block at all touch 0.9% and 1.2% of it.
        if dosage_block is not None and _overlaps_block(t, dosage_block):
            _fit_width(t, max(dosage_block["x0"]
                              - BRAND_BADGE_GAP_FRAC * face_w - left,
                              0.1 * face_w))
            _fit_above(t, floor)
        rows.append(t)
        grid_rows.append((t, brand_right))

    ingredient = (label_content.get("active_ingredient_display") or "").strip()
    if ingredient and "active_ingredient_display" in measured:
        rows.append(_place_measured_row(
            "label_ingredient", ingredient, regular,
            measured["active_ingredient_display"],
            _ink_for(measured["active_ingredient_display"]),
            face_w, face_h, left_x, top_z, y))
    elif ingredient:
        t = _add_text("label_ingredient", ingredient, regular,
                      small_print_cap(INGREDIENT_CAP_M), ink,
                      left, v_to_z(INGREDIENT_TOP_FRAC), y)
        _fit_width(t, right - left)
        rows.append(_clear_below(t, measured_spans,
                                 BRAND_INGREDIENT_GAP_FRAC * face_h,
                                 top_z - face_h))
        grid_rows.append((rows[-1], right))

    half_row = max((right - left - BOTTOM_ROW_GUTTER_M * unit_scale) / 2.0,
                   0.1 * face_w)
    # Keep the bottom row clear of the accent stripe by this much of the face.
    floor_z = (stripe_top_z + BOTTOM_ROW_CLEARANCE_FRAC * face_h
               if stripe_top_z is not None else None)

    bottom_row = []
    dosage = (label_content.get("dosage_display") or "").strip()
    if dosage and "dosage_display" in measured:
        # A measured row outranks the block for POSITION. Both describe where the
        # dosage goes and the measurement is of THIS carton, where the block is
        # inferred from shape.
        #
        # The ink still has to follow the surface underneath it. Cialis sets its
        # "10 mg" inside an olive block and both describe the same rectangle, so
        # taking the measured position while keeping the default dark ink prints
        # near-black on dark olive. Where the two overlap, the row reverses out
        # of the block exactly as the block path would have drawn it.
        rows.append(_place_measured_row(
            "label_dosage", dosage, bold, measured["dosage_display"],
            _ink_for(measured["dosage_display"]),
            face_w, face_h, left_x, top_z, y))
    elif (dosage and dosage_block is not None
            and (dosage_block["x1"] - dosage_block["x0"])
            >= DOSAGE_BLOCK_MIN_WIDTH_FRAC * face_w
            and not _block_is_taken(dosage_block, rows, bold,
                                    DOSAGE_BLOCK_CAP_FRAC,
                                    DOSAGE_BLOCK_FILL_FRAC)):
        # Reversed out of the measured colour block, which is where the real
        # carton puts it. Leaving it on the grid below would print the dosage
        # twice over: once in black at the foot of the face, and once as an empty
        # rectangle where the reference reads "10 mg".
        bw = dosage_block["x1"] - dosage_block["x0"]
        bh = dosage_block["z1"] - dosage_block["z0"]
        t = _add_text("label_dosage", dosage, bold,
                      bh * DOSAGE_BLOCK_CAP_FRAC,
                      _reverse_ink(dosage_block["fill"]),
                      0.5 * (dosage_block["x0"] + dosage_block["x1"]),
                      dosage_block["z1"] - 0.5 * (bh - bh * DOSAGE_BLOCK_CAP_FRAC),
                      y, align="CENTER")
        _fit_width(t, bw * DOSAGE_BLOCK_FILL_FRAC)
        rows.append(t)
        grid_rows.append((t, right))
    elif dosage:
        t = _add_text("label_dosage", dosage, bold, small_print_cap(BOTTOM_ROW_CAP_M),
                      ink, left, v_to_z(BOTTOM_ROW_TOP_FRAC), y)
        bottom_row.append(_fit_width(t, half_row))
        grid_rows.append((t, left + half_row))

    count = (label_content.get("unit_count_display") or "").strip()
    if count and "unit_count_display" in measured:
        rows.append(_place_measured_row(
            "label_unit_count", count, regular, measured["unit_count_display"],
            _ink_for(measured["unit_count_display"]),
            face_w, face_h, left_x, top_z, y))
    elif count:
        t = _add_text("label_unit_count", count, regular,
                      small_print_cap(BOTTOM_ROW_CAP_M), ink,
                      right, v_to_z(BOTTOM_ROW_TOP_FRAC), y, align="RIGHT")
        bottom_row.append(_fit_width(t, half_row))
        grid_rows.append((t, right))

    rows.extend(_lift_row(bottom_row, floor_z, measured_spans,
                          BRAND_INGREDIENT_GAP_FRAC * face_h))

    # Ink is settled HERE, from where each row FINALLY stands, and for EVERY row
    # rather than only the measured ones.
    #
    # `_surface_fill` arrived for measured rows, because a measured row lands
    # wherever the reference puts it and on these cartons that is often on the
    # design. A GRID row is just as capable of landing on a field -- it gets
    # there by our own art direction rather than by the reference -- and those
    # rows kept the constant LABEL_INK. Cialis hangs its unit count across the
    # green swoosh and Kamagra hangs its across the teal, so both printed
    # near-black on a dark field: present, correctly placed, and unreadable. The
    # OCR barrier could not read either and said nothing, because its committed
    # fixtures were three contract versions stale and it was reading a carton
    # the renderer had stopped building.
    #
    # AFTER placement, not at creation, because a grid row moves: `_fit_above`
    # shrinks it, `_clear_below` lowers it, and `_lift_row` raises the whole
    # bottom row to clear the accent stripe. Ink chosen from where a row was
    # going to go is ink chosen for the wrong surface the moment one of those
    # fires.
    #
    # GRID rows only. A measured row keeps the ink `_ink_for` gave it from the
    # MEASURED box, and the difference is not academic: `_place_measured_row`
    # sets a row against its cap line and `_fit_width` may condense it, so the
    # built box's centre is not the measured box's centre, and on `64-min` the
    # two fall on different surfaces. Judging every row by the built centre
    # flipped that dosage's ink and cost the OCR barrier a field that had been
    # reading. The measured box is what the reference measured; that is the one
    # to honour where there is a measurement at all.
    substrate = (design or {}).get("substrate")
    for t, right_limit in grid_rows:
        # The vertical fallback needs a floor, and it has two: the row beneath
        # this one, and the face. Passed from here because only the caller knows
        # the whole row set -- the same reason `_row_left_limit` is computed here.
        gap = BRAND_INGREDIENT_GAP_FRAC * face_h
        floor = _row_floor_z(t, rows, gap)
        face_bottom = top_z - face_h
        _clear_of_design(t, design, substrate, left_x, top_z, face_w, face_h,
                         right_limit,
                         _row_left_limit(t, rows, left_x, face_w),
                         face_bottom if floor is None else max(floor, face_bottom),
                         _row_ceiling_z(t, rows, gap))
        # The band is derived from the row's own location, NOT from
        # `_bounds_in_frame`, and the difference is the whole bug this
        # replaced. Blender does not refresh an object's evaluated bounds
        # when `location` is assigned, so after `_clear_of_design` moves a
        # row the bounds still describe where it USED to be. While only
        # LEFT-set rows were cleared the two agreed to about 0.007 of the
        # face and nothing showed; a right-set row travels far enough to
        # matter, and on `230-min` the ink was chosen for u 0.743-0.947
        # while the row was drawn at u 0.471-0.675 -- a band that is 70.9%
        # dark against one that is not, so "30 Pills" came out WHITE on a
        # white board, 100% of it invisible. `272-min` the same.
        #
        # Same quantities `_clear_of_design` uses, so the mover and the
        # inker cannot disagree about where the row is.
        width = _text_dimensions(t).x
        lo = t.location.x if t.data.align_x == "LEFT" else t.location.x - width
        cap_top = t.location.z - _cap_drop(t.data.font) * t.data.size
        cap_bot = cap_top - _cap_ratio(t.data.font) * t.data.size
        fill = _band_fill(
            design, substrate,
            (lo - left_x) / face_w, (lo + width - left_x) / face_w,
            (top_z - cap_top) / face_h, (top_z - cap_bot) / face_h)
        if fill:
            t.data.materials.clear()
            t.data.materials.append(_reverse_ink(fill))

    for t in rows:
        t.parent = box
        t.matrix_parent_inverse = box.matrix_world.inverted()
    # Counts LINES, not strings: a wrapped brand name is two. Cheap enough to
    # print on every render and it is the one number that says at a glance
    # whether the face came out labelled.
    lines = sum(t.data.body.count(chr(10)) + 1 for t in rows)
    print(f"[render_driver] label: {lines} text object(s)")
    return rows


#: How finely `_one_ink_serves` samples a row's cap band.
#:
#: It was 24x6, and the number mattered in a way a sampling density usually
#: does not: this function decides when `_clear_of_design` STOPS moving a row,
#: while tests/test_blender_carton.py judges the result on its own 30x10 grid.
#: A mover coarser than its judge stops one step short and the row is reported
#: unreadable at a position it was just told was clear -- measured on `59-min`,
#: where 24x6 saw 0 dark samples in the band and 30x10 saw 1, and 120x40 saw 10.
#: Finer than any judge, so the row is cleared for real and not to a resolution.
_INK_SAMPLES_U = 120
_INK_SAMPLES_V = 40


_DARK_CACHE = {}


def _is_dark(fill):
    """Does `_reverse_ink` treat this colour as dark? Memoised.

    A design carries a handful of distinct colours and the samplers ask about
    them tens of thousands of times per carton, re-parsing the same six hex
    digits every time. Same bar as `_reverse_ink`, in sRGB, so the three cannot
    drift apart on what "dark" means.
    """
    got = _DARK_CACHE.get(fill)
    if got is None:
        h = (fill or "#FFFFFF").lstrip("#")
        r, g, b = (int(h[k:k + 2], 16) / 255.0 for k in (0, 2, 4))
        got = 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.5
        _DARK_CACHE[fill] = got
    return got


#: Stride for the cheap rejecting pass. 120 and 40 are both divisible by it,
#: so the coarse grid is a strict SUBSET of the fine one -- which is the whole
#: reason it is safe to skip the fine pass when the coarse one rejects: every
#: sample the coarse pass saw is a sample the fine pass would also take, so a
#: coarse witness of two colours IS a fine witness of two colours. A coarse
#: grid that merely resembled the fine one would not license this.
_INK_COARSE_STRIDE = 5

#: Step of the clearing search, as a fraction of the face. Unchanged -- it is
#: the step the horizontal pass has always used.
CLEAR_STEP_FRAC = 0.005




def _one_ink_serves(design, substrate, u0, u1, v0, v1, stride=1):
    """True when every surface under this band sits on one side of the ink bar.

    Not "one surface": `135-min` sets its dosage across `#032F5D` and `#AD3A9D`
    and white reads on both, so crossing that boundary costs nothing. What
    cannot be served is a band carrying both a light and a dark surface.

    *stride* samples every nth point of the fine grid rather than a grid of its
    own. `_clear_of_design` asks the strided pass first because most positions
    it tries are rejected, and a rejection needs one witness of each colour, not
    4800 points. An acceptance is always confirmed at stride 1.

    MARKS COUNT HERE, AND A NOTE THAT USED TO STAND IN THIS PLACE SAID THE
    OPPOSITE ON A MISREAD MEASUREMENT. This is the predicate `_clear_of_design`
    accepts a position by, so what it sees MOVES ROWS -- which is why letting it
    see a mark was reverted once and why the revert was wrong.

    The revert was justified as "eight OCR rows lost against three gained, and
    `221_Inderal`'s legible white 40mg walked off its band". That figure was the
    cost of DRAWING the marks, not of moving the rows: the run with the mover
    blind lost NINE against the same three, so the mover was worth exactly one
    row and cost none. `221_Inderal` never moved at all -- measured on the scene
    dump, none of its rows so much as touches one of its marks.

    Retaken. Across all 28 design cartons plus a generic one, a seeing mover
    relocates exactly THREE rows and no others:

      `157-min` unit count  du +0.170 left, off the Roche hexagon -- the row
                            Tesseract could not read, and now reads
      `230-min` dosage      du +0.070, "15mg" out of the Neptune mark's frame
      `152-min` dosage      du +0.085, "150mg" off the signature swash

    +1 OCR row, none lost, and the readability guard's straddling set goes 2 to
    ZERO. Two of the three gain nothing a reader can score and are still right:
    looked at, "15mg" had the mark's orange rule through its digits. That one
    also shows what the guard cannot see -- it compares ink and surface
    LIGHTNESS, and an orange mark on a white board passes while its strokes cut
    the glyphs.
    """
    dark = light = False
    for i in range(0, _INK_SAMPLES_U, stride):
        for j in range(0, _INK_SAMPLES_V, stride):
            fill = _surface_fill(
                design, u0 + (u1 - u0) * (i + 0.5) / _INK_SAMPLES_U,
                v0 + (v1 - v0) * (j + 0.5) / _INK_SAMPLES_V) or substrate
            if _is_dark(fill):
                dark = True
            else:
                light = True
            if dark and light:
                return False
    return True


def _band_minority(design, substrate, u0, u1, v0, v1):
    """The smaller of this band's two sides, as a share of it.

    What `_one_ink_serves` answers yes/no, answered as a quantity. Not used to
    DECIDE anything -- a tolerance was tried and the evidence refused it: across
    the group's 81 grid rows, 20 carry a mixed band at home and they run from
    0.250% to 49.729% with no gap anywhere, so there is no size at which one
    stops being a defect. It is here because `PHARMAGEN_CLEAR_DEBUG` prints it,
    and printing it is how two bugs in this search were found.
    """
    dark = 0
    for i in range(_INK_SAMPLES_U):
        for j in range(_INK_SAMPLES_V):
            # Whatever `_one_ink_serves` sees, since this is that function
            # answered as a quantity rather than yes/no. A diagnostic measuring
            # a different surface set from the decision it reports on would be
            # worse than no diagnostic.
            fill = _surface_fill(
                design, u0 + (u1 - u0) * (i + 0.5) / _INK_SAMPLES_U,
                v0 + (v1 - v0) * (j + 0.5) / _INK_SAMPLES_V) or substrate
            if _is_dark(fill):
                dark += 1
    share = dark / float(_INK_SAMPLES_U * _INK_SAMPLES_V)
    return min(share, 1.0 - share)


def _band_fill(design, substrate, u0, u1, v0, v1):
    """The surface most of this band stands on, as a colour to reverse against.

    The ink and the placement must judge the SAME region or they undo each
    other. `_clear_of_design` clears a row over its CAP BAND; the ink used to be
    taken from the centre of the row's BOUNDING BOX, which carries descender
    space the glyphs never reach. On `59-min` that split them: the mover put the
    unit count on a band that is 0 of 4800 samples dark -- clean board -- and
    the box centre still sat on the swoosh below it, so the row was inked WHITE
    and printed invisibly on cream at a position chosen to make it readable.

    By majority rather than by a point, because a row that could not be cleared
    still has to pick the ink that serves most of itself. On a cleared row the
    majority is unanimous and this is just the band's own colour.
    """
    tally = {}
    for i in range(_INK_SAMPLES_U):
        for j in range(_INK_SAMPLES_V):
            # Marks count. This runs after `_clear_of_design` has returned, so
            # the row is already placed; and the majority rule means a mark the
            # row merely clips does not flip an ink that serves the rest of it.
            fill = _surface_fill(
                design, u0 + (u1 - u0) * (i + 0.5) / _INK_SAMPLES_U,
                v0 + (v1 - v0) * (j + 0.5) / _INK_SAMPLES_V) or substrate
            tally_key = (_is_dark(fill), fill)
            tally[tally_key] = tally.get(tally_key, 0) + 1
    if not tally:
        return None
    side = {}
    for (dark, _f), n in tally.items():
        side[dark] = side.get(dark, 0) + n
    win = max(side, key=side.get)
    return max((k for k in tally if k[0] == win), key=lambda k: tally[k])[1]


def _row_left_limit(t, rows, left_x, face_w):
    """How far left a right-set row may travel before it reaches a neighbour.

    The bottom row is two strings sharing one baseline -- dosage left, unit
    count right -- so clearing the unit count leftwards has to stop at the
    dosage rather than print through it. Rows that do not overlap this one's
    CAP BAND vertically are not in the way whatever their x, which is the same
    reason `_clear_of_design` judges the cap band and not the bounding box.
    """
    cap_top = t.location.z - _cap_drop(t.data.font) * t.data.size
    cap_bot = cap_top - _cap_ratio(t.data.font) * t.data.size
    gap = 0.02 * face_w
    limit = left_x
    for o in rows:
        if o is t:
            continue
        o_top = o.location.z - _cap_drop(o.data.font) * o.data.size
        o_bot = o_top - _cap_ratio(o.data.font) * o.data.size
        if o_bot > cap_top or o_top < cap_bot:
            continue                      # nothing shared vertically
        o_w = _text_dimensions(o).x
        align = o.data.align_x
        o_right = o.location.x + (o_w if align == "LEFT" else
                                  0.5 * o_w if align == "CENTER" else 0.0)
        limit = max(limit, o_right + gap)
    return limit


def _clear_of_design(t, design, substrate, left_x, top_z, face_w, face_h,
                     right_limit, left_limit=None, floor_z=None,
                     ceiling_z=None):
    """Indent a LEFT-set grid row until one ink can serve all of its capitals.

    A measured row never needs this: the reference puts a row where the real
    carton puts it, which is on one surface. The grid is design-blind, and on
    `59-min` it starts the brand at LABEL_LEFT_FRAC -- inside the green swoosh.
    "Cia" printed dark on dark green and Tesseract returned "lis", off our
    render AND off the reference photograph, the same three letters.

    Indenting is not an invention: the real Cialis carton starts its wordmark
    clear of the swoosh at u 0.22 against our 0.076, and the measured shift that
    clears it here is +0.184.

    Judged over the CAP BAND, because a row's bounding box carries ascender and
    descender space that reaches where no glyph does -- by the box, `135-min`
    and `344-min` look affected and stop looking so as the sampling gets finer;
    over the cap band both are clean at every density.

    Bounded by the row's own limit rather than by a chosen distance: a row that
    cannot be cleared before it would overrun stays where the grid put it and
    keeps whatever ink `_surface_fill` gives it.

    A RIGHT-set row is cleared the same way, toward the LEFT. This used to bail
    on any row that was not LEFT-set, and a note here recorded that the two
    bottom-right unit counts could not be cleared by placement at all -- that
    no offset in either axis came within a third of the face. Scanning the face
    says otherwise: `59-min` reaches a fully readable position 15.5% of the
    face width to the left and `64-min` 24.0%, both along the row's own
    baseline, so the bottom row still shares one.

    Ink could never have fixed those: `59-min`'s cap band is 47.7% dark and
    52.3% light, and the hidden shares of the two inks sum to 100%, so the best
    single ink still hides 47.7% of the string. Placement is the lever.

    AND WHEN THE FIELD SPANS THE WIDTH, the lever is the other axis. Indenting
    assumes there is somewhere along the row's own baseline to go, which is true
    of a swoosh and false of a rule. `344-min` is the case: Phase B put its red
    top rule into the spec -- it is printed, `v 0.047-0.202` -- and the rule runs
    `u 0.016-0.926`, so no x clears it. The brand's cap band lands `v
    0.133-0.253`, 34.2% of it on the rule and 65.8% on the board, and
    `_band_fill`'s majority therefore inks it DARK: a third of "Modafinil
    Generic" printed dark on dark red, present and unreadable.

    AND UP AS WELL AS DOWN, which it did not until contract 1.8's fixture
    rebuild found what the missing direction had been costing. The fallback
    dropped a row and never raised one, and the group still carried three rows
    printed in an ink their own surface hides -- every one of them clearable
    only upward:

      `357-min` ingredient  10.0% hidden   cleared by a rise of 0.015
      `357-min` dosage      28.7% hidden   cleared by a rise of 0.115
      `149-min` unit count  13.7% hidden   cleared by a rise of 0.235

    The ingredient shows why the horizontal pass could not save them: it runs
    88% of the face wide, so no x offset fits between the margins at all, and
    every offset that serves lies UP the face -- 0.015 to 0.235 of it -- where
    nothing ever looked. Its own field is BELOW the row, and a row escapes a
    field by moving away from it.

    Each direction is exhausted before the next is tried and the new one comes
    last, so a carton the old search cleared is cleared by the identical move.

    A JOINT search over both axes was built and measured and is not here. A
    diagonal boundary is genuinely cheaper to cross in two axes -- `357-min`'s
    dosage clears at (dx +0.090, dz -0.005), against 0.115 straight up -- but
    with the axes tried first it never fires on any carton in the group, and
    unreachable code that decides where type goes is worse than a move 0.020
    larger than it had to be.

    The row goes back to where the grid put it if nothing serves.

    Bounded by the row beneath it -- `_row_floor_z` -- because lowering a row
    onto its neighbour is the failure `_clear_below` exists to prevent, by the
    row above it -- `_row_ceiling_z` -- for the same reason in the other
    direction, and by the face itself.

    One caution, measured: a candidate found on a coarse grid may not survive
    the fine one. `357-min`'s dosage has a position at dx +0.160 that serves at
    30x10 and does not at 120x40, where 0.29% of the band is still the other
    colour. `serves()` confirms every acceptance at full density for that
    reason.
    """
    if not design or t.data.align_x not in ("LEFT", "RIGHT"):
        return t
    rightward = t.data.align_x == "LEFT"
    if left_limit is None:
        left_limit = left_x
    width = _text_dimensions(t).x
    drop = _cap_drop(t.data.font) * t.data.size
    cap_h = _cap_ratio(t.data.font) * t.data.size
    home_x, home_z = t.location.x, t.location.z

    def _band(x, z):
        # location.x is the row's LEFT edge when it is left-set and its
        # RIGHT edge when it is right-set; the band is the same either way.
        lo = x if rightward else x - width
        hi = x + width if rightward else x
        cap_top = z - drop
        return ((lo - left_x) / face_w, (hi - left_x) / face_w,
                (top_z - cap_top) / face_h, (top_z - (cap_top - cap_h)) / face_h)

    def serves(x, z):
        band = _band(x, z)
        # Reject cheaply, accept only on the full grid.
        return (_one_ink_serves(design, substrate, *band,
                               stride=_INK_COARSE_STRIDE)
                and _one_ink_serves(design, substrate, *band))

    sx, sz = CLEAR_STEP_FRAC * face_w, CLEAR_STEP_FRAC * face_h

    # The two limits are NOT symmetric and must not be treated as one window.
    # `right_limit` bounds a LEFT-set row's travel toward its neighbour;
    # `_row_left_limit` answers the same question for a RIGHT-set row and
    # returns the neighbour on the row's OTHER side, so applying it to a
    # left-set row rejects even the position the grid chose -- measured, it
    # rejected every candidate for `357-min`'s dosage and the row never moved.
    # A row may INDENT away from its margin and never past it. The grid sets
    # rows between u 0.07 and u 0.95 and those margins are art direction, so
    # the far side of a row's travel is its own home: measured, letting a
    # LEFT-set row travel left took `60-min`'s brand to u 0.026 -- outside the
    # label grid altogether -- on a carton that was already readable. The
    # horizontal range is therefore exactly the one this function always had.
    lo_bound = left_limit if not rightward else home_x
    hi_bound = right_limit if rightward else home_x
    top_bound = top_z if ceiling_z is None else min(top_z, ceiling_z)

    def in_bounds(xi, zj):
        # Each axis is bounded only when it MOVES. The old search checked the
        # x limit in its x pass and the floor in its z pass, and never one in
        # the other's; checking both on every candidate rejects a pure-z move
        # for a row that is already wider than its own limit -- and the brand
        # is, on every carton where it fills the face. Measured, that threw
        # away the 0.100 drop the old code gave `357-min`'s brand and left it
        # printing 22.4% of its cap band in an ink that surface hides.
        x, z = home_x + xi * sx, home_z + zj * sz
        if xi:
            lo = x if rightward else x - width
            hi = x + width if rightward else x
            if lo < lo_bound or hi > hi_bound:
                return False
        if zj:
            cap_top = z - drop
            if cap_top > top_bound:
                return False
            if floor_z is not None and cap_top - cap_h < floor_z:
                return False
        return True

    def take(xi, zj):
        if (xi or zj) and not in_bounds(xi, zj):
            # HOME is always admissible. The old search asked `serves` about it
            # before it asked about any bound, and a row can start outside one:
            # `357-min`'s brand fills 88% of the face and reaches its own right
            # limit, so testing the bound first rejected the position the grid
            # chose and sent a readable row up the carton.
            return False
        if not serves(home_x + xi * sx, home_z + zj * sz):
            return False
        t.location.x = home_x + xi * sx
        t.location.z = home_z + zj * sz
        return True

    # Each direction is EXHAUSTED before the next is tried, and the newly
    # opened one comes last, so a carton the old search cleared is cleared by
    # the identical move. `64-min`'s unit count travels 0.240 of the face along
    # its baseline and `59-min`'s 0.155; a travel cap fitted to the three rows
    # THIS change repairs would have thrown both away.
    # Each direction is EXHAUSTED before the new one is tried, not alternated
    # with it. Alternating takes the nearest serving position, which sounds
    # better and is not: it moved `158-min` and `221-min`, two cartons the old
    # search had already cleared, onto different positions that are no more
    # readable. The old direction goes first and goes all the way, so a carton
    # that used to be cleared is cleared by the identical move.
    reach = max(1, int(1.0 / CLEAR_STEP_FRAC))
    ahead = 1 if rightward else -1              # the way this row used to look
    if os.environ.get("PHARMAGEN_CLEAR_DEBUG"):
        print(f"[clear] {t.name} home minority "
              f"{_band_minority(design, substrate, *_band(home_x, home_z)):.5f}",
              flush=True)
    if take(0, 0):
        return t
    for xi in range(1, reach + 1):
        if take(ahead * xi, 0):
            return t
    for zj in range(1, reach + 1):
        if take(0, -zj):                        # down, as it always was
            return t
    for zj in range(1, reach + 1):
        if take(0, zj):                         # up, which is new
            return t

    t.location.x, t.location.z = home_x, home_z
    return t


def _row_span(o):
    """(left, right, cap_bottom, cap_top) of a row, from its LOCATION.

    Not from `_z_span`/`_x_span`, and the difference is a trap this file already
    records once: Blender does not refresh an object's evaluated bounds when
    `location` is assigned, so a row `_clear_of_design` has already moved still
    reports where it USED to be. `_row_left_limit` computes from the location and
    the font's own metrics for exactly that reason; anything that has to be
    correct DURING the clearing pass has to do the same.
    """
    w = _text_dimensions(o).x
    align = o.data.align_x
    right = o.location.x + (w if align == "LEFT" else
                            0.5 * w if align == "CENTER" else 0.0)
    top = o.location.z - _cap_drop(o.data.font) * o.data.size
    return right - w, right, top - _cap_ratio(o.data.font) * o.data.size, top


def _row_floor_z(t, rows, gap):
    """How far this row may descend before it reaches the row beneath it.

    The mirror of `_row_left_limit`, and it shares that function's one real
    rule: a row that does not overlap this one HORIZONTALLY is not in the way
    whatever its height. `135-min` is why -- its measured dosage block sits at
    the right of the same band the brand occupies at the left, they share their
    whole height and touch nowhere, and dropping a row for an obstacle it never
    meets is a wrong layout too, just a quieter one.
    """
    x_lo, x_hi, cap_bot, _cap_top = _row_span(t)
    floor = None
    for o in rows:
        if o is t:
            continue
        o_x_lo, o_x_hi, _o_bot, o_top = _row_span(o)
        if x_hi <= o_x_lo or x_lo >= o_x_hi:
            continue                      # nothing shared horizontally
        if o_top >= cap_bot:
            continue                      # not beneath this row
        floor = o_top + gap if floor is None else max(floor, o_top + gap)
    return floor


def _row_ceiling_z(t, rows, gap):
    """How far this row may RISE before it reaches the row above it.

    The mirror of `_row_floor_z`, added because the clearing search now travels
    upward as well as down, and for the same reason that one exists: a row that
    does not overlap this one horizontally is not in the way whatever its
    height.

    Upward was missing outright until contract 1.8's fixture rebuild found
    `357-min` printing "Amphetamine / Dextroamphetamine Salts" in white with
    10.0% of its cap band on the white swoosh -- and the only offsets that clear
    it lie UP the face, from 0.015 to 0.235 of it, because the field it has to
    escape is below the row rather than above it.
    """
    x_lo, x_hi, _cap_bot, cap_top = _row_span(t)
    ceiling = None
    for o in rows:
        if o is t:
            continue
        o_x_lo, o_x_hi, o_bot, _o_top = _row_span(o)
        if x_hi <= o_x_lo or x_lo >= o_x_hi:
            continue                      # nothing shared horizontally
        if o_bot <= cap_top:
            continue                      # not above this row
        ceiling = o_bot - gap if ceiling is None else min(ceiling, o_bot - gap)
    return ceiling


def _add_panel_text(name, body, font, cap_h, ink_mat, u, v, x, align="LEFT"):
    """A text row on the -X side panel.

    A text object is created in the XY plane facing +Z. Rotating +90 deg about X
    stands it upright facing -Y (the front face); a further -90 about Z swings it
    round to face -X, which is the side panel. The sign matters: +90 about Z
    would leave the normal at +X, pointing INTO the carton, and the row would
    render mirrored and backfacing. Reading then runs along -Y, so rows are
    anchored at the panel's back edge and read toward the front.
    """
    bpy.ops.object.text_add(location=(x, u, v))
    t = bpy.context.active_object
    t.name = name
    t.data.body = body
    t.data.font = font
    t.data.size = cap_h / _cap_ratio(font)
    t.data.align_x = align
    t.data.align_y = "TOP"
    t.rotation_euler = (math.radians(90.0), 0.0, math.radians(-90.0))
    t.data.materials.append(ink_mat)
    return t


def build_side_panel(box, manifest: dict, panel_w, panel_h, left_x, back_y,
                     top_z, half_thick, unit_scale):
    """The visible side panel: barcode, empty LOT/EXP fields, and a data block.

    panel_w is the carton DEPTH and panel_h its height. Everything is placed in
    the panel's own coordinates and every string comes from the manifest.
    """
    carton = manifest.get("carton") or {}
    # `product_code`, NEVER `sku_id`. The catalogue's key is SKU.csv's `picture`
    # column -- the source image's filename -- so printing it put `.jpg` on all
    # 391 cartons, under the barcode and inside the Code 128 as a scannable
    # product code. Contract 1.6 separates the two; see src/utils.product_code.
    #
    # SystemExit rather than a fallback to sku_id: Blender exits 0 after an
    # ordinary uncaught exception, and a silent fallback here is precisely how
    # the filename got onto the carton in the first place.
    code = str(manifest.get("product_code") or "")
    if not code:
        raise SystemExit(
            "manifest carries no product_code (contract 1.6). Regenerate it "
            "with `python main.py --passports-only`; this driver will not fall "
            "back to sku_id, which is a filename.")
    built = []

    ink = make_material("panel_ink", LABEL_INK, roughness=MATTE_ROUGHNESS)
    regular, bold = _load_font(FONT_REGULAR), _load_font(FONT_BOLD)
    x = left_x - half_thick                      # just proud of the -X face
    margin = PANEL_MARGIN_FRAC * panel_w
    usable_w = panel_w - 2 * margin
    # Rows read along -Y, so they start at the BACK edge and run to the front.
    u_start = back_y + panel_w - margin
    u_front = back_y + margin

    def v_at(frac):
        return top_z - frac * panel_h

    # ── barcode ──────────────────────────────────────────────────────────────
    widths = encode_code128b(code)
    total_modules = sum(widths) + 20              # 10 modules of quiet zone each end
    span = BARCODE_LEN_FRAC * panel_h
    module = span / total_modules
    bar_len = BARCODE_BAR_FRAC * usable_w

    # An 11-character Code 128 is a long symbol, and these are small cartons.
    # Measured across the catalogue the module lands between 0.08mm and 0.40mm,
    # so on the shorter panels it falls under the ~0.19mm a scanner needs and
    # under the ~2 pixels per module a 2048px render can resolve — the bars merge
    # into a grey block. Say so rather than shipping a code that only looks like
    # one. This is also the argument FOR the DataMatrix the carton data already
    # asks for in `features`: a 2D symbol carries the same payload in a fraction
    # of the area, which is exactly why real small-format pharma packs use one.
    module_mm = (module / unit_scale) * 1000.0 if unit_scale else 0.0
    if module_mm < BARCODE_MIN_MODULE_M * 1000.0:
        print(f"[render_driver] WARNING: barcode module is {module_mm:.3f}mm on a "
              f"{panel_h / unit_scale * 1000:.0f}mm panel, below the ~"
              f"{BARCODE_MIN_MODULE_M * 1000:.2f}mm a scanner needs; the symbol is "
              f"correct but will not resolve at this size", file=sys.stderr)

    v = v_at(BARCODE_TOP_FRAC) - 10 * module      # leading quiet zone
    for i, w in enumerate(widths):
        run = w * module
        if i % 2 == 0:                            # even index = bar
            bpy.ops.mesh.primitive_cube_add(
                size=1.0, location=(x, u_front + bar_len / 2, v - run / 2))
            bar = bpy.context.active_object
            bar.name = f"panel_barcode_{i:03d}"
            bar.scale = (half_thick * 2, bar_len, run)
            bpy.ops.object.transform_apply(scale=True)
            bar.data.materials.append(ink)
            built.append(bar)
        v -= run

    built.append(_add_panel_text(
        "panel_barcode_hri", code, regular,
        min(BARCODE_HRI_CAP_M * unit_scale, 0.30 * usable_w), ink,
        u_start, v - 0.4 * module * 20, x))
    _fit_width(built[-1], usable_w)

    # ── LOT / EXP, labels only ───────────────────────────────────────────────
    # No values, deliberately. There is no lot or expiry data anywhere in this
    # project, and a real carton does not carry one either: it is inkjetted at
    # packing time onto exactly this blank rule.
    cap = min(FIELD_CAP_M * unit_scale, 0.22 * usable_w)
    for n, (field, frac) in enumerate((("LOT", 0.0), ("EXP", 0.12))):
        t = _add_panel_text(f"panel_field_{field.lower()}", field, bold, cap, ink,
                            u_start, v_at(FIELD_TOP_FRAC + frac), x)
        _fit_width(t, 0.30 * usable_w)
        built.append(t)
        rule_len = FIELD_RULE_FRAC * usable_w
        rule_v = v_at(FIELD_TOP_FRAC + frac) - cap * 1.15
        bpy.ops.mesh.primitive_cube_add(
            size=1.0, location=(x, u_front + rule_len / 2, rule_v))
        rule = bpy.context.active_object
        rule.name = f"panel_rule_{field.lower()}"
        rule.scale = (half_thick * 2, rule_len, module * 0.8)
        bpy.ops.object.transform_apply(scale=True)
        rule.data.materials.append(ink)
        built.append(rule)

    # ── data block: manifest strings only ────────────────────────────────────
    # Anchored under whatever the LOT/EXP block actually came out as, not at a
    # fixed v. The fields are sized in absolute millimetres, so on a short panel
    # they occupy a larger share of it and a constant would collide.
    from mathutils import Vector
    dg = bpy.context.evaluated_depsgraph_get()
    lowest = min((o.matrix_world @ Vector(cnr)).z
                 for o in built for cnr in o.evaluated_get(dg).bound_box)
    block_top = min(v_at(DATA_BLOCK_TOP_FRAC),
                    lowest - DATA_BLOCK_GAP_FRAC * panel_h)
    # The printed size is carton.passport_dimensions, NEVER carton.width_mm and
    # its siblings. Since contract 1.3 those are art-directed scene geometry --
    # the shape solved to match the template's reference proportion -- and
    # printing them would put measurements on pharmaceutical packaging that no
    # carton has. This project already refuses to print a plausible LOT or EXP
    # for that reason; a plausible size is the same act in numbers.
    printed = carton["passport_dimensions"]
    lines = [str(carton.get("material") or ""),
             f"{printed['width_mm']:.0f}x{printed['height_mm']:.0f}"
             f"x{printed['depth_mm']:.0f}mm",
             str(manifest.get("packaging_geometry") or "")]
    features = carton.get("features") or []
    if features:
        lines.append(" / ".join(features))
    lines = [ln for ln in lines if ln]
    if lines:
        cap = min(DATA_BLOCK_CAP_M * unit_scale, 0.14 * usable_w)
        t = _add_panel_text("panel_data_block", "\n".join(lines), regular, cap,
                            ink, u_start, block_top, x)
        _fit_width(t, usable_w)
        # And shrink to the panel's bottom edge if it still runs off. The block
        # is anchored under the LOT/EXP fields and sized in absolute millimetres,
        # so on the catalogue's smallest panel — a 25x35mm T3 — three lines reach
        # past the bottom of the carton. Found by the 391-SKU sweep, not by the
        # curated templates: exactly one SKU in 391.
        _fit_above(t, (top_z - panel_h) + PANEL_BOTTOM_MARGIN_FRAC * panel_h)
        built.append(t)

    for obj in built:
        obj.parent = box
        obj.matrix_parent_inverse = box.matrix_world.inverted()
    return built


def build_design_fields(box, design: dict, face_w, face_h, depth, left_x,
                        front_y, top_z, half_thick, finish=None):
    """Draw a measured design onto the front face.

    Contract 1.4 carries the fields of a REAL carton for the eleven SKU with
    reference photography: an outline per part in face-normalised coordinates,
    u across and v DOWN, both 0..1 of the printed face.

    Filled 2D curves rather than meshes, because the outlines are deeply concave
    -- the Cialis white swoosh is a crescent -- and an n-gon face through those
    vertices renders as a torn fan. A curve with fill_mode BOTH is tessellated
    properly whatever the outline does, and carries the arcs the sources actually
    have without a triangulation step of our own.

    Extruded by the same half-thickness as the stripe it replaces, so printed
    fields read as ink on board rather than as tiles floating above it, and
    cannot z-fight with the face.

    CONTRACT 1.7: fields are separated in DEPTH by their `z`, so paint order is
    geometry rather than a convention. Every part used to be built at
    `location = (0, front_y, 0)` -- one plane, where nothing is on top of
    anything and Cycles resolves an overlap arbitrarily. The spec's field list
    has always been ordered and `rasterise()` fills it front to back, so the
    target and the render answered the same question differently: on
    `357_Adderall` the teal block was erased outright in the target and z-fought
    in the render.

    The separation is deliberately much smaller than the slab itself -- the whole
    stack spreads over less than half a `half_thick` however many fields there
    are -- so the fields still straddle the face plane and read as ink. It also
    stays clear of the label rows, which sit at `front_y - 2 * half_thick`: the
    frontmost field's surface reaches `front_y - 1.5 * half_thick` at worst.

    CONTRACT 1.8: a part is its outline MINUS its holes, and the holes are more
    cyclic splines of the same curve. The two contracts compose, and had to land
    in this order: a hole is a window onto whatever is BEHIND the part, so it
    shows the right thing only once the fields stand at different depths.
    """
    fields = design.get("fields") or []
    if "marks" not in design:
        # SystemExit for the same reason `z`, `holes` and `fill` are: Blender
        # exits 0 after an ordinary uncaught exception, so a KeyError here would
        # read as a successful render of a carton whose marks were never
        # decided. They are a person's decision, not a default -- see
        # 00_PROJECT_STATE/MARKS_DECISION.md.
        raise SystemExit(
            "[render_driver] the design block carries no `marks`. That is "
            "contract 1.10 and it is required, empty where the owner approved "
            "none; a manifest written before it must be regenerated by Stage 1.")
    marks = design.get("marks") or []
    # Small enough that the stack never reads as tiles, and scaled by the field
    # count so adding fields cannot walk the top one into the label plane. Marks
    # share the budget because they stand in the same stack, in front of every
    # field; with none the denominator is unchanged and so is every render that
    # carries no mark.
    z_step = half_thick / (2.0 * max(1, len(fields) + len(marks)))
    built, blocks, mats = [], [], {}

    def _filled_curve(name, rings, colour, surface, surface_offset):
        """One filled, extruded 2D curve: the outer ring first, holes after.

        Contract 1.8's nesting rule and contract 1.10's marks are the same
        geometry problem, so they are the same code. Blender fills a 2D curve by
        NESTING -- measured on this build, an inner square takes a unit square's
        fill to 0.7500 whichever way it is wound, and the extrude walls the hole
        too. Not separate objects: two objects would each fill, and the hole
        would be painted rather than cut.
        """
        curve = bpy.data.curves.new(name, type="CURVE")
        curve.dimensions = "2D"
        curve.fill_mode = "BOTH"
        curve.extrude = half_thick
        for points in rings:
            if len(points) < 3:
                continue
            spline = curve.splines.new("POLY")
            spline.points.add(len(points) - 1)
            for i, uv in enumerate(points):
                u, v = float(uv[0]), float(uv[1])
                if surface == "front":
                    # This branch is the pre-surface contract byte-for-byte.
                    spline.points[i].co = (
                        left_x + u * face_w, top_z - v * face_h, 0.0, 1.0)
                elif surface == "top":
                    spline.points[i].co = (
                        left_x + u * face_w, front_y + v * depth, 0.0, 1.0)
                elif surface == "left":
                    desired_y = front_y + u * depth
                    desired_z = top_z - v * face_h
                    # +90 around Y maps local (-Z,Y,0) to world (0,Y,Z).
                    spline.points[i].co = (
                        -desired_z, desired_y, 0.0, 1.0)
                else:
                    raise SystemExit(
                        "[render_driver] unsupported design field surface "
                        f"{surface!r}")
            spline.use_cyclic_u = True
        obj = bpy.data.objects.new(name, curve)
        bpy.context.scene.collection.objects.link(obj)
        if surface == "front":
            obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
            obj.location = (0.0, front_y - surface_offset, 0.0)
        elif surface == "top":
            obj.location = (0.0, 0.0, top_z + surface_offset)
        else:  # left
            obj.rotation_euler = (0.0, math.radians(90.0), 0.0)
            obj.location = (left_x - surface_offset, 0.0, 0.0)
        obj["design_surface"] = surface
        # Diagnostic facts, read back by --dump-scene.  They describe the
        # object Blender actually built; they are not manifest state and do not
        # participate in placement.  Keeping the common ink budget beside the
        # actual offset makes a floating mark measurable without duplicating
        # the z-stack arithmetic in QA.
        obj["design_normal_offset_m"] = float(surface_offset)
        obj["design_ink_budget_m"] = float(half_thick / 2.0)
        obj["design_hole_count"] = max(0, len(rings) - 1)
        obj["design_fill"] = colour
        mat = mats.get(colour)
        if mat is None:
            mat = make_carton_material(f"{name}_mat", colour, finish)
            mats[colour] = mat
        obj.data.materials.append(mat)
        obj.parent = box
        obj.matrix_parent_inverse = box.matrix_world.inverted()
        return obj
    for f_i, field in enumerate(fields):
        # Only a guard now: under contract 1.9 the field's fill paints nothing,
        # the part's does. A field with none is malformed, not a field to paint.
        if not field.get("fill"):
            continue
        if "z" not in field:
            # SystemExit, not KeyError: Blender exits 0 after an ordinary
            # uncaught exception, and `blender_renderer` would read the run as a
            # success with the fields built in whatever order the list happened
            # to have.
            raise SystemExit(
                f"[render_driver] design field {field.get('role')!r} carries no "
                f"`z`. That is contract 1.7 and it is required; a manifest "
                f"written before it must be regenerated by Stage 1 rather than "
                f"built in an order this driver invents.")
        surface = field.get("surface", "front")
        if surface not in PROFILE_SURFACES:
            raise SystemExit(
                "[render_driver] unsupported design field surface "
                f"{surface!r}")
        surface_offset = int(field["z"]) * z_step
        for p_i, part in enumerate(field.get("parts") or []):
            outline = part.get("outline") or []
            if len(outline) < 3:
                continue
            if "holes" not in part:
                # SystemExit for the same reason `z` above is: Blender exits 0
                # after an ordinary uncaught exception, so a KeyError here would
                # be read as a successful render of a carton with every hole
                # filled in.
                raise SystemExit(
                    f"[render_driver] design field {field.get('role')!r} part "
                    f"{p_i} carries no `holes`. That is contract 1.8 and it is "
                    f"required, empty where the part has none; a manifest "
                    f"written before it must be regenerated by Stage 1 rather "
                    f"than built as a solid shape this driver assumes.")
            if "fill" not in part:
                raise SystemExit(
                    f"[render_driver] design field {field.get('role')!r} part "
                    f"{p_i} carries no `fill`. That is contract 1.9 and it is "
                    f"required; a field's fill is the median of its whole "
                    f"cluster while a part is one region of it, and a manifest "
                    f"written before 1.9 must be regenerated by Stage 1 rather "
                    f"than painted a colour this driver assumes.")
            # CONTRACT 1.9: the colour is the PART's. Cached per colour rather
            # than made per part, so a field whose parts agree still builds one
            # material -- which is the common case, and what keeps Stage A's
            # plumbing bit-identical to the per-field material it replaced.
            part_fill = part["fill"]
            # CONTRACT 1.8: a part is its outline MINUS its holes, and the holes
            # are more cyclic splines of the SAME curve -- see `_filled_curve`.
            obj = _filled_curve(
                f"design_{field.get('role', f_i)}_{p_i}",
                [outline] + list(part.get("holes") or []),
                part_fill, surface, surface_offset)
            built.append(obj)

            # A `block` is a place to put type: four of the eleven references
            # reverse the dosage out of one. The spec names it -- the driver does
            # not re-derive it from the outline, which would be a second copy of
            # a rule that already lives in scripts/fit_design_spec.py.
            if surface == "front" and part.get("kind") == "block":
                us = [float(pt[0]) for pt in outline]
                vs = [float(pt[1]) for pt in outline]
                blocks.append({
                    "fill": part_fill,
                    "x0": left_x + min(us) * face_w, "x1": left_x + max(us) * face_w,
                    "z0": top_z - max(vs) * face_h, "z1": top_z - min(vs) * face_h,
                })
    # CONTRACT 1.10: the marks the owner approved by name, drawn in front of
    # every field. Each carries the print_truth key that permitted it, so a
    # drawn mark can be put back against the row of MARKS_DECISION.md that
    # allowed it.
    #
    # A mark carries its OWN holes and five of the twenty-two have them. The
    # sentence that used to stand here -- "`holes` is empty on every one of
    # them by construction, each approved region was measured solid" -- was
    # true of the eight HOLE marks and false of the components, and painting
    # them solid covered up to 9.5x the ink they describe. `157_Valium`'s Roche
    # hexagon is an OUTLINE; filled, it invents a logo the pack does not print.
    for m_i, mark in enumerate(marks):
        for required in ("fill", "outline", "z", "key"):
            if required not in mark:
                raise SystemExit(
                    f"[render_driver] design mark {m_i} carries no "
                    f"`{required}`. That is contract 1.10 and it is required; "
                    f"regenerate the manifest from Stage 1 rather than drawing "
                    f"a mark this driver has to guess at.")
        parts = _drawable_mark_parts(mark)
        for p_i, part in enumerate(parts):
            outline = part.get("outline") or []
            if len(outline) < 3:
                continue
            if "fill" not in part:
                raise SystemExit(
                    f"[render_driver] design mark {m_i} part {p_i} "
                    "carries no `fill`; regenerate the manifest from Stage 1.")
            name = f"mark_{mark.get('role', m_i)}_{m_i}"
            if p_i:
                name += f"_part_{p_i - 1}"
            # Every approved mark retains one z slot. Overlays subdivide that
            # slot, never adding a full z_step per path. Legacy base depth is
            # unchanged; even hundreds of overlays stay below the next slot.
            surface_offset = (int(mark["z"]) + p_i / len(parts)) * z_step
            obj = _filled_curve(
                name, [outline] + list(part.get("holes") or []),
                part["fill"], "front", surface_offset)
            obj["design_mark_key"] = mark["key"]
            obj["design_mark_part_index"] = p_i - 1  # -1 identifies the base
            built.append(obj)

    print(f"[render_driver] design: {len(built)} field part(s) from "
          f"{len(design.get('fields') or [])} field(s), "
          f"{len(blocks)} colour block(s), {len(marks)} approved mark(s)")
    # The largest block is the dosage's. Where a carton has more than one filled
    # rectangle the dosage is on the biggest of them in every reference measured.
    blocks.sort(key=lambda b: (b["x1"] - b["x0"]) * (b["z1"] - b["z0"]), reverse=True)
    return built, blocks


def build_reference_aux_text(box, rows, face_w, face_h, depth, left_x,
                             front_y, top_z, half_thick):
    """Build only boundary-validated, reference-only auxiliary text rows."""
    if not rows:
        return []
    fonts = {
        "regular": _load_font(FONT_REGULAR),
        "bold": _load_font(FONT_BOLD),
    }
    ink = make_material("reference_aux_ink", LABEL_INK,
                        roughness=MATTE_ROUGHNESS)
    built = []
    for index, row in enumerate(rows):
        surface = row["surface"]
        if surface not in PROFILE_SURFACES:
            raise SystemExit(
                "[render_driver] unsupported reference_aux_text surface "
                f"{surface!r}")
        u0, v0, u1, v1 = (float(value) for value in row["bbox"])
        align = row["align"]
        font = fonts.get(row["font_role"])
        if font is None:
            raise SystemExit(
                "[render_driver] unsupported reference_aux_text font_role "
                f"{row['font_role']!r}")
        name = f"reference_aux_{index}"
        if surface == "front":
            anchor_x = (left_x + u0 * face_w if align == "LEFT" else
                        left_x + u1 * face_w if align == "RIGHT" else
                        left_x + (u0 + u1) * face_w / 2.0)
            cap_h = (v1 - v0) * face_h * 0.62
            obj = _add_text(
                name, row["text"], font, cap_h, ink, anchor_x,
                top_z - v0 * face_h, front_y - 3.0 * half_thick, align)
            extent_axis = 0
            allowed = (u1 - u0) * face_w
        elif surface == "left":
            # Text reads toward the front (-Y), so LEFT begins at bbox u1.
            anchor_y = (front_y + u1 * depth if align == "LEFT" else
                        front_y + u0 * depth if align == "RIGHT" else
                        front_y + (u0 + u1) * depth / 2.0)
            cap_h = (v1 - v0) * face_h * 0.62
            obj = _add_panel_text(
                name, row["text"], font, cap_h, ink, anchor_y,
                top_z - v0 * face_h, left_x - 3.0 * half_thick, align)
            extent_axis = 1
            allowed = (u1 - u0) * depth
        else:  # top
            anchor_x = (left_x + u0 * face_w if align == "LEFT" else
                        left_x + u1 * face_w if align == "RIGHT" else
                        left_x + (u0 + u1) * face_w / 2.0)
            cap_h = (v1 - v0) * depth * 0.62
            bpy.ops.object.text_add(location=(
                anchor_x, front_y + v1 * depth, top_z + 3.0 * half_thick))
            obj = bpy.context.active_object
            obj.name = name
            obj.data.body = row["text"]
            obj.data.font = font
            obj.data.size = cap_h / _cap_ratio(font)
            obj.data.align_x = align
            obj.data.align_y = "TOP"
            obj.data.materials.append(ink)
            extent_axis = 0
            allowed = (u1 - u0) * face_w
        actual = _text_dimensions(obj)[extent_axis]
        if actual > allowed > 0:
            obj.scale.x *= allowed / actual
        obj["reference_aux_surface"] = surface
        obj.parent = box
        obj.matrix_parent_inverse = box.matrix_world.inverted()
        built.append(obj)
    return built














def build_box(dims_m, palette: dict, label_content: dict = None,
              manifest: dict = None):
    """The printed carton — i.e. the SECONDARY packaging, which is what a
    packshot shows — sized in metres, with an accent stripe band welded to the
    bottom of the front face (Row-6 rule, see 06_docs/DESIGN_RATIONALE.md §2) and a
    square brand badge in its top-right corner.

    Not to be confused with the primary package (the blister, bottle or syringe
    inside): that is a smaller object on different axes, and passing its
    dimensions here produces an undersized, sometimes misoriented box.

    SURFACE COLOUR MANDATE (reference_analysis.md §5): the body is WHITE for
    every SKU, and brand colour appears in exactly two places, never more — the
    bottom stripe in palette.ACCENT and the top-right badge in palette.PRIMARY.
    A body tinted with primary is a mismatch, not a brand cue.
    """
    w, h, d = dims_m
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, h / 2))
    box = bpy.context.active_object
    box.name = "carton"
    # size=1.0 is a UNIT cube spanning -0.5..0.5, so its edge length is 1 and the
    # scale factor IS the finished edge length in metres. Scaling by the HALF
    # extents (w/2, d/2, h/2) — which is what Blender's default size=2.0 cube
    # would want — is the trap that built every carton at half its nominal
    # millimetres. Scene units are real metres.
    box.scale = (w, d, h)
    bpy.ops.object.transform_apply(scale=True)

    # The board is white for every SKU EXCEPT the eleven built from a measured
    # design, where it is whatever the real carton's board is. Two of those
    # eleven have a coloured board -- Kamagra's teal, Lexotanil's lime -- so
    # "white always" is not a rule those cartons follow, and it fails inside the
    # sample rather than at its edge.
    design = (manifest or {}).get("design")
    profile = (design or {}).get("carton_profile")
    finish = None
    if profile:
        source_finish = profile["surface_finish"]
        micro = dict(source_finish["micro_bump"])
        base = min(w, h, d)
        finish = {
            "roughness": float(source_finish["roughness"]),
            "micro_bump": micro,
            "_coordinate_scale": 1.0 / base,
            "_distance_m": base * float(micro["distance_frac"]),
        }
    body_hex = (design or {}).get("substrate") or "#FFFFFF"
    body_mat = make_carton_material("carton_body", body_hex, finish)
    box.data.materials.append(body_mat)

    # Measure the mesh that was actually built instead of assuming it spans
    # (w, h, d). It does not: primitive_cube_add(size=1.0) is a UNIT cube, so
    # scaling it by (w/2, d/2, h/2) leaves edge lengths of w/2, d/2, h/2 — the
    # carton mesh is half its nominal millimetres. Camera framing is calibrated
    # against that (see SPHERE_FILL), so the size is left alone here, but
    # anything placed ON the carton has to come off these measured extents.
    # Deriving the stripe from (w, h, d) instead is what detached it: it was
    # pinned to y = -d/2 while the real front face is at -d/4, leaving it
    # floating a quarter-depth clear of the box and swinging visibly wide of the
    # silhouette once the carton was rotated for the packshot.
    xs = [c[0] for c in box.bound_box]
    ys = [c[1] for c in box.bound_box]
    zs = [c[2] for c in box.bound_box]
    face_w, face_h = max(xs) - min(xs), max(zs) - min(zs)
    front_y, bottom_z = min(ys), min(zs)
    right_x, top_z = max(xs), max(zs)
    depth = max(ys) - min(ys)
    unit_scale = face_h / h if h else 1.0   # scene units per real metre
    # Thin slab straddling the face plane, so printed elements read as ink rather
    # than as an applied tile and cannot z-fight with the surface they sit on.
    # Shared by the stripe and the badge, hence hoisted out of either branch.
    half_thick = depth * 0.002

    full_surface_materials = build_full_surface_materials(design, finish)
    build_visible_carton_details(
        box, profile, face_w, face_h, depth,
        {"min": [min(xs), min(ys), min(zs)],
         "max": [max(xs), max(ys), max(zs)]},
        full_surface_materials,
    )

    # The stripe and badge ARE the generic art direction: one accent band and one
    # primary badge, fitted to nine AI reference renders. Where a real carton has
    # been measured they are not decoration to add on top, they are a different
    # design being drawn over the right one.
    stripe_top_z = None
    accent_hex = None if design else palette.get("accent")
    if accent_hex:
        # Target 4mm, held inside the measured 3-6% band.
        stripe_m = min(max(STRIPE_TARGET_M, h * STRIPE_MIN_FRAC), h * STRIPE_MAX_FRAC)
        stripe_h = stripe_m * unit_scale

        bpy.ops.mesh.primitive_cube_add(
            size=1.0, location=(0, front_y, bottom_z + stripe_h / 2),
        )
        stripe = bpy.context.active_object
        stripe.name = "accent_stripe"
        stripe_top_z = bottom_z + stripe_h
        stripe.scale = (face_w * 0.999, half_thick * 2, stripe_h)
        bpy.ops.object.transform_apply(scale=True)
        stripe_mat = make_material("accent_stripe_mat", accent_hex,
                                   roughness=MATTE_ROUGHNESS)
        stripe.data.materials.append(stripe_mat)

        # Parent BEFORE rotating, and pin matrix_parent_inverse explicitly. Both
        # meshes currently bake to identity object transforms (transform_apply
        # defaults to location=True), so the carton's rotation is about the world
        # Z axis through its own centre and the stripe rides along correctly even
        # without this. That is a coincidence of the current build order, not a
        # guarantee: give a child a non-identity parent matrix and an identity
        # matrix_parent_inverse and the parent's transform is applied twice.
        stripe.parent = box
        stripe.matrix_parent_inverse = box.matrix_world.inverted()

    # The badge: brand colour's second and only other permitted appearance.
    # Filled with palette.PRIMARY — the lighter tone — while the stripe above
    # takes the darker palette.accent. That is not a guess: sampling the badge in
    # all nine curated references matches primary every time (T1's #DDA7A5 reads
    # (207,157,155), T3's #E2583E reads (214,89,65)), and reference_analysis.md
    # §5 does not say which of the two it is.
    badge_left_x = None
    primary_hex = None if design else palette.get("primary")
    if primary_hex:
        # Sized off the SHORTER front-face edge. Measured against the references
        # that holds to 21-37%, where sizing from face height alone spreads
        # 12-29% and from face width 7-37% — a wide flat T3 and a tall narrow
        # T_VERT_VIAL only agree on the short edge.
        side = BADGE_SIDE_FRAC * min(face_w, face_h)
        badge_x = right_x - BADGE_MARGIN_RIGHT_FRAC * face_w - side / 2
        badge_z = top_z - BADGE_MARGIN_TOP_FRAC * face_h - side / 2
        badge_left_x = badge_x - side / 2
        # Always fits, so no clamp: side + margin is 0.30 of the shorter edge,
        # comfortably inside both face dimensions, and the badge's lower edge
        # stays far above the stripe (which never exceeds 6% of face height).

        # Local +X is the far/right end of the front face in frame: the camera
        # looks along +Y, so world +X is image-right, and rotating the carton by
        # +ROTATION_DEG about Z turns the front normal to (sin, -cos, 0) — still
        # facing the camera, angled right. Top-right on film is therefore max X,
        # max Z here.
        bpy.ops.mesh.primitive_cube_add(
            size=1.0, location=(badge_x, front_y, badge_z),
        )
        badge = bpy.context.active_object
        badge.name = "brand_badge"
        badge.scale = (side, half_thick * 2, side)
        bpy.ops.object.transform_apply(scale=True)
        badge_mat = make_material("brand_badge_mat", primary_hex,
                                  roughness=MATTE_ROUGHNESS)
        badge.data.materials.append(badge_mat)

        # Parented before the rotation below, same reasoning as the stripe.
        badge.parent = box
        badge.matrix_parent_inverse = box.matrix_world.inverted()

    dosage_block = None
    if design and not BLANK_CARTON:
        _, blocks = build_design_fields(box, design, face_w, face_h, depth,
                                        right_x - face_w, front_y, top_z,
                                        half_thick, finish)
        dosage_block = blocks[0] if blocks else None

    if not BLANK_CARTON:
        build_label(box, label_content, face_w, face_h, right_x - face_w,
                    front_y, top_z, half_thick, unit_scale, badge_left_x,
                    stripe_top_z, dosage_block,
                    (design or {}).get("type_rows"), design)

    if design and not BLANK_CARTON:
        build_reference_aux_text(
            box, design.get("reference_aux_text") or [], face_w, face_h,
            depth, right_x - face_w, front_y, top_z, half_thick)

    measured_left_surface = any(
        field.get("surface", "front") == "left"
        for field in ((design or {}).get("fields") or [])
    )
    if manifest and not BLANK_CARTON and not measured_left_surface:
        build_side_panel(box, manifest, depth, face_h, min(xs), front_y,
                         top_z, half_thick, unit_scale)

    box.rotation_euler[2] = math.radians(ROTATION_DEG)
    return box, max(w, h, d)


_LAST_SHADOW_RIG = {
    "enabled": False,
    "scope": "common_carton_rig",
    "method": "none",
    "receiver_scale": 0.0,
    "receiver_offset_frac": 0.0,
    "engine": ENGINE,
}


def _disable_receiver_indirect(plane):
    for attr in ("visible_diffuse", "visible_glossy", "visible_transmission",
                 "visible_volume_scatter"):
        if hasattr(plane, attr):
            setattr(plane, attr, False)


def build_background(hex_color: str, exposure: float, target_size: float):
    """A seamless emissive backdrop plus one compact contact receiver.

    It used to be a diffuse plane lit by the key and fill. Two small lights
    cannot light 50 metres of plane evenly, so the render showed a hot spot
    behind the carton falling away to grey (measured: corner brightness 75-178
    across templates, against the flat 255 every reference holds) plus a hard
    cast shadow reaching well clear of the box. reference_analysis.md §1 asks for
    "a single, seamless white plane with no floor/wall transition visible" and §3
    for a contact shadow "minimal to nearly absent" — measured, the references
    sit at 254.9 directly beneath the carton, i.e. no shadow to speak of.

    Making the backdrop EMISSIVE decouples it from the rig: it renders at a fixed
    value everywhere and needs no light aimed at it.  A separate compact plane
    now evaluates only local geometric occlusion beneath the carton, producing
    the requested soft support without exposing a floor, horizon or rectangle.
    """
    global _LAST_SHADOW_RIG
    mode = "off" if SHADOW_OFF else "receiver"
    plane_scale = 50.0 / target_size
    receiver_offset_frac = 0.0005 if mode != "off" else 0.0
    bpy.ops.mesh.primitive_plane_add(
        size=plane_scale * target_size,
        location=(0, 0, -0.002 * target_size))
    plane = bpy.context.active_object
    plane.name = "background"

    mat = bpy.data.materials.new(name="background_mat")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")

    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = hex_to_rgba(
        hex_color or "#FFFFFF")
    # Exactly full scale after the film transform, so the backdrop always
    # renders pure white whatever exposure this carton is metered at.
    emission.inputs["Strength"].default_value = 2.0 ** (-exposure)
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    _disable_receiver_indirect(plane)
    if hasattr(plane, "visible_shadow"):
        plane.visible_shadow = False
    plane.data.materials.append(mat)

    if mode == "receiver":
        # A compact real receiver evaluates geometric occlusion only under and
        # immediately around the carton.  The former full-frame AO receiver met
        # every image gate but made a matched 2048 render 61% slower; limiting
        # the same physical calculation to its useful support is the measured
        # performance fix.  A Generated-coordinate feather reaches transparent
        # before the boundary, leaving the emissive studio plane visible there.
        receiver_scale = 1.5
        feather_start = 0.40
        ao_distance_frac = 0.04
        ao_samples = 4
        shadow_floor_linear = 0.78
        bpy.ops.mesh.primitive_plane_add(
            size=receiver_scale * target_size,
            location=(0, 0, -receiver_offset_frac * target_size))
        receiver = bpy.context.active_object
        receiver.name = "shadow_receiver"

        receiver_mat = bpy.data.materials.new(name="shadow_receiver_mat")
        receiver_mat.use_nodes = True
        rnodes = receiver_mat.node_tree.nodes
        rlinks = receiver_mat.node_tree.links
        rnodes.clear()
        rout = rnodes.new("ShaderNodeOutputMaterial")
        ao = rnodes.new("ShaderNodeAmbientOcclusion")
        ao.inputs["Color"].default_value = hex_to_rgba(
            hex_color or "#FFFFFF")
        ao.inputs["Distance"].default_value = ao_distance_frac * target_size
        ao.samples = ao_samples
        ao.only_local = False
        ramp = rnodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.interpolation = "EASE"
        ramp.color_ramp.elements[0].position = 0.0
        ramp.color_ramp.elements[0].color = (
            shadow_floor_linear, shadow_floor_linear,
            shadow_floor_linear, 1.0)
        ramp.color_ramp.elements[1].position = 1.0
        ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
        lit_receiver = rnodes.new("ShaderNodeEmission")
        lit_receiver.inputs["Strength"].default_value = 2.0 ** (-exposure)
        rlinks.new(ao.outputs["AO"], ramp.inputs["Fac"])
        rlinks.new(ramp.outputs["Color"], lit_receiver.inputs["Color"])

        texcoord = rnodes.new("ShaderNodeTexCoord")
        separate = rnodes.new("ShaderNodeSeparateXYZ")
        rlinks.new(texcoord.outputs["Generated"], separate.inputs["Vector"])
        edge_x = rnodes.new("ShaderNodeMath")
        edge_x.operation = "SUBTRACT"
        edge_x.inputs[1].default_value = 0.5
        rlinks.new(separate.outputs["X"], edge_x.inputs[0])
        abs_x = rnodes.new("ShaderNodeMath")
        abs_x.operation = "ABSOLUTE"
        rlinks.new(edge_x.outputs[0], abs_x.inputs[0])
        edge_y = rnodes.new("ShaderNodeMath")
        edge_y.operation = "SUBTRACT"
        edge_y.inputs[1].default_value = 0.5
        rlinks.new(separate.outputs["Y"], edge_y.inputs[0])
        abs_y = rnodes.new("ShaderNodeMath")
        abs_y.operation = "ABSOLUTE"
        rlinks.new(edge_y.outputs[0], abs_y.inputs[0])
        edge = rnodes.new("ShaderNodeMath")
        edge.operation = "MAXIMUM"
        rlinks.new(abs_x.outputs[0], edge.inputs[0])
        rlinks.new(abs_y.outputs[0], edge.inputs[1])
        fade = rnodes.new("ShaderNodeMapRange")
        fade.clamp = True
        fade.inputs["From Min"].default_value = feather_start
        fade.inputs["From Max"].default_value = 0.5
        fade.inputs["To Min"].default_value = 0.0
        fade.inputs["To Max"].default_value = 1.0
        rlinks.new(edge.outputs[0], fade.inputs["Value"])
        transparent = rnodes.new("ShaderNodeBsdfTransparent")
        mix = rnodes.new("ShaderNodeMixShader")
        rlinks.new(fade.outputs["Result"], mix.inputs[0])
        rlinks.new(lit_receiver.outputs["Emission"], mix.inputs[1])
        rlinks.new(transparent.outputs[0], mix.inputs[2])
        rlinks.new(mix.outputs[0], rout.inputs["Surface"])
        receiver.data.materials.append(receiver_mat)
        _disable_receiver_indirect(receiver)
        _LAST_SHADOW_RIG = {
            "enabled": True,
            "scope": "common_carton_rig",
            "method": "physical_receiver",
            "receiver_scale": receiver_scale,
            "receiver_offset_frac": receiver_offset_frac,
            "feather_start": feather_start,
            "ao_distance_frac": ao_distance_frac,
            "ao_samples": ao_samples,
            "shadow_floor_linear": shadow_floor_linear,
            "engine": ENGINE,
        }
    else:
        _LAST_SHADOW_RIG = {
            "enabled": False,
            "scope": "common_carton_rig",
            "method": "none",
            "receiver_scale": 0.0,
            "receiver_offset_frac": 0.0,
            "engine": ENGINE,
        }

    # A large bright surface would otherwise bounce into the carton, lifting the
    # shadows and washing the accent out of tolerance. EEVEE does not gather that
    # indirect light anyway, but Cycles does, and the same driver has to serve
    # both — so switch the backdrop out of every indirect path explicitly.
    # Per-mode visibility is set above; all three share one receiver object and
    # scale rule, so the spike changes one variable rather than the studio rig.


LENS_MM = 85.0        # matches the documented Gemini optical calibration
SENSOR_MM = 36.0      # Blender's default sensor width
# How much of the frame the carton's BOUNDING SPHERE is asked to fill. Values
# Calibrated against the measured reference renders, whose dominant axis fills
# 76-88% of frame with the object centred at 50-52% height. This value belongs
# to the TRUE-SCALE carton: while the mesh was built at half its nominal
# millimetres the same framing needed 1.70, and the two must move together.
# (Note the "45-55%" quoted in reference_analysis.md §1 does not match a direct
# measurement of those same images.)
SPHERE_FILL = 0.8365


def setup_camera(dims_m):
    """Frame the carton from its real size rather than a fixed distance.

    Distance is solved from the bounding sphere and the lens field of view, so
    a 35mm-deep dropper carton and a 170mm-tall vial tray both fill the frame
    consistently. The previous fixed `max(size*3, 0.3)` worked only while every
    box was the same nominal 100mm; with real dimensions it cropped tall cartons
    and left flat ones tiny.
    """
    w, h, d = dims_m
    centre_z = h / 2.0

    radius = 0.5 * math.sqrt(w * w + h * h + d * d)
    half_fov = math.atan((SENSOR_MM / 2.0) / LENS_MM)
    distance = radius / math.sin(SPHERE_FILL * half_fov)

    pitch = math.radians(PITCH_DEG)
    cam_y = -distance * math.cos(pitch)
    cam_z = centre_z + distance * math.sin(pitch)

    # Aim by explicit rotation rather than a TRACK_TO constraint. A constraint
    # only resolves once the depsgraph is evaluated, which made framing depend
    # on evaluation order and left the carton riding high in the frame; a
    # camera rotated (90deg - pitch) about X looks along +Y tilted down by
    # exactly `pitch`, putting the aim point dead centre every time.
    bpy.ops.object.camera_add(
        location=(0.0, cam_y, cam_z),
        rotation=(math.radians(90.0) - pitch, 0.0, 0.0),
    )
    cam = bpy.context.active_object
    cam.name = "camera"
    cam.data.lens = LENS_MM
    cam.data.dof.aperture_fstop = 8.0  # f/8, same documented value (DOF stays off)

    bpy.context.scene.camera = cam


# ── the light rig ────────────────────────────────────────────────────────────
# One studio for the whole catalogue. Every quantity below is a multiple of the
# carton's own size, so the rig is scale-invariant: from the carton's point of
# view the key always arrives from the same direction and subtends the same
# angle, whatever the carton measures. Directions are as built, NOT as sometimes
# described in prose — the key is on the camera's RIGHT (+X) and the fill on its
# LEFT (-X); do not "correct" them the other way round.
#
# The key sits WELL IN FRONT of the carton, not beside it, and that is the whole
# of it. At the old (2, -2, 3) the printed front face stood almost edge-on to the
# key: cos 0.119 against the top face's cos 0.728, so the key put 6.1x more light
# on the lid than on the face it exists to light. Two things followed, both
# measured on 2026-08-09.
#
# The top face rendered at 255.0 -- pure clipped white, brighter than the 254.96
# backdrop -- so the carton lost its volume and read as a flat label. The nine
# references put their top face 10 to 33 levels BELOW the backdrop, at 0.89-1.04
# of their own front face. Ours was at 2.60x.
#
# And the fill was doing the key's job: 5.94 of the front face's light against
# the key's 2.98, twice as much from a light a third the wattage. That is also
# why the film exposure had to be pulled nearly three stops -- the rig was
# lighting the lid and the frame, and the face was catching the spill.
#
# (2, -4.5, 3) keeps the key on the camera's right and at a similar elevation,
# and moves it forward: top/front falls to 1.06, in the references' band, and the
# key takes back 1.85x the fill's share of the front face.
KEY_OFFSET  = (3.0, -3.0, 2.0)    # x, y, z in multiples of target_size
FILL_OFFSET = (-2.0, -1.5, 2.0)
LIGHT_SIZE_FRAC = 2.0             # area-light edge, also in multiples

# Scene is macro-scale (objects ~0.05-0.3m, camera ~0.3-1m away). Blender's
# AREA-light Watts are calibrated for room-scale scenes; at this proximity the
# values once here (800W/300W) clipped the whole frame to white (found + fixed
# via the smoke-test render — see roadmap §9). These stay studio-strobe scale;
# they are NOT to be raised back toward room wattages.
KEY_ENERGY_W  = 25
FILL_ENERGY_W = 8

# The size these wattages were tuned at: the T1 family's largest dimension, and
# also the catalogue's modal carton — 259 of 391 SKU measure exactly this, so
# two thirds of the catalogue is lit at literally 25 W / 8 W as before.
LIGHT_REF_SIZE_M = 0.115


def light_energy(base_w: float, target_size: float) -> float:
    """Base wattage corrected so irradiance at the carton is size-independent.

    The rig's positions are multiples of target_size, so light DISTANCE scales
    linearly with the carton while a fixed wattage does not — and irradiance from
    a fixed-power source falls as 1/distance². Big cartons were therefore lit
    dimmer than small ones by exactly the factor the rig grew: measured across
    the nine curated templates the front face ran 182-255 where the references
    hold a tight 232-243, and no single exposure can close a spread like that
    because exposure moves every template together.

    Scaling power with the SQUARE of the size ratio cancels the falloff exactly.
    Over the real catalogue (target_size 0.080-0.170m) that is 0.48x-2.19x, i.e.
    key 12-55 W. Note this is a change of INTERPRETATION, not of the protected
    numbers: 25 W / 8 W is now the power *at the reference size*, and at that
    size the rig is bit-for-bit what it was.
    """
    return base_w * (target_size / LIGHT_REF_SIZE_M) ** 2


# Captured for --dump-scene, which needs to report the size the rig resolved
# against. Not read by anything that builds the scene.
_LAST_TARGET_SIZE = None


def setup_lighting(target_size: float):
    global _LAST_TARGET_SIZE
    _LAST_TARGET_SIZE = target_size
    # Size is strictly proportional, with no lower clamp. A clamp makes the light
    # relatively LARGER on a small carton, i.e. softer shadows there than on a big
    # one — a per-template style difference, which is the thing this rig exists to
    # avoid. (The clamp that used to sit here never bound in practice: the
    # smallest carton in the catalogue puts the light at 0.160, above the old
    # 0.15 floor. Removing it costs nothing today and closes the hole.)
    key = bpy.data.lights.new(name="key_light", type="AREA")
    key.energy = light_energy(KEY_ENERGY_W, target_size)
    key.size = target_size * LIGHT_SIZE_FRAC
    key_obj = bpy.data.objects.new("key_light", key)
    key_obj.location = tuple(c * target_size for c in KEY_OFFSET)
    bpy.context.collection.objects.link(key_obj)

    fill = bpy.data.lights.new(name="fill_light", type="AREA")
    fill.energy = light_energy(FILL_ENERGY_W, target_size)
    fill.size = target_size * LIGHT_SIZE_FRAC
    fill_obj = bpy.data.objects.new("fill_light", fill)
    fill_obj.location = tuple(c * target_size for c in FILL_OFFSET)
    bpy.context.collection.objects.link(fill_obj)

    # Pin the world background explicitly (rather than relying on
    # --factory-startup's default) so exposure is deterministic across
    # Blender versions/installs — a project invariant (see PROJECT_HISTORY.md
    # Determinism discussion for the Gemini engine's contrasting lack of this).
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.05, 0.05, 0.05, 1.0)
        bg.inputs["Strength"].default_value = 0.3


# Film response, pinned for the same reason the world background is: so exposure
# is deterministic across Blender versions and installs rather than inherited
# from whatever --factory-startup currently defaults to.
#
# This is a CAMERA/FILM setting, not a lighting one. setup_lighting()'s 25 W key
# and 8 W fill are a deliberate studio-strobe-scale fix (see its comment) and are
# not what needed correcting. Blender's default AgX transform rolls the
# highlights off far enough to hide that the scene is over-exposed: the white
# body still landed at a plausible 237, while the ~15%-albedo accent stripe came
# out (195,135,179) — a pale orchid — against the (99,42,72) the references
# measure. A pastel stripe satisfies "brand colour appears here" only on paper.
#
# Measured, not estimated: render the front face at an exposure low enough that
# nothing clips, read it, and scale back. That puts the face at ~6.0-6.7x full
# scale, i.e. ~2.9 stops hot, against the 0.858 linear the references hold.
# Estimating this off an AgX render instead gives ~2.0 — AgX is not linear, and
# at -2.0 the T1 face still clips at 255, dragging the badge and stripe printed
# on it out of tolerance too.
#
# light_energy() equalises irradiance across carton SIZES, which took the
# per-template requirement from ~1.2 stops down to 0.17. What survives is not a
# size effect but a SHAPE one, and it separates cleanly with no overlap:
#
#     landscape cartons (w >= h)  want -2.74 .. -2.77      -> -2.76
#     portrait  cartons (h >  w)  want -2.82 .. -2.87      -> -2.84
#
# Re-measured under CYCLES on the TRUE-SCALE carton, which is what production
# renders. The earlier figures (-2.75 / -2.88) came from EEVEE on the half-scale
# mesh, because a broken engine check reported CYCLES unavailable on every
# install and every render silently fell through. They survived the correction
# almost intact - the rig scales with the carton and the film response is a pure
# multiplier - but "almost" is not "measured", so these are the measured ones.
#
# The key is an area light roughly two face-widths from the carton. Across a WIDE
# front face its far end is materially further away than its near end, so the
# mean over the face drops; a narrow portrait face barely sees that. No single
# scalar rig size can equalise the horizontal and the vertical falloff at once
# for both shapes — it is geometry, not a defect, and correcting it in the rig
# would mean changing the rig's proportions, i.e. the look.
#
# So the LIGHTING stays bit-for-bit identical for every carton and only the
# metered exposure differs — which is what a photographer does anyway: the strobe
# pack is not touched between shots, the meter is read for each one. Two values
# keyed on carton shape, not a nine-entry table keyed on template.
FILM_VIEW_TRANSFORM = "Standard"
FILM_EXPOSURE_LANDSCAPE = -2.18
FILM_EXPOSURE_PORTRAIT = -2.21


def film_exposure(dims_m) -> float:
    """Exposure for this carton's shape. See FILM_EXPOSURE_* above."""
    w, h, _ = dims_m
    return FILM_EXPOSURE_LANDSCAPE if w >= h else FILM_EXPOSURE_PORTRAIT


def setup_film(exposure: float):
    view = bpy.context.scene.view_settings
    view.view_transform = FILM_VIEW_TRANSFORM
    view.exposure = exposure


def setup_device(scene):
    """Pin Cycles to the device it was ASKED for, or stop.

    The device used to be whatever the process inherited. Under
    `--factory-startup` that is CPU, so nothing looked wrong -- but nothing
    was choosing it either, and a `--python` argument ahead of this script is
    enough to move the render onto the GPU. `scripts/probe_render_device.py`
    does precisely that, on purpose, and it is why this function exists.

    A DEVICE IS NOT A QUALITY SETTING AND IS NOT SUBSTITUTABLE. Measured
    2026-08-24 on an RTX 2060 SUPER at 16 samples, against the CPU render of
    `1-min`, `64-min` and `357-min`: OptiX sampling lands up to 43 levels away
    on 0.2-0.9% of pixels, CUDA up to 23 on 0.2-0.7%, and GPU denoising up to
    43 on 14-18%. Every one of those would invalidate the calibration curve, the
    `design_qa` rows and the OCR fixtures, all of which were measured on CPU
    pixels. So an unavailable device raises `SystemExit` rather than falling
    back -- the same rule the engine already follows one function down, and for
    the same reason: a quietly swapped renderer emits off-spec packshots with
    nothing in the log to say so.

    SystemExit specifically, because Blender prints an ordinary traceback and
    still exits 0, which `blender_renderer.py` would read as a success.
    """
    if DEVICE not in ("CPU", "GPU"):
        raise SystemExit(
            f"[render_driver] blender.device must be CPU or GPU, not "
            f"{DEVICE!r}.")
    if DENOISE_DEVICE not in ("CPU", "GPU"):
        raise SystemExit(
            f"[render_driver] blender.denoising_device must be CPU or GPU, not "
            f"{DENOISE_DEVICE!r}.")

    scene.cycles.device = DEVICE
    if DEVICE == "GPU":
        prefs = bpy.context.preferences.addons["cycles"].preferences
        try:
            prefs.compute_device_type = DEVICE_BACKEND
        except (TypeError, ValueError) as exc:
            raise SystemExit(
                f"[render_driver] compute back-end {DEVICE_BACKEND!r} is not "
                f"one this Blender ({bpy.app.version_string}) offers; refusing "
                f"to substitute another. Blender reports: {exc}")
        prefs.refresh_devices()
        # Only the accelerator is enabled. Leaving the CPU device on as well is
        # a HYBRID render -- a third thing, with its own pixels -- and picking
        # it by accident is exactly the silence this function removes.
        enabled = []
        for dev in prefs.devices:
            dev.use = (dev.type == DEVICE_BACKEND)
            if dev.use:
                enabled.append(dev.name)
        if not enabled:
            raise SystemExit(
                f"[render_driver] blender.device is GPU and blender."
                f"device_backend is {DEVICE_BACKEND!r}, but this machine "
                f"exposes no such device. Refusing to render on the CPU under "
                f"a GPU setting: the two do not produce the same image, and "
                f"every figure this project holds was measured on one of them.")
        print(f"[render_driver] cycles device {DEVICE}/{DEVICE_BACKEND}: "
              f"{', '.join(enabled)}")
    else:
        print(f"[render_driver] cycles device {DEVICE}")

    # Independent of the sampling device, and worth its own key: the denoiser is
    # more than half of every render (~14.9s of 28s, R006), so it is where the
    # time is -- and also where the pixels move most, 14-18% of the frame.
    if hasattr(scene.cycles, "denoising_use_gpu"):
        scene.cycles.denoising_use_gpu = (DENOISE_DEVICE == "GPU")
    elif DENOISE_DEVICE == "GPU":
        raise SystemExit(
            f"[render_driver] blender.denoising_device is GPU but this Blender "
            f"({bpy.app.version_string}) has no `denoising_use_gpu`; refusing "
            f"to denoise on the CPU under a GPU setting.")
    print(f"[render_driver] denoiser "
          f"{getattr(scene.cycles, 'denoiser', '?')} on {DENOISE_DEVICE}")


def setup_render(out_path: str, engine: str, samples: int, res_x: int, res_y: int):
    scene = bpy.context.scene
    # Ask Blender to make the assignment rather than introspecting the enum.
    # RenderSettings.engine is a DYNAMIC enum: Blender builds its real item list
    # through an RNA callback at assignment time, and that list is NOT what
    # bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items returns.
    # That introspection yields only the static placeholder — ('BLENDER_EEVEE',)
    # on 5.1.2 — so it reported CYCLES "unavailable" on every install, including
    # ones where Cycles is enabled and renders fine, and every render quietly
    # fell through to EEVEE with `samples` never applied.
    #
    # An unavailable engine is FATAL, not substituted. Engine choice changes
    # sampling, denoising and light falloff, so a quietly swapped renderer emits
    # off-spec packshots with nothing in the logs to say so — the same reasoning
    # that makes main.py fail Stage 2 when it exits 0 having produced no PNG.
    # SystemExit specifically: Blender prints an ordinary traceback and still
    # exits 0, which blender_renderer.py would read as a successful render.
    try:
        scene.render.engine = engine
    except (TypeError, ValueError) as exc:
        raise SystemExit(
            f"[render_driver] render engine '{engine}' is not available in this "
            f"Blender ({bpy.app.version_string}); refusing to substitute a "
            f"different one. Blender reports: {exc}. Set blender.engine_type in "
            f"config.yaml to an identifier from that list.")

    print(f"[render_driver] engine {scene.render.engine} "
          f"({samples} samples, {res_x}x{res_y})")
    if engine == "CYCLES":
        scene.cycles.samples = samples
        scene.cycles.use_denoising = True
        setup_device(scene)
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = out_path


def _save_mask(path, values):
    import numpy as np

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.tmp{target.suffix}")
    grey = np.asarray(values, dtype=np.float32)
    rgba = np.empty((RES_Y, RES_X, 4), dtype=np.float32)
    rgba[:, :, :3] = np.clip(grey[:, :, None], 0.0, 1.0)
    rgba[:, :, 3] = 1.0
    image = bpy.data.images.new(
        f"{target.stem}_derived_mask", RES_X, RES_Y, alpha=True,
        float_buffer=False)
    image.colorspace_settings.name = "Non-Color"
    image.file_format = "PNG"
    image.filepath_raw = str(temporary)
    image.pixels.foreach_set(rgba.ravel())
    image.save()
    bpy.data.images.remove(image)
    os.replace(temporary, target)
    print(f"[render_driver] wrote derived mask {target}")


def _convex_hull(points):
    unique = sorted(set((float(x), float(y)) for x, y in points))
    if len(unique) <= 1:
        return unique

    def cross(origin, a, b):
        return ((a[0] - origin[0]) * (b[1] - origin[1])
                - (a[1] - origin[1]) * (b[0] - origin[0]))

    lower = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _projected_object_mask():
    """Rasterize the convex carton envelope through the actual scene camera."""
    import numpy as np
    from bpy_extras.object_utils import world_to_camera_view

    scene = bpy.context.scene
    camera = scene.camera
    if camera is None:
        raise SystemExit(
            "[render_driver] derived object mask requires the built camera")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    carton = bpy.data.objects.get("carton")
    if carton is None:
        raise SystemExit(
            "[render_driver] derived object mask requires procedural carton")
    projected = []
    for obj in scene.objects:
        # The carton and its measured construction details own the outer
        # silhouette.  Printed curves and glyph meshes are guaranteed inside
        # that envelope; tessellating all of their vertices made mask export
        # slower than the beauty render without changing one boundary pixel.
        is_envelope = (obj == carton
                       or obj.get("carton_detail_kind") is not None)
        if (not is_envelope or obj.hide_render
                or obj.type not in {"MESH", "CURVE", "FONT"}):
            continue
        evaluated = obj.evaluated_get(depsgraph)
        if obj.type == "FONT":
            local_corners = evaluated.bound_box
        else:
            mesh = evaluated.to_mesh()
            if not mesh.vertices:
                evaluated.to_mesh_clear()
                continue
            mins = [min(vertex.co[axis] for vertex in mesh.vertices)
                    for axis in range(3)]
            maxs = [max(vertex.co[axis] for vertex in mesh.vertices)
                    for axis in range(3)]
            local_corners = [
                (x, y, z)
                for x in (mins[0], maxs[0])
                for y in (mins[1], maxs[1])
                for z in (mins[2], maxs[2])
            ]
            evaluated.to_mesh_clear()
        object_points = []
        for corner in local_corners:
            # Match _bounds_in_frame: evaluated geometry supplies the bounds,
            # while the original object's matrix carries the parent transform.
            # Using evaluated.matrix_world here applies the carton parent twice
            # for curves on Blender 5.1 and projects them thousands of pixels
            # outside a 64px test frame.
            world = obj.matrix_world @ mathutils.Vector(corner)
            ndc = world_to_camera_view(scene, camera, world)
            object_points.append((
                ndc.x * RES_X, ndc.y * RES_Y))
        projected.extend(object_points)
    hull = _convex_hull(projected)
    if len(hull) < 3:
        raise SystemExit(
            "[render_driver] derived object mask has no projected carton hull")
    hull_bounds = (min(x for x, _y in hull), min(y for _x, y in hull),
                   max(x for x, _y in hull), max(y for _x, y in hull))
    if (hull_bounds[0] < -RES_X or hull_bounds[1] < -RES_Y
            or hull_bounds[2] > 2 * RES_X or hull_bounds[3] > 2 * RES_Y):
        raise SystemExit(
            "[render_driver] projected carton hull is outside the frame: "
            f"{hull_bounds}")

    mask = np.zeros((RES_Y, RES_X), dtype=bool)
    min_y = max(0, int(math.floor(min(y for _x, y in hull))))
    max_y = min(RES_Y - 1, int(math.ceil(max(y for _x, y in hull))))
    for row in range(min_y, max_y + 1):
        scan_y = row + 0.5
        intersections = []
        for index, (x0, y0) in enumerate(hull):
            x1, y1 = hull[(index + 1) % len(hull)]
            if (y0 <= scan_y < y1) or (y1 <= scan_y < y0):
                intersections.append(
                    x0 + (scan_y - y0) * (x1 - x0) / (y1 - y0))
        if len(intersections) < 2:
            continue
        left, right = min(intersections), max(intersections)
        start = max(0, int(math.ceil(left - 0.5)))
        stop = min(RES_X, int(math.floor(right - 0.5)) + 1)
        if start < stop:
            mask[row, start:stop] = True
    return mask


def save_diagnostic_passes():
    """Derive masks from scene projection and the existing beauty render."""
    import numpy as np

    if not (OBJECT_MASK_PATH or SHADOW_MASK_PATH):
        return
    if SHADOW_MASK_PATH and not _LAST_SHADOW_RIG.get("enabled"):
        raise SystemExit(
            "[render_driver] derived shadow mask requested while shadow rig is off")

    object_mask = _projected_object_mask()

    if OBJECT_MASK_PATH:
        _save_mask(OBJECT_MASK_PATH, object_mask.astype(np.float32))
    if not SHADOW_MASK_PATH:
        return

    beauty = bpy.data.images.load(str(Path(OUT_PATH)), check_existing=False)
    beauty_pixels = np.empty(RES_X * RES_Y * 4, dtype=np.float32)
    beauty.pixels.foreach_get(beauty_pixels)
    beauty_rgba = beauty_pixels.reshape((RES_Y, RES_X, 4))
    bpy.data.images.remove(beauty)
    luma = (0.2126 * beauty_rgba[:, :, 0]
            + 0.7152 * beauty_rgba[:, :, 1]
            + 0.0722 * beauty_rgba[:, :, 2])
    outside = ~object_mask
    if not outside.any():
        raise SystemExit(
            "[render_driver] projected object mask covers the whole frame; "
            "refusing to derive a shadow from an invalid mask")
    white = float(np.percentile(luma[outside], 99.5))
    shadow = np.clip(white - luma, 0.0, 1.0)
    ys, xs = np.nonzero(object_mask)
    radius = max(2, int(round(max(RES_X, RES_Y) * 0.05)))
    near = np.zeros_like(object_mask)
    near[max(0, int(ys.min()) - radius):
         min(RES_Y, int(ys.max()) + radius + 1),
         max(0, int(xs.min()) - radius):
         min(RES_X, int(xs.max()) + radius + 1)] = True
    padded = np.pad(object_mask, 1, mode="constant")
    object_ring = np.logical_or.reduce([
        padded[0:-2, 0:-2], padded[0:-2, 1:-1], padded[0:-2, 2:],
        padded[1:-1, 0:-2], padded[1:-1, 1:-1], padded[1:-1, 2:],
        padded[2:, 0:-2], padded[2:, 1:-1], padded[2:, 2:],
    ])
    shadow = np.where(near & ~object_ring & (shadow > 0.002), shadow, 0.0)
    _save_mask(SHADOW_MASK_PATH, shadow)


def _base_color(obj):
    """Linear RGBA of an object's first Principled BSDF, or None."""
    if not obj.data.materials:
        return None
    mat = obj.data.materials[0]
    if not mat.use_nodes:
        return None
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        return None
    return list(bsdf.inputs["Base Color"].default_value)


def _roughness(obj):
    """Roughness of an object's first Principled BSDF, or None."""
    if not obj.data.materials:
        return None
    mat = obj.data.materials[0]
    if not mat.use_nodes:
        return None
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is None or "Roughness" not in bsdf.inputs:
        return None
    return bsdf.inputs["Roughness"].default_value


def _material_finish(obj):
    """Read the actual carton material graph back into the scene dump."""
    if not obj.data.materials:
        return None
    mat = obj.data.materials[0]
    if not mat.use_nodes:
        return None
    nodes = mat.node_tree.nodes
    mapping = nodes.get("Carton Seed Mapping")
    noise = nodes.get("Carton Paper Grain")
    bump = nodes.get("Carton Micro Bump")
    bsdf = nodes.get("Principled BSDF")
    base_input = (bsdf.inputs.get("Base Color") if bsdf is not None else None)
    return {
        "node_types": sorted(node.bl_idname for node in nodes),
        "mapping_location": (
            list(mapping.inputs["Location"].default_value[:3])
            if mapping is not None else None),
        "mapping_scale": (
            list(mapping.inputs["Scale"].default_value[:3])
            if mapping is not None else None),
        "noise_scale": (
            float(noise.inputs["Scale"].default_value)
            if noise is not None else None),
        "bump_strength": (
            float(bump.inputs["Strength"].default_value)
            if bump is not None else None),
        "bump_distance_m": (
            float(bump.inputs["Distance"].default_value)
            if bump is not None else None),
        "noise_linked_to_base_color": bool(
            base_input is not None and any(
                link.from_node == noise for link in base_input.links)),
    }


def _fill_area(obj):
    """One side of a filled 2D curve's area, in the object's own units.

    The measurement that makes contract 1.8 checkable without rendering. A hole
    is another cyclic spline of the same curve and Blender fills by nesting, so
    whether the hole was CUT or merely drawn shows up here and nowhere else in
    the dump: the bounding box is identical either way.

    Caps only -- the polygons whose local normal is +-Z -- halved, because the
    extrude gives the region a front and a back. Measured on 5.1.2, a unit
    square with a 0.5 inner square returns 0.7500 unextruded and 1.5000 in caps
    at 0.05 extrude, whichever way either ring is wound.
    """
    if obj.type != "CURVE":
        return None
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    caps = sum(pg.area for pg in me.polygons if abs(pg.normal.z) > 0.9)
    ev.to_mesh_clear()
    return round(caps / 2.0, 10)


def _bounds_in_frame(obj, reference):
    """Axis-aligned bounds of obj's mesh expressed in `reference`'s local frame.

    Measured in the carton's own frame rather than in world space on purpose: a
    thin plate lying flat on a rotated box has a world-space AABB that pokes
    outside the box's world-space AABB even when it is perfectly glued on, so a
    world-space containment check reports false alarms. In the carton's frame
    "on the front face, at the bottom" is a plain interval comparison.
    """
    to_ref = reference.matrix_world.inverted() @ obj.matrix_world
    if obj.type == "FONT":
        # A text object has no vertices until the depsgraph builds its glyphs,
        # so the evaluated bounding box is the measurement.
        from mathutils import Vector
        dg = bpy.context.evaluated_depsgraph_get()
        pts = [to_ref @ Vector(c) for c in obj.evaluated_get(dg).bound_box]
    elif obj.type == "CURVE":
        # A curve is measured from its TESSELLATED MESH, and the difference from
        # the branch above is not stylistic.
        #
        # CURVE was added with the contract-1.4 design fields, which are filled
        # 2D curves, and it was put on the same evaluated bound_box as FONT.
        # Blender does not fill that in for a curve: measured on 5.1.2 with a
        # 0.05 x 0.03 rectangle extruded by 0.0001, `evaluated_get(dg).bound_box`
        # returns the DEFAULT unit cube -- (-1,-1,-1) to (1,1,1) -- while the raw
        # `obj.bound_box` is exact and `to_mesh()` carries 16 real vertices
        # spanning the rectangle. So every design field in every scene dump has
        # reported a two-unit box on a carton 0.09 units wide.
        #
        # It went unseen because nothing read it: the design-field tests check
        # `name`, `roughness` and `base_color`. A test written against these
        # bounds would have passed for the wrong reason, which is how it was
        # found -- contract 1.7's paint-order test asked how thick the stack is
        # and got 1.0.
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        mesh = ev.to_mesh()
        pts = [to_ref @ v.co for v in mesh.vertices]
        ev.to_mesh_clear()
        if not pts:
            from mathutils import Vector
            pts = [to_ref @ Vector(c) for c in obj.bound_box]
    else:
        pts = [to_ref @ v.co for v in obj.data.vertices]
    return {
        "min": [min(p[i] for p in pts) for i in range(3)],
        "max": [max(p[i] for p in pts) for i in range(3)],
    }


# ── Where the printed faces landed in the rendered frame ─────────────────────
# OCR of a packshot needs the front face flattened first, and flattening needs
# its four corners in pixels. The renderer holds the camera and the built mesh,
# so it publishes the answer; a consumer that reconstructs it from the image is
# guessing, and two attempts to do that failed.
#
# Corners come off the built mesh's bound_box, never off (w, h, d) -- see the
# note in build_box about the nominal dimensions and the mesh extents not being
# the same thing.
def _order_quad(vert_px_pairs):
    """[top-left, top-right, bottom-right, bottom-left], in image pixels.

    Paired by their LOCAL Z, not by projected pixel y. The carton only ever
    rotates about Z, so local Z is world-up regardless of ROTATION_DEG, and
    "the two points with the smallest local Z are the bottom pair" is always
    true. Sorting by PROJECTED y instead is the bug this replaced: on a wide,
    shallow front face (measured failing on all T3 at 140x35x25mm, aspect
    4.00) the far vertical edge can project ENTIRELY above the near one, so
    the two smallest-y points come from the same edge, not opposite ones, and
    the old code emitted a self-intersecting quad (BR-TR-BL-TL, a diagonal
    crossing) that still passed a same-side ordering check because the sort
    that produced it also satisfies its own consistency. Do not go back to
    sorting the projected points -- it looks right on 370/391 SKU and is
    silently wrong on the rest.

    Requires a VERTICAL face, i.e. one whose four corners do not share a
    single local Z. On a horizontal face -- the carton's lid or base -- all
    four Z values are equal, the sort order between them is arbitrary, and the
    "bottom pair / top pair" split separates nothing: the returned quad would
    be a scramble that still looks well-formed to a caller. Returns None
    rather than that, so a wrong answer cannot be mistaken for a right one.
    """
    by_z = sorted(vert_px_pairs, key=lambda pair: pair[0].z)
    if by_z[2][0].z - by_z[1][0].z < 1e-6:
        print("[render_driver] WARNING: _order_quad was given a face whose "
              "corners share one local Z (a horizontal face). It orders "
              "corners by height, so there is nothing to split on; returning "
              "no corners rather than a scrambled quad.", file=sys.stderr)
        return None
    bottom = sorted((px for _, px in by_z[:2]), key=lambda p: p[0])
    top = sorted((px for _, px in by_z[2:]), key=lambda p: p[0])
    return [top[0], top[1], bottom[1], bottom[0]]


def _face_corners_px(box, axis: int, take_min: bool):
    """One axis-aligned local face of *box*, projected to image pixels.

    axis is 0 or 1 -- local X or Y -- because those are the faces that stand
    upright, and `_order_quad` orders corners by their local Z. **axis 2 is
    not supported**: the lid and base are horizontal, their four corners share
    one Z, and the split `_order_quad` relies on has nothing to separate. It
    returns None in that case rather than a scrambled quad, so this function
    does too; an earlier version of this docstring advertised 0/1/2 and would
    have walked a caller straight into it.

    The front face is local -Y and the visible side panel is local -X;
    +ROTATION_DEG about Z turns both toward the camera.
    """
    from bpy_extras.object_utils import world_to_camera_view
    scene = bpy.context.scene
    cam = scene.camera
    if box is None or cam is None:
        return None
    local = [mathutils.Vector(c) for c in box.bound_box]
    values = [v[axis] for v in local]
    target = min(values) if take_min else max(values)
    face = [v for v in local if abs(v[axis] - target) < 1e-6]
    if len(face) != 4:
        return None
    pairs = []
    for v in face:
        ndc = world_to_camera_view(scene, cam, box.matrix_world @ v)
        # world_to_camera_view puts (0, 0) at the frame's BOTTOM-left with y up;
        # image pixels count from the TOP-left with y down.
        pairs.append((v, [ndc.x * RES_X, (1.0 - ndc.y) * RES_Y]))
    return _order_quad(pairs)


def printed_faces_px():
    """Both printed faces in image pixels, plus the resolution they refer to."""
    box = bpy.data.objects.get("carton")
    scene = bpy.context.scene
    # world_to_camera_view() derives the camera's view frame from the scene's
    # CURRENT render resolution (via Camera.view_frame()), not from RES_X/RES_Y
    # directly. On the --dump-scene path this function runs before
    # setup_render() ever executes, so the scene still holds Blender's own
    # default (1920x1080) rather than the requested resolution; projecting
    # against that mismatched aspect skews the vertical axis -- measured, a
    # corner landed at y=2162 against a reported frame height of 2048. On the
    # render path setup_render() has already set these to the same values, so
    # this is a no-op there and changes nothing about the render itself (it
    # runs after setup_render, and resolution_percentage/file settings are
    # untouched here).
    scene.render.resolution_x = RES_X
    scene.render.resolution_y = RES_Y
    bpy.context.view_layer.update()
    return {
        "resolution": [RES_X, RES_Y],
        "front_face_px": _face_corners_px(box, axis=1, take_min=True),
        # Nothing consumes the side panel yet. It comes from the same call, and
        # emitting it now avoids touching the driver twice.
        "side_panel_px": _face_corners_px(box, axis=0, take_min=True),
    }


def _device_report() -> dict:
    """What Cycles is actually set to sample and denoise on.

    Applies the device settings and then READS THEM BACK, rather than echoing
    the flags it was given. The difference is the whole value of the field: a
    dump that repeats its own input agrees with itself whatever Blender did, and
    the failure this guards against -- the render happening on a device nobody
    chose -- is invisible to it.

    Off CYCLES there is no `scene.cycles`, so the engine is reported and the
    rest is null rather than invented.
    """
    scene = bpy.context.scene
    if ENGINE != "CYCLES":
        return {"engine": ENGINE, "cycles_device": None, "backend": None,
                "enabled_devices": [], "denoising_use_gpu": None}
    try:
        scene.render.engine = ENGINE
    except (TypeError, ValueError) as exc:
        raise SystemExit(
            f"[render_driver] render engine '{ENGINE}' is not available in this "
            f"Blender ({bpy.app.version_string}). Blender reports: {exc}")
    setup_device(scene)
    prefs = bpy.context.preferences.addons["cycles"].preferences
    on_gpu = scene.cycles.device == "GPU"
    return {
        "engine": scene.render.engine,
        "cycles_device": scene.cycles.device,
        # Both null on CPU rather than reported, and that is not tidiness. The
        # preference list keeps whatever devices Blender enabled for itself, so
        # a CPU render would print "enabled_devices: [NVIDIA ...]" and read as
        # though the card were doing the work. `scene.cycles.device` is the only
        # thing that decides, and on CPU the list decides nothing.
        "backend": prefs.compute_device_type if on_gpu else None,
        "enabled_devices": (sorted(d.name for d in prefs.devices if d.use)
                            if on_gpu else []),
        "denoising_use_gpu": getattr(scene.cycles, "denoising_use_gpu", None),
    }


def _projected_splines_px(obj):
    """Actual curve control rings, before extrusion/bevel, in image pixels.

    These are measured off Blender objects with their real normal offsets and
    transforms. They describe the path, not the final beveled mesh silhouette.
    `printed_faces_px` sets the matching projection resolution before this runs.
    """
    if obj.type != "CURVE":
        return None
    from bpy_extras.object_utils import world_to_camera_view
    scene = bpy.context.scene
    if scene.camera is None:
        return None
    rings = []
    for spline in obj.data.splines:
        points = (spline.bezier_points if spline.type == "BEZIER"
                  else spline.points)
        ring = []
        for point in points:
            world = obj.matrix_world @ mathutils.Vector(point.co[:3])
            ndc = world_to_camera_view(scene, scene.camera, world)
            ring.append([float(ndc.x * RES_X), float((1.0 - ndc.y) * RES_Y)])
        rings.append(ring)
    return rings


def _diagnostic_projection(obj):
    """Evaluated mesh triangles including caps, walls and modifiers.

    Pixel origin is top-left; positive depth is distance along the camera view
    axis in scene units (metres). This geometry diagnostic is independent of
    beauty shading. Triangle coverage is not a visibility or lighting result.
    """
    if obj.type not in {"CURVE", "MESH"}:
        return None
    from bpy_extras.object_utils import world_to_camera_view
    scene = bpy.context.scene
    if scene.camera is None:
        return None
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        vertices = []
        for vertex in mesh.vertices:
            # As in _bounds_in_frame, apply the original parent transform to
            # evaluated local vertices; do not apply the parent twice.
            world = obj.matrix_world @ vertex.co
            ndc = world_to_camera_view(scene, scene.camera, world)
            vertices.append([float(ndc.x * RES_X),
                             float((1.0 - ndc.y) * RES_Y), float(ndc.z)])
        return {
            "basis": "evaluated_mesh",
            "resolution": [RES_X, RES_Y],
            "depth_basis": "camera_view_axis_metres_positive_in_front",
            "projected_vertices_px_depth": vertices,
            "triangles": [list(triangle.vertices)
                          for triangle in mesh.loop_triangles],
        }
    finally:
        evaluated.to_mesh_clear()


def dump_scene(path: str):
    """Write the measured geometry of the built scene as JSON."""
    box = bpy.data.objects.get("carton")
    stripe = bpy.data.objects.get("accent_stripe")
    badge = bpy.data.objects.get("brand_badge")
    bpy.context.view_layer.update()

    view = bpy.context.scene.view_settings
    lighting = {"target_size": _LAST_TARGET_SIZE}
    for name in ("key_light", "fill_light"):
        obj = bpy.data.objects.get(name)
        lighting[name] = None if obj is None else {
            "energy": obj.data.energy,
            "size": obj.data.size,
            "location": list(obj.location),
        }
    out = {
        "carton": None,
        "carton_profile": None,
        "visible_carton_geometry": [],
        "stripe": None,
        "badge": None,
        # Present even when nothing was built, so a consumer never has to guess
        # whether an empty panel means "no panel" or "key missing". The
        # hand-authored .blend branch builds none of this.
        "side_panel": [],
        "label": [],
        "reference_aux_text": [],
        "relief": [],
        "design_marks": [],
        "shadow_rig": dict(_LAST_SHADOW_RIG),
        "lighting": lighting,
        # Read back off the scene rather than echoing the FILM_* constants, so
        # the dump reports what Blender actually holds.
        "film": {"view_transform": view.view_transform,
                 "exposure": view.exposure},
        # Which device would draw this frame, read back the same way -- off the
        # scene after the assignment, never echoed from the flags. A dump that
        # repeated its own input could not catch the case this exists for: the
        # device being something nobody asked for. `--dump-scene` returns before
        # setup_render(), so the assignment is made here, on the same seam and
        # for the same reason `setup_film` is applied before this point.
        "device": _device_report(),
        **printed_faces_px(),
    }
    if box is not None:
        out["carton"] = {
            "dimensions": list(box.dimensions),
            "self_bounds": _bounds_in_frame(box, box),
            "rotation_z_deg": math.degrees(box.matrix_world.to_euler().z),
            "base_color": _base_color(box),
            "roughness": _roughness(box),
            "material_finish": _material_finish(box),
        }
        profile_version = box.get("carton_profile_version")
        if profile_version is not None:
            bevel = next((modifier for modifier in box.modifiers
                          if modifier.name == "carton_edge_radius"), None)
            out["carton_profile"] = {
                "profile_version": str(profile_version),
                "edge_radius_m": (float(bevel.width) if bevel else 0.0),
                "edge_segments": (int(bevel.segments) if bevel else 0),
                "board_thickness_m": float(
                    box.get("carton_board_thickness_m", 0.0)),
            }
        out["visible_carton_geometry"] = [
            {
                "name": obj.name,
                "kind": str(obj.get("carton_detail_kind")),
                "surface": str(obj.get("carton_detail_surface")),
                "bounds_in_carton_frame": _bounds_in_frame(obj, box),
                "base_color": _base_color(obj),
                "roughness": _roughness(obj),
                "material_finish": _material_finish(obj),
            }
            for obj in sorted(
                (item for item in bpy.data.objects
                 if item.get("carton_detail_kind") is not None),
                key=lambda item: item.name)
        ]
        for key, obj in (("stripe", stripe), ("badge", badge)):
            if obj is not None:
                out[key] = {
                    "bounds_in_carton_frame": _bounds_in_frame(obj, box),
                    "base_color": _base_color(obj),
                    "roughness": _roughness(obj),
                }
        # The design fields, so the contract-1.4 path is measurable without
        # rendering. A test can then assert that the eleven build their measured
        # design and that the other 380 build none -- which the pixels alone
        # cannot separate from a lucky palette.
        out["design_fields"] = [
            {
                "name": o.name,
                "surface": str(o.get("design_surface", "front")),
                "bounds_in_carton_frame": _bounds_in_frame(o, box),
                "base_color": _base_color(o),
                "roughness": _roughness(o),
                "material_finish": _material_finish(o),
                # Contract 1.8. `splines` is 1 + the number of holes the part
                # carries, and `fill_area_m2` is what those holes actually
                # removed -- the only two figures in this dump that can tell a
                # cut hole from a filled one.
                "splines": (len(o.data.splines) if o.type == "CURVE" else None),
                "fill_area_m2": _fill_area(o),
                "projected_splines_px": _projected_splines_px(o),
                "projected_splines_basis":
                    "curve_control_points_before_extrusion_and_bevel",
                "diagnostic_projection": _diagnostic_projection(o),
            }
            for o in sorted((x for x in bpy.data.objects
                             if x.name.startswith("design_")),
                            key=lambda x: x.name)
        ]
        out["design_marks"] = [
            {
                "name": o.name,
                "surface": str(o.get("design_surface", "front")),
                "bounds_in_carton_frame": _bounds_in_frame(o, box),
                "normal_offset_m": float(
                    o.get("design_normal_offset_m", 0.0)),
                "ink_budget_m": float(o.get("design_ink_budget_m", 0.0)),
                "holes": int(o.get("design_hole_count", 0)),
                "fill": str(o.get("design_fill", "")),
                "mark_key": str(o.get("design_mark_key", "")),
                "mark_part_index": int(o.get("design_mark_part_index", -1)),
                "base_color": _base_color(o),
                "roughness": _roughness(o),
                "material_finish": _material_finish(o),
                "splines": (len(o.data.splines)
                            if o.type == "CURVE" else None),
                "fill_area_m2": _fill_area(o),
                "projected_splines_px": _projected_splines_px(o),
                "projected_splines_basis":
                    "curve_control_points_before_extrusion_and_bevel",
                "diagnostic_projection": _diagnostic_projection(o),
            }
            for o in sorted((x for x in bpy.data.objects
                             if x.name.startswith("mark_")),
                            key=lambda x: x.name)
        ]
        # Every label row, with the exact string it will draw. `body` is what
        # makes the engine's headline claim checkable: a test can compare it byte
        # for byte against the manifest and prove nothing was dropped, truncated
        # or invented on the way to the glyphs.
        out["side_panel"] = [
            {
                "name": o.name,
                "kind": ("barcode" if o.name.startswith("panel_barcode_") and
                         o.type != "FONT" else
                         "rule" if o.name.startswith("panel_rule_") else "text"),
                "body": o.data.body if o.type == "FONT" else None,
                "bounds_in_carton_frame": _bounds_in_frame(o, box),
            }
            for o in sorted((x for x in bpy.data.objects
                             if x.name.startswith("panel_")),
                            key=lambda x: (-x.location.z, x.name))
        ]
        out["label"] = [
            {
                "name": t.name,
                "body": t.data.body,
                "size": t.data.size,
                "align_x": t.data.align_x,
                "font": t.data.font.name if t.data.font else None,
                "bounds_in_carton_frame": _bounds_in_frame(t, box),
                # Where this row's CAPITALS start, which is what a measured row
                # is set against and what the INK bounds above cannot give: a
                # row's ink top sits above its cap line by whatever ascender the
                # string happens to carry, and every row carries a different one.
                "cap_top_z": (t.location.z - _cap_drop(t.data.font) * t.data.size
                              if t.data.font else None),
                # The cap height actually built, after any width fit. `size` is
                # not this and the two are not related by a documented constant
                # -- see _cap_ratio -- so a consumer that converts one to the
                # other has to re-measure the font to do it.
                "cap_h": (_cap_ratio(t.data.font) * t.data.size
                          if t.data.font else None),
                # How far the glyphs were narrowed to fit the measured box.
                # 1.0 means they were not; CONDENSE_FLOOR means the width ran
                # out and the size gave way after it.
                "scale_x": t.scale.x,
                # The ink. A row set inside a colour block reverses out of it,
                # and a test cannot see that from geometry alone.
                "base_color": _base_color(t),
            }
            # Front-panel rows only. The side panel's text is reported
            # separately, under "side_panel".
            for t in sorted((o for o in bpy.data.objects
                             if o.type == "FONT" and o.name.startswith("label_")),
                            key=lambda o: -o.location.z)
        ]
        out["reference_aux_text"] = [
            {
                "name": obj.name,
                "body": obj.data.body,
                "surface": str(obj.get("reference_aux_surface")),
                "font": obj.data.font.name if obj.data.font else None,
                "bounds_in_carton_frame": _bounds_in_frame(obj, box),
            }
            for obj in sorted(
                (item for item in bpy.data.objects
                 if item.type == "FONT"
                 and item.name.startswith("reference_aux_")),
                key=lambda item: item.name)
        ]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"[render_driver] dumped scene geometry to {path}")


def main():
    if JOB.get('physical_baseline'):
        # Explicit photograph-free branch, compiled by the existing manifest
        # owner. The adapters receive bpy; no second Blender entry point exists.
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from src.carton_scene import run_physical
        views = _arg('--physical-views')
        try:
            run_physical(bpy, JOB, OUT_PATH or DUMP_SCENE, DUMP_SCENE, SAVE_BLEND,
                         views.split(',') if views else None)
        except Exception:
            import traceback
            traceback.print_exc()
            raise
        return
    clear_scene()

    palette = JOB.get("palette", {}) or {}
    template_id = JOB.get("template_id", "T1")

    # Carton dimensions are guaranteed by the manifest contract, which resolves
    # them (and records their provenance) before anything reaches Blender. There
    # is deliberately no aspect-ratio guess here any more: the fallback table
    # lives once, in src/render_manifest.py. A missing carton means the job was
    # not built through the contract, and rendering a silently wrong size is
    # worse than stopping.
    carton = JOB.get("carton")
    if not carton:
        raise SystemExit(
            "[render_driver] job has no 'carton' block — it was not produced by "
            "src/render_manifest.py. Regenerate it via Stage 1 or "
            "src.blender_renderer, which validate against "
            "schemas/render_manifest.schema.json."
        )

    # Resolved before the branch: the .blend override brings its own scene but is
    # still metered for this carton's shape, and the backdrop needs the same
    # figure to render at full scale.
    dims_m = (float(carton["width_mm"]) / 1000.0,
              float(carton["height_mm"]) / 1000.0,
              float(carton["depth_mm"]) / 1000.0)
    exposure = film_exposure(dims_m)

    # Optional Phase-2 hand-authored .blend override (loaded instead of the
    # procedural build below, if the loader finds a matching file).
    scenes_dir = Path(_arg("--scenes-dir", "")) if _arg("--scenes-dir") else None
    blend_override = (scenes_dir / f"{template_id}.blend") if scenes_dir else None
    if blend_override and blend_override.exists():
        bpy.ops.wm.open_mainfile(filepath=str(blend_override))
        # A hand-authored scene is expected to already own camera/lights/materials;
        # only the render settings are still applied below.
    else:
        print(f"[render_driver] carton {carton['width_mm']}x{carton['height_mm']}"
              f"x{carton['depth_mm']}mm (source: {carton.get('source', 'unknown')}) "
              f"exposure {exposure:+.2f}")

        box, target_size = build_box(dims_m, palette, JOB.get("label_content"), JOB)
        build_background(
            palette.get("background", "#FFFFFF"), exposure, target_size)
        setup_camera(dims_m)
        setup_lighting(target_size)

    # Applied to the hand-authored .blend branch as well: a scene loaded from
    # disk brings its own camera, lights and materials, but exposure is a
    # project-wide invariant, and applied BEFORE the --dump-scene return so the
    # measurement path sees exactly what the render path will.
    setup_film(exposure)

    if DUMP_SCENE:
        dump_scene(DUMP_SCENE)
        return

    setup_render(OUT_PATH, ENGINE, SAMPLES, RES_X, RES_Y)
    if SAVE_BLEND:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(SAVE_BLEND).resolve()))

    # Sidecar for post-render QA. Written before the render so it exists even if
    # rendering later fails, and the pixels are unaffected either way.
    if not BLANK_CARTON:
        view_path = Path(OUT_PATH).with_suffix(".view.json")
        view_path.write_text(json.dumps(printed_faces_px(), indent=2), encoding="utf-8")
        print(f"[render_driver] wrote {view_path}")

    bpy.ops.render.render(write_still=True)
    save_diagnostic_passes()
    print(f"[render_driver] wrote {OUT_PATH}")


try:
    main()
except Exception as exc:
    # Blender reports ordinary script exceptions with process exit 0. Stage 2
    # must receive a failure for scene, sidecar and render errors (INV-004).
    raise SystemExit(
        f"[render_driver] fatal {type(exc).__name__}: {exc}") from exc
