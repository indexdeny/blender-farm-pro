"""Strict, photograph-free input contract for the physical baseline rebuild."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
from functools import lru_cache
from html import escape
from pathlib import Path
from types import MappingProxyType

CODE_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = CODE_ROOT / "Reference Templates/74_Viagra/design_spec.json"
SCHEMA_PATH = CODE_ROOT / "schemas/carton_baseline.schema.json"
REQUIRED_ELEMENTS = {
    "front_wordmark",
    "front_registered",
    "front_dose",
    "front_film",
    "front_sildenafil",
    "front_pfizer",
    "front_count",
    "front_band",
    "front_transition",
    "front_emboss",
    "front_foil",
    "back_barcode",
    "back_batch",
    "back_expiry",
    "left_vertical",
    "front_braille",
}
SOURCES = {"template", "measured", "authored", "estimated"}
CIALIS_REQUIRED_ELEMENTS = (
    REQUIRED_ELEMENTS
    - {
        "front_sildenafil",
        "front_pfizer",
        "front_band",
        "front_transition",
        "front_emboss",
    }
) | {"front_tadalafil", "front_lilly", "front_green", "front_cream"}

_NEW_REQUIRED = {
    "cialis_professional": {
        "front_wordmark", "front_professional", "front_tadalafil", "front_dose",
        "front_count", "front_emblem_gold", "front_emblem_green", "front_green_arc",
        "front_yellow_band", "back_batch", "back_expiry",
    },
    "cialis_super_active": {
        "front_wordmark", "front_super_active", "front_tadalafil", "front_dose",
        "front_count", "front_yellow_arcs", "back_batch", "back_expiry",
    },
    "kamagra": {
        "front_wordmark", "front_dose", "front_count", "front_green_stripes",
        "front_dose_patch", "front_mark_left", "front_mark_right",
        "front_mark_head_left", "front_mark_head_right", "back_batch", "back_expiry",
    },
}

PROFILE_POLICIES = MappingProxyType({
    "viagra": MappingProxyType({
        "required_element_ids": frozenset(REQUIRED_ELEMENTS),
        "effects": MappingProxyType({"foil": "required", "braille": "required", "emboss": "required"}),
    }),
    "cialis": MappingProxyType({
        "required_element_ids": frozenset(CIALIS_REQUIRED_ELEMENTS),
        "effects": MappingProxyType({"foil": "required", "braille": "required", "emboss": "optional"}),
    }),
    **{
        name: MappingProxyType({
            "required_element_ids": frozenset(required),
            "effects": MappingProxyType({"foil": "optional", "braille": "optional", "emboss": "optional"}),
        })
        for name, required in _NEW_REQUIRED.items()
    },
})

_EFFECT_KINDS = {"foil", "braille", "emboss"}
_TEXTUAL_IDS = {
    "front_professional", "front_super_active", "front_tadalafil", "front_dose",
    "front_count", "back_batch", "back_expiry",
}
_COMPOSITE_IDS = {
    "front_emblem_gold", "front_emblem_green", "front_mark_left", "front_mark_right",
    "front_mark_head_left", "front_mark_head_right",
}
_GEOMETRY_IDS = {"front_green_arc", "front_yellow_band", "front_yellow_arcs", "front_green_stripes", "front_dose_patch"}


def profile_policy(spec: dict):
    profile = spec.get("layout_profile", "viagra")
    try:
        return PROFILE_POLICIES[profile]
    except KeyError as exc:
        raise ValueError(f"Unknown physical layout profile: {profile}") from exc


def _source_root() -> Path:
    return (
        CODE_ROOT.parent.parent if CODE_ROOT.parent.name == ".worktrees" else CODE_ROOT
    )


def workspace_root() -> Path:
    root = _source_root()
    output_root = os.environ.get("BFP_PHYSICAL_OUTPUT_ROOT")
    if output_root is None:
        return root
    resolved = Path(output_root).resolve()
    allowed = (root / "reports").resolve()
    if resolved == allowed or not resolved.is_relative_to(allowed):
        raise ValueError(f"Physical output root must be strictly inside {allowed}")
    return resolved


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@lru_cache(maxsize=256)
def _path_has_printable_fill(path_mm: str, width_mm: float, height_mm: float) -> bool:
    """Render an authored vector at contract DPI and require visible filled ink."""
    import cairosvg
    from PIL import Image

    dpi = 600
    width_px = max(1, math.ceil(width_mm * dpi / 25.4))
    height_px = max(1, math.ceil(height_mm * dpi / 25.4))
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width_mm} {height_mm}">'
        f'<path d="{escape(path_mm, quote=True)}" fill="#000"/></svg>'
    )
    png = cairosvg.svg2png(
        bytestring=svg.encode("utf-8"),
        output_width=width_px,
        output_height=height_px,
    )
    with Image.open(io.BytesIO(png)) as image:
        return image.convert("RGBA").getchannel("A").getbbox() is not None


def resolve_asset(path: str, *, generated: bool = False) -> Path:
    root = workspace_root() if generated else _source_root()
    resolved = (root / path).resolve()
    allowed = root / "assets" / ("generated" if generated else "sources")
    if not resolved.is_relative_to(allowed.resolve()):
        raise ValueError(f"Asset must be inside {allowed}: {path}")
    if not resolved.is_file():
        raise ValueError(f"Asset does not exist: {path}")
    return resolved


def srgb_lab(rgb):
    """D65 sRGB -> CIE Lab, with RGB channels in 0..1."""
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    matrix = (
        (0.4124564, 0.3575761, 0.1804375),
        (0.2126729, 0.7151522, 0.0721750),
        (0.0193339, 0.1191920, 0.9503041),
    )
    xyz = [
        sum(a * b for a, b in zip(row, linear)) / white
        for row, white in zip(matrix, (0.95047, 1.0, 1.08883))
    ]
    f = [
        v ** (1 / 3) if v > (6 / 29) ** 3 else v / (3 * (6 / 29) ** 2) + 4 / 29
        for v in xyz
    ]
    return [116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])]


def hex_lab(value):
    return srgb_lab([int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)])


def validate_spec(spec: dict, *, check_files: bool = True) -> None:
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    try:
        jsonschema.Draft202012Validator(schema).validate(spec)
    except jsonschema.ValidationError as exc:
        raise ValueError(
            f"baseline_rebuild schema {list(exc.absolute_path)}: {exc.message}"
        ) from exc
    if spec["mode"] != "physical_baseline":
        raise ValueError("Only physical_baseline is accepted")
    policy = profile_policy(spec)
    profile = spec.get("layout_profile", "viagra")
    ids = [e["id"] for e in spec["elements"]]
    required = policy["required_element_ids"]
    if len(set(ids)) != len(ids) or not required.issubset(ids):
        raise ValueError("Duplicate or missing mandatory layout element")
    effect_elements = {kind: [e for e in spec["elements"] if e["kind"] == kind] for kind in _EFFECT_KINDS}
    if profile in _NEW_REQUIRED:
        effects = spec.get("effects")
        if not isinstance(effects, dict) or set(effects) != _EFFECT_KINDS:
            raise ValueError("New physical profiles require explicit foil/braille/emboss declarations")
        for kind, declaration in effects.items():
            if (
                not isinstance(declaration, dict)
                or set(declaration) != {"status", "source", "reason", "production_status"}
                or declaration["status"] not in {"present", "absent"}
                or declaration["source"] not in SOURCES
                or not isinstance(declaration["reason"], str)
                or not declaration["reason"].strip()
                or declaration["production_status"] not in {"confirmed", "unknown"}
            ):
                raise ValueError(f"Invalid effect declaration: {kind}")
            actual = bool(effect_elements[kind])
            if actual != (declaration["status"] == "present"):
                raise ValueError(f"Effect declaration does not match {kind} elements")
            if declaration["status"] == "absent" and declaration["source"] != "authored":
                raise ValueError(f"Absent {kind} must be an authored baseline decision")
    for kind, requirement in policy["effects"].items():
        if requirement == "required" and not effect_elements[kind]:
            raise ValueError(f"Required {kind} element is missing")
        if requirement == "forbidden" and effect_elements[kind]:
            raise ValueError(f"Forbidden {kind} element is present")
    for section in (
        "dimensions_mm",
        "geometry",
        "atlas",
        "materials",
        "stage",
        "render",
    ):
        if spec[section].get("source") not in SOURCES:
            raise ValueError(f"Missing numeric provenance: {section}")
    for name, color in spec["colors"].items():
        expected = hex_lab(color["hex"])
        if max(abs(a - b) for a, b in zip(expected, color["lab"])) > 0.02:
            raise ValueError(f"Inconsistent sRGB/Lab: {name}")
    for name, asset in spec["assets"].items():
        suffix = Path(asset["path"]).suffix.lower()
        if suffix not in {".svg", ".ttf", ".otf"}:
            raise ValueError(f"Only independent vector/font sources allowed: {name}")
        if check_files and sha256(resolve_asset(asset["path"])) != asset["sha256"]:
            raise ValueError(f"Asset hash mismatch: {name}")
    for element in spec["elements"]:
        dims = spec["dimensions_mm"]
        panel_sizes = {
            "front": (dims["width"], dims["height"]),
            "back": (dims["width"], dims["height"]),
            "left": (dims["depth"], dims["height"]),
            "right": (dims["depth"], dims["height"]),
            "top": (dims["width"], dims["depth"]),
            "bottom": (dims["width"], dims["depth"]),
        }
        x, y, w, h = element["bbox_mm"]
        pw, ph = panel_sizes[element["panel"]]
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > pw + 1e-6 or y + h > ph + 1e-6:
            raise ValueError(f"Element outside its panel: {element['id']}")
        if "color" in element and element["color"] not in spec["colors"]:
            raise ValueError(f"Unknown color: {element['id']}")
        if "asset" in element and element["asset"] not in spec["assets"]:
            raise ValueError(f"Unknown asset: {element['id']}")
        if profile in _NEW_REQUIRED:
            identifier = element["id"]
            if identifier == "front_wordmark" or identifier in _TEXTUAL_IDS:
                if element["kind"] == "text":
                    if not str(element.get("text", "")).strip():
                        raise ValueError(f"Visible text is empty: {identifier}")
                elif element["kind"] == "vector":
                    asset = spec["assets"].get(element.get("asset"), {})
                    if Path(asset.get("path", "")).suffix.lower() != ".svg":
                        raise ValueError(f"Visible SVG is not independently sourced: {identifier}")
                else:
                    raise ValueError(f"Invalid visible element kind: {identifier}")
            if identifier in _COMPOSITE_IDS:
                if element["kind"] not in {"vector", "path"}:
                    raise ValueError(f"Composite mark must be SVG/path: {identifier}")
                if element["kind"] == "vector":
                    asset = spec["assets"].get(element.get("asset"), {})
                    if Path(asset.get("path", "")).suffix.lower() != ".svg":
                        raise ValueError(f"Composite vector lacks an independent SVG: {identifier}")
            if identifier in _GEOMETRY_IDS and element["kind"] not in {"band", "path"}:
                raise ValueError(f"Geometry mark must be rect/path: {identifier}")
        if element["kind"] == "path":
            from fontTools.svgLib.path import parse_path
            from fontTools.pens.boundsPen import BoundsPen

            pen = BoundsPen(None)
            try:
                parse_path(element["path_mm"], pen)
            except (ValueError, KeyError, IndexError) as exc:
                raise ValueError(f"Invalid authored path: {element['id']}") from exc
            required_new_path = (
                profile in _NEW_REQUIRED
                and element["id"] in _NEW_REQUIRED[profile]
            )
            if (
                not pen.bounds
                or min(pen.bounds[:2]) < -1e-6
                or pen.bounds[2] > w + 1e-6
                or pen.bounds[3] > h + 1e-6
                or pen.bounds[2] - pen.bounds[0] <= 1e-6
                or pen.bounds[3] - pen.bounds[1] <= 1e-6
                or (
                    required_new_path
                    and not _path_has_printable_fill(element["path_mm"], w, h)
                )
            ):
                raise ValueError(f"Authored path is empty, degenerate, or outside bbox: {element['id']}")
        if element["kind"] == "text":
            for key in (
                "font",
                "font_size_mm",
                "line_height_mm",
                "tracking_mm",
                "weight",
                "italic",
                "text",
            ):
                if key not in element:
                    raise ValueError(f"Text {element['id']} missing {key}")
            if (
                element["font"] not in spec["assets"]
                or element["font_size_mm"] <= 0
                or element["line_height_mm"] <= 0
            ):
                raise ValueError(f"Invalid typography: {element['id']}")
            if "\n" in element["text"]:
                raise ValueError("Each text line must be a separate positioned block")
        if element["kind"] == "braille":
            for key in (
                "dot_diameter_mm",
                "dot_height_mm",
                "dot_pitch_mm",
                "cell_pitch_mm",
                "row_pitch_mm",
                "lines",
            ):
                if key not in element:
                    raise ValueError(f"Braille missing {key}")
            if (
                min(
                    element[k]
                    for k in (
                        "dot_diameter_mm",
                        "dot_height_mm",
                        "dot_pitch_mm",
                        "cell_pitch_mm",
                        "row_pitch_mm",
                    )
                )
                <= 0
            ):
                raise ValueError("Braille dimensions must be positive")
    geometry = spec["geometry"]
    if profile in _NEW_REQUIRED:
        validation = spec["validation"]
        targets = validation.get("reference_colors")
        patches = validation.get("control_regions_mm")
        if (
            not isinstance(targets, dict)
            or not targets
            or not isinstance(patches, dict)
            or not patches
            or "paper" not in patches
            or set(targets) != set(patches)
        ):
            raise ValueError("Reference colors and control-region keys must be nonempty and identical")
        width = spec["dimensions_mm"]["width"]
        height = spec["dimensions_mm"]["height"]
        for name, rect in patches.items():
            if (
                not isinstance(rect, list)
                or len(rect) != 4
                or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in rect)
            ):
                raise ValueError(f"Invalid control region: {name}")
            x, y, w, h = rect
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
                raise ValueError(f"Control region outside front panel: {name}")
    if (
        geometry["crease_depth_mm"] >= geometry["board_thickness_mm"]
        or geometry["bevel_mm"] > geometry["board_thickness_mm"] / 2
    ):
        raise ValueError("Crease/bevel must preserve cardboard thickness")
    camera_names = [c["name"] for c in spec["stage"]["cameras"]]
    if len(set(camera_names)) != len(camera_names) or not {
        "front",
        "hero",
        "top",
        "end",
    }.issubset(camera_names):
        raise ValueError("Four distinct required cameras must be present")

    def walk(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Non-finite number in physical spec")
        if isinstance(value, dict):
            for k, v in value.items():
                if k in {"reference_projection", "image_path", "source_image"}:
                    raise ValueError(
                        f"Photograph input forbidden in physical spec: {k}"
                    )
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(spec)


def load_spec(path: Path | None = None) -> dict:
    payload = json.loads(Path(path or SPEC_PATH).read_text("utf-8"))
    spec = payload["baseline_rebuild"]
    validate_spec(spec)
    return spec


def verify_generated(assets: dict) -> None:
    required = {"base_color", "roughness", "normal", "height", "metallic"}
    if set(assets["maps"]) != required:
        raise ValueError("Generated map set is incomplete")
    for name, record in assets["maps"].items():
        path = resolve_asset(record["path"], generated=True)
        if sha256(path) != record["sha256"]:
            raise ValueError(f"Current artwork hash mismatch: {name}")
