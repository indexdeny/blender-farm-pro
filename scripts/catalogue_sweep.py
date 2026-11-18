"""Render a named group of SKU and measure every resulting packshot.

Diagnostic only: this script never changes how anything is rendered. It exists
because the driver's layout constants were fitted against nine curated
references, and a sweep over many real SKU is the only thing that finds the
failures those nine cannot show. Every correction pass currently in
05_assets/blender/render_driver.py was added after a sweep found real breakage.

    python scripts/catalogue_sweep.py --limit 5           # trial
    python scripts/catalogue_sweep.py                     # the group, resuming
    python scripts/catalogue_sweep.py --force             # re-render the group
    python scripts/catalogue_sweep.py --group catalogue   # every SKU on disk

Writes one record per SKU as JSON plus a human summary in 00_PROJECT_STATE/,
rewritten on every run including after Ctrl+C, so a long run is never lost. The
filenames are keyed by what the run actually covered: only a whole `catalogue`
run may occupy the canonical sweep_report.* — see report_paths().
"""
from __future__ import annotations

import sys
import json
import time
import hashlib
import argparse
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import load_config, get_path, resolve_path  # noqa: E402

# ── The group ────────────────────────────────────────────────────────────────
# Resolved once, by hand, from product_name in the passports. Kept as data so
# the group can be changed without touching any logic below.
#
# Two traps this mapping already resolves, and which re-deriving it would
# reintroduce: "Xanax (Alprazolam)" and "Xanax (Alprazolam) by Pfizer" are
# DIFFERENT SKU (156-min and 340-min), and most names carry the active
# ingredient in brackets while product_name does not.
GROUPS = {
    "top30": [
        ("2-min",   "Strattera (Atomoxetine)"),
        ("59-min",  "Cialis (Tadalafil)"),
        ("60-min",  "Cialis Professional"),
        ("62-min",  "Cialis Super Active"),
        ("107-min", "Tramadol"),
        ("133-min", "Ambien (Zolpidem)"),
        ("134-min", "Atarax (Hydroxyzine)"),
        ("135-min", "Ativan (Lorazepam)"),
        ("139-min", "Lyrica (Pregabalin)"),
        ("149-min", "Modalert (Modafinil)"),
        ("150-min", "Waklert (Armodafinil)"),
        ("151-min", "Provigil (Modafinil)"),
        ("152-min", "Artvigil (Armodafinil)"),
        ("155-min", "Imovane (Zopiclone)"),
        ("156-min", "Xanax (Alprazolam)"),
        ("157-min", "Valium (Diazepam)"),
        ("158-min", "Klonopin (Clonazepam)"),
        ("221-min", "Inderal (Propranolol)"),
        ("230-min", "Slimex"),
        ("258-min", "Stromectol (Ivermectin)"),
        ("272-min", "Valium Brand"),
        ("304-min", "Sonata (Zaleplon)"),
        ("308-min", "Lexotanil (Bromazepam)"),
        ("340-min", "Xanax (Alprazolam) by Pfizer"),
        ("344-min", "Modafinil"),
        ("346-min", "Modvigil"),
        ("357-min", "Adderall"),
        ("362-min", "Hydrocodone"),
        ("365-min", "Tapentadol"),
        ("404-min", "Ritalin (Generic)"),
    ],
    # `top30` is a commercial selection and turns out to be all T1 and T1_SMALL:
    # it never renders the other SEVEN templates, so any layout failure specific
    # to a flat T3 or a vial carton is invisible to it. This group exists to
    # cover shape rather than sales, two SKU per template, and within each
    # template it takes the two whose front-face proportion the 2026-08-09
    # reshape moved MOST -- those are where a grid fitted to the old proportions
    # is likeliest to break. The percentages are that movement, measured.
    "families": [
        ("99-min",  "T1               +22%"),
        ("98-min",  "T1               +22%"),
        ("422-min", "T1_LARGE         +36%"),
        ("420-min", "T1_LARGE         +36%"),
        ("337-min", "T1_SMALL         +22%"),
        ("79-min",  "T1_SMALL         +22%"),
        ("76-min",  "T3               +58%"),
        ("65-min",  "T3               +58%"),
        ("412-min", "T_BOTTLE_BOX     +44%"),
        ("411-min", "T_BOTTLE_BOX     +44%"),
        ("351-min", "T_MULTIPACK       +0%"),
        ("350-min", "T_MULTIPACK       +0%"),
        ("379-min", "T_VERT_DROPPER   +80%"),
        ("229-min", "T_VERT_DROPPER   +80%"),
        ("393-min", "T_VERT_INHALER   +90%"),
        ("316-min", "T_VERT_INHALER   +90%"),
        ("416-min", "T_VERT_VIAL     +115%"),
        ("415-min", "T_VERT_VIAL     +115%"),
    ],
}

# The whole catalogue, generated rather than curated. 391 hand-written rows
# would be a second copy of the passport directory, kept in sync by hand; and
# the label the curated groups carry is only stored as the record's
# `requested_as` — record_for() reads product_name off the passport itself.
CATALOGUE = "catalogue"


