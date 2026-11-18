"""Where the carton lands in frame, computed from geometry rather than measured.

Why this exists
---------------
Until now the only answer to "how much of the frame does the carton fill" came
from measuring pixels in a rendered image. That is exactly the measurement a
white carton on a 255 backdrop defeats: the brightly lit top face blends into
the background, so a landscape carton reads shorter than it is. Every landscape
row of the measured table in ``00_PROJECT_STATE/CURRENT_STATE.md`` is 5-9 points
low on height for that reason -- for the modal ``115x55x48`` carton it records
74/48 where the geometry says 76/57.

The carton is a box and the camera is deterministic, so the silhouette does not
have to be guessed at all. This module projects all eight corners through the
same camera ``05_assets/blender/render_driver.py`` builds and returns the
bounding box of the result.

It is checked, not asserted. The driver projects the carton's printed faces
itself and writes them beside each render as ``{stem}.view.json``;
``tests/test_silhouette.py`` requires this module to reproduce those pixels to
within a rounding error. If it ever stops doing so, the model is wrong and the
test says which corner.

The camera constants
--------------------
They are duplicated from the driver, because ``render_driver.py`` cannot be
imported outside Blender -- it does ``import bpy`` at module scope, and Blender's
bundled interpreter is the only place that resolves. Duplication without a check
is how two sources of truth begin to disagree, so the test reads the driver as
text and fails the moment a value parts company with its copy here.

One trap is worth naming. ``src/render_manifest.py`` also defines a
``VERTICAL_FAMILY``, and it is a *different set*: it includes ``T_BOTTLE_BOX``
because that carton stands upright, and it governs which edge is stood up. The
set below governs which CAMERA is used, and the driver excludes ``T_BOTTLE_BOX``
from it. Using the orientation set here would shoot that template with the wrong
pitch and rotation, and nothing downstream would notice.
"""
from __future__ import annotations

import math

# ── Camera, mirrored from 05_assets/blender/render_driver.py ────────────────
LENS_MM = 85.0
SENSOR_MM = 36.0
SPHERE_FILL = 0.8365

# (pitch_deg, rotation_deg)
CAMERA_VERTICAL = (20.0, 27.5)
CAMERA_DEFAULT = (25.0, 35.0)

# Which templates take the vertical camera. NOT the manifest's orientation
# family -- see the module docstring.
CAMERA_VERTICAL_TEMPLATES = {"T_VERT_VIAL", "T_VERT_DROPPER", "T_VERT_INHALER"}

DEFAULT_RESOLUTION = (2048, 2048)


def camera_for(template_id: str) -> tuple[float, float]:
    """(pitch_deg, rotation_deg) for a template, as the driver would choose."""
    return (CAMERA_VERTICAL if template_id in CAMERA_VERTICAL_TEMPLATES
            else CAMERA_DEFAULT)


def _projector(dims_mm, template_id, resolution):
    """A function mapping a local carton corner to image pixels.

    The carton spans x in [-w/2, w/2], y in [-d/2, d/2], z in [0, h] locally,
    is rotated about Z, and is framed by solving the camera distance from the
    bounding sphere -- which is why absolute size cancels out entirely.
    """
    w, h, d = (float(v) for v in dims_mm)
    res_x, res_y = resolution
    pitch_deg, rot_deg = camera_for(template_id)
    pitch, rot = math.radians(pitch_deg), math.radians(rot_deg)

    half_fov = math.atan((SENSOR_MM / 2.0) / LENS_MM)
    tan_half = math.tan(half_fov)
    radius = 0.5 * math.sqrt(w * w + h * h + d * d)
    distance = radius / math.sin(SPHERE_FILL * half_fov)

    # Camera at the driver's position, rotated (90deg - pitch) about X: it looks
    # along +Y and downward.
    cam = (0.0, -distance * math.cos(pitch), h / 2.0 + distance * math.sin(pitch))
    right = (1.0, 0.0, 0.0)
    up = (0.0, math.sin(pitch), math.cos(pitch))
    forward = (0.0, math.cos(pitch), -math.sin(pitch))

    def project(local):
        lx, ly, lz = local
        wx = lx * math.cos(rot) - ly * math.sin(rot)
        wy = lx * math.sin(rot) + ly * math.cos(rot)
        v = (wx - cam[0], wy - cam[1], lz - cam[2])
        x_cam = sum(a * b for a, b in zip(v, right))
        y_cam = sum(a * b for a, b in zip(v, up))
        z_cam = sum(a * b for a, b in zip(v, forward))
        ndc_x = x_cam / (z_cam * tan_half)
        ndc_y = y_cam / (z_cam * tan_half)
        # NDC runs -1..1 with y up; image pixels count from the top-left, y down.
        return [(ndc_x + 1.0) / 2.0 * res_x, (1.0 - (ndc_y + 1.0) / 2.0) * res_y]

    return project, (w, h, d)