def _stem_order(stem: str):
    """The project's stem sort: numeric prefix first, `10-min` after `9-min`."""
    head = stem.split("-")[0]
    return (int(head) if head.isdigit() else 999999, stem)


def group_members(name: str) -> list[tuple[str, str]]:
    """The (stem, label) pairs a group covers."""
    if name == CATALOGUE:
        return [(f.stem, CATALOGUE) for f in
                sorted(PASSPORT_DIR.glob("*.json"), key=lambda f: _stem_order(f.stem))]
    return list(GROUPS[name])


def group_names() -> list[str]:
    return sorted([*GROUPS, CATALOGUE])

# ── Thresholds a SKU is flagged against ──────────────────────────────────────
BLANK_FRAC = 5.0          # object smaller than this share of frame -> nothing rendered
OVERSIZE_FRAC = 95.0      # larger than this -> effectively filling the frame
SLOW_RENDER_S = 180.0
SPREAD_TOLERANCE_PP = 10.0  # deviation from the template's median frame fill

# Front-face brightness. Worth flagging rather than merely recording: this
# catches a carton lit visibly darker than the rig intends, which is what the
# light_energy square law exists to prevent and which no geometry check can see.
# The sweep's band is deliberately looser than src.measure's reference band —
# the vertical family measures 232.6-234.2 under the current rig, just below the
# reference floor, and that is a known rig gap rather than a per-SKU defect.
FRONT_FACE_MIN, FRONT_FACE_MAX = 230.0, 245.0

# Legacy object-versus-backdrop threshold. New sweep renders always request the
# driver's independent object mask, because contact shadow is intentionally
# darker than the backdrop and must not enlarge the carton. The threshold stays
# only for explicitly reused pre-mask artifacts and reference-style fixtures.
SILHOUETTE_MAX_LUMA = 243

_CFG = load_config()
OUT_DIR = resolve_path(_CFG["blender"]["output_dir"])
MANIFEST_DIR = get_path(_CFG, "passports_manifests")
PASSPORT_DIR = get_path(_CFG, "passports_json")
BLENDER_EXE = Path(_CFG["blender"]["executable"])
STATE_DIR = PROJECT_ROOT / "00_PROJECT_STATE"

# Resolved once per run, not per SKU: the driver must not appear to change
# halfway through a three-hour sweep just because someone saved the file.
_FINGERPRINT: dict | None = None


# ── Measurement ──────────────────────────────────────────────────────────────
def measure(png_path: Path, manifest_path: Path,
            object_mask_path: Path | None = None) -> dict:
    """Geometry and brightness of one rendered packshot.

    Front-face brightness comes from src.measure, shared with the calibration
    gate in tests/test_blender_carton.py so a measurement whose band was fitted
    off the references has exactly one implementation.
    """
    import numpy as np
    from PIL import Image

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    grey = np.asarray(Image.open(png_path).convert("L")).astype(float)
    height, width = grey.shape

    try:
        from src.silhouette import measured_silhouette_px
        left, top, right, bottom = measured_silhouette_px(
            png_path, threshold=SILHOUETTE_MAX_LUMA, erode_r=0,
            object_mask_path=object_mask_path)
    except AssertionError:
        return {"measured": False, "reason": "no object found against the backdrop"}
    top, bottom = int(top), int(bottom)
    left, right = int(left), int(right)
    frac_w = 100.0 * (right - left + 1) / width
    frac_h = 100.0 * (bottom - top + 1) / height
    margins = {"top": top, "bottom": height - 1 - bottom,
               "left": left, "right": width - 1 - right}

    result = {
        "measured": True,
        "silhouette_source": ("object_mask" if object_mask_path is not None
                              else "luminance"),
        "resolution": [width, height],
        "frame_fill_width_pct": round(frac_w, 1),
        "frame_fill_height_pct": round(frac_h, 1),
        "frame_fill_dominant_pct": round(max(frac_w, frac_h), 1),
        "margins_px": margins,
        "cropped": min(margins.values()) == 0,
        "blank": max(frac_w, frac_h) < BLANK_FRAC,
        "oversize": max(frac_w, frac_h) > OVERSIZE_FRAC,
    }

    try:
        from src.measure import _front_face_and_background
        front, backdrop, backdrop_sd = _front_face_and_background(
            str(png_path), manifest["palette"]["accent"])
        result["front_face_mean"] = round(float(front), 1)
        result["backdrop_mean"] = round(float(backdrop), 1)
        result["backdrop_sd"] = round(float(backdrop_sd), 2)
    except Exception as e:  # noqa: BLE001 - a brightness miss must not lose the geometry
        result["front_face_mean"] = None
        result["brightness_error"] = f"{type(e).__name__}: {e}"

    return result


# ── Scene-level layout check ─────────────────────────────────────────────────
# The silhouette metrics above cannot see a text defect: a label row that
# overruns the face edge or collides with the row below leaves the outline of
# the box unchanged. This check reads the built scene instead of the pixels,
# through the driver's own --dump-scene, which is how tests/test_blender_carton.py
# already asserts on layout. It renders nothing and changes nothing.
DUMP_TIMEOUT_S = 120
ROW_MIN_GAP_MM = 0.0     # stacked rows must not overlap at all

# The driver fits a long row by SHRINKING it, never by letting it overrun, so an
# overflow defect cannot occur — but nothing puts a floor under the type size.
# Measured on 357-min: a 37-character ingredient sets at 4.64mm cap height, 70
# characters at 1.73mm, 140 at 0.77mm, with the row's width pinned at 101.2mm
# throughout. The references set their small print at 4.4-5.5mm
# (reference_analysis.md §6), so anything much under that is legible in the data
# and not on the carton.
SMALL_PRINT_MIN_MM = 4.0
FITTED_ROWS = {"label_ingredient", "label_dosage", "label_unit_count"}

# The dosage and the unit count deliberately share one baseline at the bottom of
# the face, left- and right-aligned. They overlap in Z by design, so they are
# never compared against each other as "stacked".
SAME_BASELINE = {"label_dosage", "label_unit_count"}


def check_scene(stem: str) -> dict:
    """Label geometry for one SKU, measured off the built scene."""
    import tempfile
    manifest = MANIFEST_DIR / f"{stem}.json"
    with tempfile.TemporaryDirectory() as tmp:
        dump = Path(tmp) / "scene.json"
        try:
            subprocess.run(
                [str(BLENDER_EXE), "--background", "--factory-startup",
                 "--python", str(resolve_path(_CFG["blender"]["driver_script"])), "--",
                 "--job", str(manifest), "--dump-scene", str(dump)],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=DUMP_TIMEOUT_S,
            )
        except Exception as e:  # noqa: BLE001
            return {"checked": False, "reason": f"{type(e).__name__}: {e}"}
        if not dump.exists():
            return {"checked": False, "reason": "driver wrote no scene dump"}
        scene = json.loads(dump.read_text(encoding="utf-8"))

    m = json.loads(manifest.read_text(encoding="utf-8"))
    half_w = m["carton"]["width_mm"] / 2000.0     # metres, face spans -half_w..+half_w
    half_h = m["carton"]["height_mm"] / 2000.0

    rows = []
    for o in scene.get("label", []):
        b = o.get("bounds_in_carton_frame")
        if b:
            rows.append({"name": o.get("name", "?"), "body": o.get("body", ""),
                         "x0": b["min"][0], "x1": b["max"][0],
                         "z0": b["min"][2], "z1": b["max"][2]})

    issues = []
    for r in rows:
        if r["x1"] > half_w + 1e-6:
            issues.append(f"{r['name']} overruns the right edge by "
                          f"{(r['x1'] - half_w) * 1000:.2f}mm")
        if r["x0"] < -half_w - 1e-6:
            issues.append(f"{r['name']} overruns the left edge by "
                          f"{(-half_w - r['x0']) * 1000:.2f}mm")
        if r["z1"] > 2 * half_h + 1e-6 or r["z0"] < -1e-6:
            issues.append(f"{r['name']} runs off the face vertically")

    stacked = sorted(rows, key=lambda r: -r["z1"])
    for a, b in zip(stacked, stacked[1:]):
        if {a["name"], b["name"]} == SAME_BASELINE:
            continue
        gap = (a["z0"] - b["z1"]) * 1000
        if gap < ROW_MIN_GAP_MM:
            issues.append(f"{a['name']} and {b['name']} overlap by {-gap:.2f}mm")

    smallest = None
    for r in rows:
        if r["name"] not in FITTED_ROWS:
            continue
        mm = (r["z1"] - r["z0"]) * 1000
        smallest = mm if smallest is None else min(smallest, mm)
        if mm < SMALL_PRINT_MIN_MM:
            issues.append(f"{r['name']} set at {mm:.2f}mm, under the "
                          f"{SMALL_PRINT_MIN_MM:.1f}mm the references hold small "
                          f"print to ({len(r['body'])} characters)")

    return {"checked": True, "row_count": len(rows), "issues": issues,
            "smallest_fitted_row_mm": round(smallest, 2) if smallest else None,
            "rows": [{"name": r["name"],
                      "x_mm": [round(r["x0"] * 1000, 2), round(r["x1"] * 1000, 2)],
                      "z_mm": [round(r["z0"] * 1000, 2), round(r["z1"] * 1000, 2)],
                      "body": r["body"]} for r in rows]}


# ── Rendering ────────────────────────────────────────────────────────────────
def render_command(stem: str) -> list[str]:
    """One diagnostic render with beauty and independent derived masks."""
    blender = _CFG["blender"]
    resolution = blender.get("resolution", [2048, 2048])
    return [
        str(BLENDER_EXE), "--background", "--factory-startup",
        "--python", str(resolve_path(blender["driver_script"])), "--",
        "--job", str(MANIFEST_DIR / f"{stem}.json"),
        "--out", str(OUT_DIR / f"{stem}.png"),
        "--object-mask", str(OUT_DIR / f"{stem}.object.png"),
        "--shadow-mask", str(OUT_DIR / f"{stem}.shadow.png"),
        "--engine-type", blender.get("engine_type", "CYCLES"),
        "--samples", str(blender.get("samples", 16)),
        "--res-x", str(resolution[0]), "--res-y", str(resolution[1]),
        "--device", blender.get("device", "CPU"),
    ]