def _order_quad(pairs):
    """[top-left, top-right, bottom-right, bottom-left], the driver's order.

    Split by LOCAL Z, not by projected y, for the reason ``_order_quad`` in the
    driver documents: on a wide shallow face the far vertical edge can project
    entirely above the near one, and sorting the pixels then pairs two corners
    of the same edge together and emits a self-intersecting quad.
    """
    by_z = sorted(pairs, key=lambda pair: pair[0][2])
    bottom = sorted((px for _, px in by_z[:2]), key=lambda p: p[0])
    top = sorted((px for _, px in by_z[2:]), key=lambda p: p[0])
    return [top[0], top[1], bottom[1], bottom[0]]


def _face(dims_mm, template_id, resolution, axis, take_min):
    project, (w, h, d) = _projector(dims_mm, template_id, resolution)
    extent = {0: w / 2.0, 1: d / 2.0}[axis]
    fixed = -extent if take_min else extent
    corners = []
    for other in (-{0: d, 1: w}[axis] / 2.0, {0: d, 1: w}[axis] / 2.0):
        for z in (0.0, h):
            local = (fixed, other, z) if axis == 0 else (other, fixed, z)
            corners.append((local, project(local)))
    return _order_quad(corners)


def front_face_px(dims_mm, template_id, resolution=DEFAULT_RESOLUTION):
    """The printed front face -- local -Y -- in image pixels, TL TR BR BL."""
    return _face(dims_mm, template_id, resolution, axis=1, take_min=True)


def side_panel_px(dims_mm, template_id, resolution=DEFAULT_RESOLUTION):
    """The visible side panel -- local -X -- in image pixels, TL TR BR BL."""
    return _face(dims_mm, template_id, resolution, axis=0, take_min=True)


def silhouette_px(dims_mm, template_id, resolution=DEFAULT_RESOLUTION):
    """(min_x, min_y, max_x, max_y) of the whole carton, in image pixels."""
    project, (w, h, d) = _projector(dims_mm, template_id, resolution)
    xs, ys = [], []
    for lx in (-w / 2.0, w / 2.0):
        for ly in (-d / 2.0, d / 2.0):
            for lz in (0.0, h):
                px, py = project((lx, ly, lz))
                xs.append(px)
                ys.append(py)
    return min(xs), min(ys), max(xs), max(ys)


def frame_fill(dims_mm, template_id, resolution=DEFAULT_RESOLUTION):
    """(width, height) of the silhouette as a percentage of the frame.

    Directly comparable with the numbers measured off the reference renders,
    and unlike them it cannot lose a face to the backdrop.
    """
    res_x, res_y = resolution
    x0, y0, x1, y1 = silhouette_px(dims_mm, template_id, resolution)
    return 100.0 * (x1 - x0) / res_x, 100.0 * (y1 - y0) / res_y


def silhouette_aspect(dims_mm, template_id, resolution=DEFAULT_RESOLUTION):
    """Silhouette width divided by its height. The art-direction target."""
    w_pct, h_pct = frame_fill(dims_mm, template_id, resolution)
    return w_pct / h_pct