def render_one(stem: str) -> tuple[bool, float, str]:
    """Render one canonical manifest and its masks in the same Blender run."""
    start = time.time()
    try:
        proc = subprocess.run(
            render_command(stem),
            cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            stdin=subprocess.DEVNULL,
            timeout=_CFG["blender"].get("render_timeout", 300),
        )
    except subprocess.TimeoutExpired:
        return False, time.time() - start, "renderer timed out after 600s"
    except Exception as e:  # noqa: BLE001
        return False, time.time() - start, f"{type(e).__name__}: {e}"

    elapsed = time.time() - start
    required = [OUT_DIR / f"{stem}.png", OUT_DIR / f"{stem}.object.png",
                OUT_DIR / f"{stem}.shadow.png"]
    if proc.returncode != 0 or not all(path.exists() for path in required):
        tail = (proc.stderr or proc.stdout or "")[-400:]
        missing = [path.name for path in required if not path.exists()]
        return False, elapsed, (f"render incomplete (rc={proc.returncode}, "
                                f"missing={missing}): {tail}")
    return True, elapsed, ""


def record_for(stem: str, label: str, rendered: bool, seconds, error: str) -> dict:
    manifest_path = MANIFEST_DIR / f"{stem}.json"
    rec = {"stem": stem, "requested_as": label, "rendered": rendered,
           "render_seconds": round(seconds, 1) if seconds is not None else None,
           "error": error or None}

    if manifest_path.exists():
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        rec.update({"sku_id": m["sku_id"], "template_id": m["template_id"],
                    "carton_mm": [m["carton"]["width_mm"], m["carton"]["height_mm"],
                                  m["carton"]["depth_mm"]],
                    "carton_source": m["carton"]["source"]})
        passport = PASSPORT_DIR / f"{stem}.json"
        if passport.exists():
            rec["product_name"] = json.loads(
                passport.read_text(encoding="utf-8")).get("product_name")
    else:
        rec["manifest_missing"] = True

    png = OUT_DIR / f"{stem}.png"
    if png.exists():
        # One-directional and therefore safe to act on: a PNG older than the
        # driver CANNOT have been drawn by it. The converse is not claimed --
        # a driver merely re-saved would mark fresh renders stale, which is a
        # warning to re-render, not a wrong measurement.
        # Still recorded, though sweep() now re-renders rather than reporting it:
        # record_for is also reached by a measure-only path, and a report that
        # cannot say "this row is about older code" is the original defect.
        if is_stale(png):
            rec["render_predates_driver"] = True
        try:
            mask = OUT_DIR / f"{stem}.object.png"
            rec["measurement"] = measure(
                png, manifest_path,
                object_mask_path=mask if mask.exists() else None)
        except Exception as e:  # noqa: BLE001 - a corrupt PNG is a finding, not a crash
            rec["measurement"] = {"measured": False,
                                  "reason": f"{type(e).__name__}: {e}"}
            rec["rendered"] = False
            rec["error"] = rec["error"] or "PNG unreadable"

    if manifest_path.exists():
        rec["layout"] = check_scene(stem)
    return rec


def problems_for(rec: dict) -> list[str]:
    """Which thresholds this SKU violates. Empty means clean."""
    out = []
    if not rec.get("rendered"):
        out.append("render failed")
    # First, because everything below it is a measurement of the wrong artifact.
    if rec.get("render_predates_driver"):
        out.append("PNG older than the driver — measured, but not of this code; "
                   "re-render with --force")
    m = rec.get("measurement") or {}
    if m.get("measured"):
        if m["cropped"]:
            out.append("cropped at frame edge")
        if m["blank"]:
            out.append(f"blank frame (<{BLANK_FRAC}%)")
        if m["oversize"]:
            out.append(f"fills frame (>{OVERSIZE_FRAC}%)")
        front = m.get("front_face_mean")
        if front is None:
            # Never let a dropped measurement read as a pass. Without this the
            # brightness pass could fail for all 30 SKU and the summary would
            # still print "flagged: 0".
            out.append(f"front-face brightness not measured: "
                       f"{m.get('brightness_error', 'unknown')}")
        elif not (FRONT_FACE_MIN <= front <= FRONT_FACE_MAX):
            out.append(f"front face at {front}, outside the "
                       f"{FRONT_FACE_MIN}-{FRONT_FACE_MAX} reference band")
    elif rec.get("rendered"):
        out.append(f"not measurable: {m.get('reason', 'unknown')}")
    if (rec.get("render_seconds") or 0) > SLOW_RENDER_S:
        out.append(f"slow render (>{SLOW_RENDER_S:.0f}s)")
    layout = rec.get("layout") or {}
    if layout.get("checked"):
        out.extend(layout["issues"])
    elif layout:
        out.append(f"layout not checked: {layout.get('reason', 'unknown')}")
    return out


# ── Reporting ────────────────────────────────────────────────────────────────
def _median(values):
    s = sorted(values)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def spread_by_template(records: list[dict]) -> dict:
    """Frame fill per template. The group is near-homogeneous in geometry, so a
    SKU whose silhouette departs from its template's median is very likely a
    TEXT defect rather than a geometry one."""
    buckets: dict[str, list] = {}
    for r in records:
        m = r.get("measurement") or {}
        if m.get("measured") and r.get("template_id"):
            buckets.setdefault(r["template_id"], []).append(
                (r["stem"], m["frame_fill_dominant_pct"]))
    out = {}
    for tid, rows in buckets.items():
        vals = [v for _, v in rows]
        med = _median(vals)
        out[tid] = {
            "count": len(vals), "min": min(vals), "max": max(vals), "median": med,
            "outliers": [{"stem": s, "dominant_pct": v,
                          "deviation_pp": round(v - med, 1)}
                         for s, v in rows if abs(v - med) > SPREAD_TOLERANCE_PP],
        }
    return out


def driver_fingerprint() -> dict:
    """What produced the pixels: the driver's content hash and the render settings.

    A sweep resumes by finding `{stem}.png` on disk, and a PNG does not say which
    driver drew it. The first catalogue run assembled a "baseline" out of five
    generations: eight SKU came back flagged for a blown, cropped frame and a
    front face at 138.9 against a 230-245 band, and every one of them had been
    rendered on 2026-07-31, nine days and several rig fixes earlier. Measured
    honestly, attributed to the wrong code.

    Recorded so a report can be checked rather than trusted, and so `--force`
    versus resume is a visible choice.
    """
    driver = resolve_path(_CFG["blender"]["driver_script"])
    digest = hashlib.sha256(driver.read_bytes()).hexdigest() if driver.exists() else None
    return {
        "driver_script": str(driver.relative_to(PROJECT_ROOT)) if driver.exists() else None,
        "driver_sha256": digest,
        "driver_mtime": driver.stat().st_mtime if driver.exists() else None,
        "engine_type": _CFG["blender"].get("engine_type"),
        "samples": _CFG["blender"].get("samples"),
        "resolution": _CFG["blender"].get("resolution"),
    }


def is_stale(png: Path) -> bool:
    """Was this PNG drawn by an older driver than the one on disk now?

    One-directional, and that is what makes it safe to act on: a render older
    than the driver CANNOT have come from it. The converse is not claimed — a
    driver merely re-saved marks fresh renders stale, which costs a re-render
    and never yields a wrong measurement.
    """
    driver_mtime = (_FINGERPRINT or driver_fingerprint()).get("driver_mtime")
    return bool(driver_mtime) and png.stat().st_mtime < driver_mtime


def catalogue_templates() -> list[str]:
    """Every template_id with at least one SKU, read off the manifests.

    The set is data, not a constant: `T2` has zero SKU here and a future
    catalogue could populate it or empty another. A report that hardcodes the
    list will eventually describe a catalogue that no longer exists.
    """
    tids = set()
    for f in MANIFEST_DIR.glob("*.json"):
        try:
            tids.add(json.loads(f.read_text(encoding="utf-8"))["template_id"])
        except Exception:  # noqa: BLE001 — an unreadable manifest is the sweep's finding, not this helper's
            continue
    return sorted(tids)


def report_paths(limit, group_name: str = CATALOGUE) -> tuple[Path, Path]:
    """Where this run's reports go.

    One rule: **only a whole-catalogue run may occupy `sweep_report.*`.** Every
    narrower run — a smaller group, or `--limit` — writes to its own filenames.

    The `--limit` half of that already existed, because a three-SKU smoke check
    silently replaced a full group's report and left the repository claiming the
    group was verified when a tenth of it was. The group half was missing, and
    the same thing had quietly happened again: `sweep_report.md` was named as
    though it were *the* sweep of record while covering the 18 SKU of `families`,
    and a `top30` run would have overwritten it with a different 30.
    """
    parts = ["sweep_report"]
    if group_name != CATALOGUE:
        parts.append(group_name)
    if limit is not None:
        parts.append("partial")
    stem = ".".join(parts)
    return STATE_DIR / f"{stem}.json", STATE_DIR / f"{stem}.md"