# ── The same quantity, measured off pixels ──────────────────────────────────
#
# Needed for the nine curated references, which carry no dimensions: there is no
# model to project, so the only way to learn their proportion is to look. It is
# NOT the way to learn ours -- for our own renders the model above is exact and
# this is the inferior instrument. Both live here so their disagreement is
# testable rather than theoretical.
#
# Two facts about these images decide the method, both measured 2026-08-09 over
# the 40 current-era renders in 02_processing/blender_test_renders.
#
# The backdrop is not flat. It means 254.96 with sd 0.32, but Cycles noise takes
# individual pixels down to 244.7 -- darker than anything a threshold could
# exclude without also discarding the carton. A bounding box built from the
# extreme subject pixels therefore spans the entire frame: 7 stray pixels on the
# border are enough. Eroding the mask by one pixel removes them, because noise
# is not connected to anything and the carton is. Skipping the erosion is not a
# small error, it is a total one.
#
# The top face cannot be separated from the backdrop AT ALL. Measured across the
# carton's own top rows it reads 254.7-254.9 against a backdrop of 254.96 -- the
# same value, not a close one. That is the light rig working as designed: a
# white board under near-shadowless high-key lighting in front of a 255 backdrop
# has no upper edge in pixels. No threshold exists that keeps it, and raising the
# threshold only makes the measurement catch the top face on cartons whose
# geometry gives it a gradient while still missing it on cartons where it is
# flat. That is why the residual against the model is structured by template
# rather than random.
#
# The nine references do NOT have this problem, and that asymmetry is the whole
# reason the instrument is usable. Their topmost band reads 225-243 -- a real
# drawn edge -- and moving the threshold from 250 to 252 shifts their top row by
# 0 or 1 pixel. Gemini shades the top face; our rig deliberately does not.
#
# So the same call returns two different quantities depending on the subject:
#
#   * on a reference, the FULL silhouette, top face included;
#   * on one of our renders, only the VERTICAL faces, because the top has no
#     pixels to find.
#
# Which makes one comparison legitimate and one worthless. Reference measurement
# against ``silhouette_px`` is like for like. Reference measurement against a
# pixel measurement of our own render is not -- it would read our lighting as a
# proportion difference and report roughly 14% of shape that is not there.
#
# What the numbers are, at threshold 250 with one-pixel erosion, measured
# 2026-08-09:
#
#   * our renders against ``visible_faces_px``, which is what they actually
#     show: aspect error +1.3% mean, sd 2.9, worst 10.0%;
#   * the same renders against ``silhouette_px``: +14.1% mean -- the missing top
#     face, not an error in either the model or this code;
#   * across thresholds 248-253 on the nine references: 0.6-3.6%, except
#     T_VERT_DROPPER at 7.6%.
#
# So MEASURE_UNCERTAINTY_PCT below is not a safety margin someone chose. It is
# what the instrument does. A difference smaller than it is not evidence of
# anything, and tuning geometry to close such a gap is tuning noise.
MEASURE_THRESHOLD = 250.0
MEASURE_ERODE_R = 1
MEASURE_UNCERTAINTY_PCT = 4.0


def visible_faces_px(dims_mm, template_id, resolution=DEFAULT_RESOLUTION):
    """(min_x, min_y, max_x, max_y) of the carton's VERTICAL faces only.

    What a high-key photograph of a white carton on a white backdrop can show:
    the front face and the side panel, and nothing of the top. Narrower than
    ``silhouette_px``, and the quantity a pixel measurement of one of our own
    renders is actually returning.
    """
    corners = (list(front_face_px(dims_mm, template_id, resolution))
               + list(side_panel_px(dims_mm, template_id, resolution)))
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return min(xs), min(ys), max(xs), max(ys)