def write_reports(records, group_name, started_at, interrupted=False, limit=None):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    json_path, md_path = report_paths(limit, group_name)
    spread = spread_by_template(records)
    flagged = [(r, problems_for(r)) for r in records]
    flagged = [(r, p) for r, p in flagged if p]
    templates = sorted({r.get("template_id") for r in records if r.get("template_id")})
    total_s = sum(r.get("render_seconds") or 0 for r in records)

    payload = {
        "group": group_name,
        "started_at": started_at,
        "interrupted": interrupted,
        "limit": limit,
        "covers_whole_group": limit is None,
        "counts": {"total": len(records),
                   "rendered": sum(1 for r in records if r.get("rendered")),
                   "failed": sum(1 for r in records if not r.get("rendered")),
                   "flagged": len(flagged)},
        "templates_covered": templates,
        "total_render_seconds": round(total_s, 1),
        "thresholds": {"blank_pct": BLANK_FRAC, "oversize_pct": OVERSIZE_FRAC,
                       "slow_render_s": SLOW_RENDER_S,
                       "spread_tolerance_pp": SPREAD_TOLERANCE_PP},
        "spread_by_template": spread,
        "rendered_by": _FINGERPRINT or driver_fingerprint(),
        "records": records,
    }
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    L = []
    L.append("# Catalogue sweep report")
    L.append("")
    scope = ("the whole group" if limit is None
             else f"**a partial run — first {limit} of the group only**")
    L.append(f"> Group `{group_name}`, {scope} · started {started_at}"
             + (" · **INTERRUPTED**" if interrupted else ""))
    L.append("")
    L.append("Generated by `scripts/catalogue_sweep.py`. Diagnostic only: nothing "
             "about how the packshot is rendered was changed to produce this.")
    L.append("")
    fp = payload["rendered_by"]
    res = fp.get("resolution") or ["?", "?"]
    sha = (fp.get("driver_sha256") or "unknown")[:12]
    L.append(f"Rendered by `{fp.get('driver_script')}` `{sha}`, "
             f"{fp.get('engine_type')} at {fp.get('samples')} samples, "
             f"{res[0]}x{res[1]}.")
    stale = [r for r in records if r.get("render_predates_driver")]
    if stale:
        L.append("")
        L.append(f"⚠️ **{len(stale)} of {len(records)} PNG predate that driver** and were "
                 "measured anyway. Those rows describe older code, not this one — "
                 "re-run with `--force`.")
    L.append("")
    L.append("## Summary")
    L.append("")
    L.append(f"- SKU in group: **{len(records)}**")
    L.append(f"- Rendered: **{payload['counts']['rendered']}** · "
             f"failed: **{payload['counts']['failed']}**")
    L.append(f"- Flagged against thresholds: **{len(flagged)}**")
    # Divided by what was actually rendered THIS run, not by the group size. A
    # resumed sweep measures existing PNG in well under a second and contributes
    # no render time at all, so dividing by the group turned 100 renders at 27 s
    # into "7 s per SKU" — a figure true of neither the renders nor the sweep.
    timed = [r for r in records if r.get("render_seconds") is not None]
    reused = len(records) - len(timed)
    line = f"- Total render time: **{total_s / 60:.1f} min**"
    if timed:
        line += f" for the {len(timed)} rendered here ({total_s / len(timed):.0f} s each)"
    if reused:
        line += f"; {reused} measured from PNG this driver had already written"
    L.append(line)
    L.append("")
    # Computed, not written down. The caveat used to name the same seven
    # templates as unexercised whatever the run covered, so the committed
    # `families` report listed all nine templates as covered and then declared
    # seven of them absent — two sentences apart, contradicting each other. A
    # caveat that is wrong about its own run is worse than none.
    # Two different coverages, and conflating them is how a report overstates
    # itself: `families` touches all nine templates with two SKU each, which is
    # 18 of 391 and says nothing about the other 373.
    populated = catalogue_templates()
    catalogue_size = len(list(MANIFEST_DIR.glob("*.json")))
    missing = [t for t in populated if t not in set(templates)]
    unmeasured = max(0, catalogue_size - len(records))
    L.append("### Coverage caveat")
    L.append("")
    if not templates:
        L.append("This run measured **nothing**. No conclusion of any kind follows.")
    elif missing:
        L.append(f"This run covers **{', '.join(templates)}** — {len(templates)} of "
                 f"the catalogue's {len(populated)} populated templates, "
                 f"{len(records)} of its {catalogue_size} SKU. "
                 f"{', '.join('`' + t + '`' for t in missing)} **not exercised "
                 "here**; draw no conclusion about them from this report. Their "
                 "panels are narrower and their layouts tighter, which is exactly "
                 "where a sweep is most likely to find something.")
    elif unmeasured:
        L.append(f"All {len(populated)} populated templates appear, but only "
                 f"**{len(records)} of the catalogue's {catalogue_size} SKU** were "
                 f"measured. A template that comes back clean here is not a "
                 f"statement about the {unmeasured} SKU that were not rendered — "
                 "the layout is fitted per SKU, and every defect this sweep has "
                 "ever found was specific to one.")
    else:
        L.append(f"**All {catalogue_size} SKU across all {len(populated)} populated "
                 f"templates.** Within the thresholds below, this run is the "
                 "catalogue — the baseline other runs are read against.")
    L.append("")

    L.append("## Frame fill by template")
    L.append("")
    L.append("The group is near-homogeneous in geometry, so silhouettes within a "
             "template should barely vary. A SKU that departs from its template's "
             "median is most likely a text-layout defect, not a geometry one.")
    L.append("")
    L.append("| Template | SKU | min | median | max | outliers |")
    L.append("|---|---:|---:|---:|---:|---|")
    for tid in sorted(spread):
        s = spread[tid]
        outl = ", ".join(f"`{o['stem']}` ({o['deviation_pp']:+.1f} pp)"
                         for o in s["outliers"]) or "none"
        L.append(f"| {tid} | {s['count']} | {s['min']:.1f}% | {s['median']:.1f}% | "
                 f"{s['max']:.1f}% | {outl} |")
    L.append("")

    L.append("## What was actually checked")
    L.append("")
    L.append("Two independent passes, because they catch different things:")
    L.append("")
    L.append("- **Pixels** — silhouette extent, per-edge margins, front-face "
             "brightness. Catches a carton that is cropped, missing or mis-framed.")
    L.append("- **Scene** — every label row's bounds read out of the built scene via "
             "the driver's `--dump-scene`, checked against the face edges and against "
             "the row below. This is the pass that can see a text defect at all: a "
             "row that overruns the face or collides with its neighbour leaves the "
             "silhouette completely unchanged, so the pixel pass is blind to it.")
    L.append("")
    checked = sum(1 for r in records if (r.get("layout") or {}).get("checked"))
    L.append(f"Scene check completed for **{checked} of {len(records)}** SKU.")
    L.append("")

    L.append("## Flagged SKU")
    L.append("")
    if not flagged:
        L.append("None. Every SKU rendered, stayed inside the frame, kept every label "
                 "row within the printed face, and fell within the size and time "
                 "thresholds.")
    else:
        L.append("| Stem | Product | Template | Problem |")
        L.append("|---|---|---|---|")
        for r, probs in flagged:
            L.append(f"| `{r['stem']}` | {r.get('product_name', '?')} | "
                     f"{r.get('template_id', '?')} | {'; '.join(probs)} |")
    L.append("")

    L.append("## All SKU")
    L.append("")
    L.append("| Stem | Product | Template | Carton mm | Fill w/h | Front face | Time |")
    L.append("|---|---|---|---|---|---:|---:|")
    for r in records:
        m = r.get("measurement") or {}
        carton = "x".join(f"{v:.0f}" for v in r.get("carton_mm", [])) or "?"
        fill = (f"{m['frame_fill_width_pct']:.0f}/{m['frame_fill_height_pct']:.0f}%"
                if m.get("measured") else "—")
        front = f"{m['front_face_mean']:.1f}" if m.get("front_face_mean") else "—"
        secs = f"{r['render_seconds']:.0f}s" if r.get("render_seconds") else "—"
        L.append(f"| `{r['stem']}` | {r.get('product_name', '?')} | "
                 f"{r.get('template_id', '?')} | {carton} | {fill} | {front} | {secs} |")
    L.append("")
    md_path.write_text("\n".join(L) + "\n", encoding="utf-8")


# ── Orchestration ────────────────────────────────────────────────────────────
def sweep(group_name: str, limit: int | None, force: bool) -> int:
    global _FINGERPRINT
    _FINGERPRINT = driver_fingerprint()
    group = group_members(group_name)
    if limit is not None:
        group = group[:limit]

    missing = [s for s, _ in group if not (PASSPORT_DIR / f"{s}.json").exists()]
    if missing:
        print(f"[sweep] passports missing for: {', '.join(missing)}", file=sys.stderr)
        return 2
    if not BLENDER_EXE.exists():
        print(f"[sweep] Blender not found at {BLENDER_EXE}", file=sys.stderr)
        return 2

    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    interrupted = False

    print(f"[sweep] group={group_name} n={len(group)} force={force}")
    try:
        for i, (stem, label) in enumerate(group, 1):
            png = OUT_DIR / f"{stem}.png"
            object_mask = OUT_DIR / f"{stem}.object.png"
            shadow_mask = OUT_DIR / f"{stem}.shadow.png"
            # Resume asks whether this driver rendered the SKU, not merely whether
            # a PNG exists. Existence was the old question, and it let a baseline
            # be assembled out of five driver generations -- eight of the first
            # twenty SKU came back flagged for defects fixed nine days earlier.
            # Detecting that in the report was only half the answer: a sweep that
            # KNOWS a render is stale should replace it, not describe it.
            stale = png.exists() and is_stale(png)
            missing_masks = png.exists() and not (
                object_mask.exists() and shadow_mask.exists())
            if png.exists() and not force and not stale and not missing_masks:
                print(f"[{i}/{len(group)}] {stem} — already rendered, measuring only")
                records.append(record_for(stem, label, True, None, ""))
                continue
            for artifact in (png, object_mask, shadow_mask):
                if artifact.exists():
                    artifact.unlink()
            if stale and not force:
                why = "re-rendering (older than the driver)"
            elif missing_masks and not force:
                why = "re-rendering (derived masks missing)"
            else:
                why = "rendering..."
            print(f"[{i}/{len(group)}] {stem} — {why}", flush=True)
            ok, secs, err = render_one(stem)
            rec = record_for(stem, label, ok, secs, err)
            records.append(rec)
            m = rec.get("measurement") or {}
            note = (f"{m['frame_fill_width_pct']:.0f}/{m['frame_fill_height_pct']:.0f}%"
                    if m.get("measured") else (err or "unmeasured"))
            print(f"          {'ok' if ok else 'FAILED'} {secs:.0f}s  {note}", flush=True)
    except KeyboardInterrupt:
        interrupted = True
        print("\n[sweep] interrupted — writing what was collected", file=sys.stderr)

    write_reports(records, group_name, started_at, interrupted, limit)
    flagged = sum(1 for r in records if problems_for(r))
    print(f"[sweep] done: {len(records)} record(s), {flagged} flagged")
    print(f"[sweep] {report_paths(limit, group_name)[1]}")
    return 1 if interrupted else 0