def front_face_aspect(dims_mm, template_id, resolution=DEFAULT_RESOLUTION):
    """Apparent proportion of the printed front face: width over height.

    The quantity to art-direct on, because it is a CONTINUOUS function of the
    geometry. A silhouette bounding box is not: whether the carton's far top edge
    clears a brightness threshold flips with shape, and the measured box gains a
    whole face at once. Rendering 1-min at five heights put T1's silhouette
    target inside that jump, where no carton reaches it -- see
    01_input_raster/reference_analysis.md section 11.

    The face is a rectangle in 3D and a quadrilateral once projected, so its two
    horizontal edges differ in length and so do its vertical ones. Averaging each
    pair keeps the answer smooth; taking a bounding box instead would reintroduce
    a corner-dependent kink.
    """
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = front_face_px(dims_mm, template_id,
                                                           resolution)
    top = math.hypot(x1 - x0, y1 - y0)
    bottom = math.hypot(x2 - x3, y2 - y3)
    left = math.hypot(x3 - x0, y3 - y0)
    right = math.hypot(x2 - x1, y2 - y1)
    return (0.5 * (top + bottom)) / (0.5 * (left + right))


def visible_faces_aspect(dims_mm, template_id, resolution=DEFAULT_RESOLUTION):
    """Width over height of the vertical faces. What our render appears to be.

    This, not ``silhouette_aspect``, is the number to compare a reference
    measurement against: a reference shows its top face and ours does not, so
    matching apparent shape to apparent shape means matching the reference's
    full silhouette to our visible one. Comparing against the full model instead
    understates our width by 13-14% on the landscape templates and reports
    cartons as already matching when they are not.
    """
    x0, y0, x1, y1 = visible_faces_px(dims_mm, template_id, resolution)
    return (x1 - x0) / (y1 - y0)


def _erode(mask, r):
    """Binary erosion by a (2r+1) square. Kept local: no scipy in requirements."""
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view

    k = 2 * r + 1
    out = np.zeros_like(mask)
    core = sliding_window_view(mask, (k, k)).all(axis=(2, 3))
    out[r:r + core.shape[0], r:r + core.shape[1]] = core
    return out


def measured_silhouette_px(image_path, threshold=MEASURE_THRESHOLD,
                           erode_r=MEASURE_ERODE_R,
                           object_mask_path=None):
    """(min_x, min_y, max_x, max_y) of the carton, read off the pixels.

    Comparable with ``silhouette_px`` only within ``MEASURE_UNCERTAINTY_PCT`` --
    see the note above for why, and for why that is a property of the subject
    rather than of this code.
    """
    import numpy as np
    from PIL import Image

    grey = np.asarray(Image.open(image_path).convert("RGB")).astype(float).mean(axis=2)
    if object_mask_path is not None:
        mask = np.asarray(Image.open(object_mask_path).convert("L")) > 127
        if mask.shape != grey.shape:
            raise ValueError(
                "object mask dimensions do not match the rendered image: "
                f"{mask.shape} != {grey.shape}")
        restore = 0
    else:
        # Reference photographs have no scene-derived mask and deliberately
        # retain the measured luminance path documented above.
        mask = grey < threshold
        if erode_r:
            mask = _erode(mask, erode_r)
        restore = erode_r
    if not mask.any():
        source = (f"object mask {object_mask_path}" if object_mask_path is not None
                  else f"pixels darker than {threshold} after erosion")
        raise AssertionError(
            f"no carton found from {source}: either the frame is empty or the "
            "measurement input is invalid")
    ys, xs = np.nonzero(mask)
    return (float(xs.min() - restore), float(ys.min() - restore),
            float(xs.max() + restore), float(ys.max() + restore))


def measured_silhouette_aspect(image_path, threshold=MEASURE_THRESHOLD,
                               erode_r=MEASURE_ERODE_R,
                               object_mask_path=None):
    """Measured silhouette width divided by its height."""
    x0, y0, x1, y1 = measured_silhouette_px(
        image_path, threshold, erode_r, object_mask_path)
    return (x1 - x0) / (y1 - y0)