def legibility_scan(top_n: int) -> int:
    """Measure printed type size for the catalogue's longest label strings.

    Separate from the group sweep and catalogue-wide on purpose. The driver fits
    a long row by shrinking it, so the failure it produces is illegibility rather
    than overflow — and the SKU at risk are whichever have the longest strings on
    the narrowest faces, which no curated group is likely to contain. Reads the
    built scene only; renders nothing.
    """
    manifests = []
    for f in sorted(MANIFEST_DIR.glob("*.json")):
        m = json.loads(f.read_text(encoding="utf-8"))
        manifests.append((len(m["label_content"]["active_ingredient_display"]),
                          f.stem, m))
    manifests.sort(reverse=True, key=lambda t: t[0])
    subjects = manifests[:top_n]

    print(f"[legibility] measuring the {len(subjects)} longest of {len(manifests)} SKU")
    rows = []
    for i, (nchars, stem, m) in enumerate(subjects, 1):
        res = check_scene(stem)
        smallest = res.get("smallest_fitted_row_mm") if res.get("checked") else None
        rows.append({"stem": stem, "template_id": m["template_id"],
                     "face_width_mm": m["carton"]["width_mm"],
                     "ingredient_chars": nchars,
                     "ingredient": m["label_content"]["active_ingredient_display"],
                     "smallest_fitted_row_mm": smallest,
                     "below_floor": bool(smallest and smallest < SMALL_PRINT_MIN_MM)})
        print(f"[{i}/{len(subjects)}] {stem:<10} {nchars:3d} chars -> "
              f"{smallest if smallest else '?'}mm", flush=True)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    below = [r for r in rows if r["below_floor"]]
    payload = {"scanned": len(subjects), "catalogue_size": len(manifests),
               "floor_mm": SMALL_PRINT_MIN_MM,
               "below_floor": len(below), "rows": rows}
    (STATE_DIR / "legibility_report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    L = ["# Small-print legibility scan", "",
         "> Generated by `scripts/catalogue_sweep.py --legibility-scan`. "
         "Reads the built scene; renders nothing.", "",
         "The driver never lets a label row overrun its face — it shrinks the row "
         "to fit. That makes overflow impossible and makes **illegibility** the "
         "failure mode instead, which no silhouette or pixel check can see. "
         "Measured on `357-min`: a 37-character ingredient sets at 4.64mm cap "
         "height, 70 characters at 1.73mm, 140 at 0.77mm — with the row's width "
         "pinned at 101.2mm throughout.", "",
         f"The curated references hold small print to 4.4-5.5mm "
         f"(`reference_analysis.md` §6). Flagged here below **{SMALL_PRINT_MIN_MM}mm**.",
         "",
         f"Scanned the **{len(subjects)}** longest ingredient strings of "
         f"**{len(manifests)}** SKU. **{len(below)}** fall below the floor.", "",
         "| SKU | Template | Face mm | Chars | Type mm | Ingredient |",
         "|---|---|---:|---:|---:|---|"]
    for r in rows:
        mark = " ⚠" if r["below_floor"] else ""
        size = f"{r['smallest_fitted_row_mm']:.2f}{mark}" if r["smallest_fitted_row_mm"] else "?"
        L.append(f"| `{r['stem']}` | {r['template_id']} | {r['face_width_mm']:.0f} | "
                 f"{r['ingredient_chars']} | {size} | {r['ingredient'][:52]} |")
    L += ["", "The pattern is a long string on a narrow face, so the worst case is "
              "not simply the longest string: a 42-character ingredient on an 80mm "
              "`T_VERT_VIAL` face sets smaller than a 61-character one on a 110mm "
              "`T_MULTIPACK`.", ""]
    (STATE_DIR / "legibility_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"[legibility] {len(below)} of {len(subjects)} below {SMALL_PRINT_MIN_MM}mm")
    print(f"[legibility] {STATE_DIR / 'legibility_report.md'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--group", choices=group_names(), default="top30",
                   help="`catalogue` is every SKU on disk; the others are curated "
                        "selections. Only a whole `catalogue` run writes the "
                        "canonical sweep_report.* — see report_paths().")
    p.add_argument("--limit", type=int, default=None,
                   help="only the first N SKU of the group (trial runs)")
    p.add_argument("--force", action="store_true",
                   help="re-render even where a PNG already exists")
    p.add_argument("--legibility-scan", type=int, nargs="?", const=15, default=None,
                   metavar="N",
                   help="instead of a sweep, measure printed type size for the N "
                        "longest label strings across the whole catalogue")
    args = p.parse_args()
    if args.legibility_scan is not None:
        return legibility_scan(args.legibility_scan)
    return sweep(args.group, args.limit, args.force)


if __name__ == "__main__":
    sys.exit(main())
