"""Independent vector/font -> 600+ DPI physical artwork and PBR maps.

Only separately sourced SVG/TTF assets are accepted. There is no photograph,
Blender import, tracing, reprojection or camera dependency in this module.
"""

from __future__ import annotations
import functools
import io
import json
import math
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
import cairosvg
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

from src.carton_spec import validate_spec, resolve_asset, workspace_root, sha256
from src.carton_dieline import build_dieline, braille_points, emboss_segments


@functools.lru_cache(maxsize=8)
def _font(path):
    return TTFont(path)


def text_svg(element, spec):
    font = _font(str(resolve_asset(spec["assets"][element["font"]]["path"])))
    gs = font.getGlyphSet(location={"wght": element["weight"], "wdth": 100})
    cmap = font.getBestCmap()
    pen = SVGPathPen(gs)
    bounds = BoundsPen(gs)
    cursor = 0
    scale = element["font_size_mm"] / font["head"].unitsPerEm
    for char in element["text"]:
        if ord(char) not in cmap:
            raise ValueError(f"Missing glyph {char!r} in specified font")
        glyph = gs[cmap[ord(char)]]
        matrix = (1, 0, 0, 1, cursor, 0)
        glyph.draw(TransformPen(pen, matrix))
        glyph.draw(TransformPen(bounds, matrix))
        cursor += glyph.width + element["tracking_mm"] / scale
    if not bounds.bounds:
        raise ValueError("A required text element has no ink")
    x0, y0, x1, y1 = bounds.bounds
    width, height = (x1 - x0) * scale, (y1 - y0) * scale
    ink = spec["colors"][element["color"]]["hex"]
    return (
        width,
        height,
        f'<g transform="translate({-x0 * scale} {y1 * scale}) scale({scale} {-scale})"><path fill="{ink}" d="{pen.getCommands()}"/></g>',
    )


def vector_svg(element, spec):
    root = ET.parse(resolve_asset(spec["assets"][element["asset"]]["path"])).getroot()
    x, y, w, h = map(float, root.attrib["viewBox"].split())
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag in {"image", "script", "foreignObject"}:
            raise ValueError("Raster or active SVG content forbidden")
        for key, value in node.attrib.items():
            if key.endswith("href") and not value.startswith("#"):
                raise ValueError("External SVG reference forbidden")
        if tag == "path":
            node.set("fill", spec["colors"][element["color"]]["hex"])
    target_w, target_h = element["bbox_mm"][2:]
    if element["rotation_deg"] in (90, 270):
        target_w, target_h = target_h, target_w
    inner = "".join(ET.tostring(child, encoding="unicode") for child in root)
    return (
        target_w,
        target_h,
        f'<g transform="scale({target_w / w} {target_h / h}) translate({-x} {-y})">{inner}</g>',
    )


def barcode_svg(element, spec):
    # Code 39 symbol patterns, verified against ZXing Code39Reader.java.
    # Only symbols required by the explicitly DEMO payload are defined.
    encoding = {
        "*": 0x094,
        "D": 0x019,
        "E": 0x118,
        "M": 0x142,
        "O": 0x112,
        "7": 0x025,
        "4": 0x031,
        "I": 0x04C,
        "N": 0x013,
    }
    data = "*" + element["payload"] + "*"
    if not element["payload"].startswith("DEMO"):
        raise ValueError("This authored artwork may only encode DEMO data")
    widths = []
    for char in data:
        for bit in range(8, -1, -1):
            widths.append(element["wide_ratio"] if encoding[char] & (1 << bit) else 1)
        widths.append(1)
    quiet = element["quiet_modules"]
    w, h = element["bbox_mm"][2:]
    scale = w / (sum(widths) + 2 * quiet)
    x = quiet * scale
    rects = []
    for i, width in enumerate(widths):
        if i % 10 % 2 == 0:
            rects.append(
                f'<rect x="{x}" y="0" width="{width * scale}" height="{h}" fill="{spec["colors"][element["color"]]["hex"]}"/>'
            )
        x += width * scale
    return w, h, "".join(rects)


def element_svg(element, spec):
    kind = element["kind"]
    w, h = element["bbox_mm"][2:]
    if kind == "text":
        w, h, body = text_svg(element, spec)
    elif kind == "vector":
        w, h, body = vector_svg(element, spec)
    elif kind == "barcode":
        w, h, body = barcode_svg(element, spec)
    elif kind == "band":
        body = f'<rect width="{w}" height="{h}" fill="{spec["colors"][element["color"]]["hex"]}"/>'
    elif kind == "path":
        from xml.sax.saxutils import quoteattr

        body = f'<path d={quoteattr(element["path_mm"])} fill="{spec["colors"][element["color"]]["hex"]}"/>'
    elif kind == "braille":
        x0, y0 = element["bbox_mm"][:2]
        r = element["dot_diameter_mm"] / 2
        body = "".join(
            f'<circle cx="{x - x0}" cy="{y - y0}" r="{r}" fill="white"/>'
            for x, y in braille_points(element)
        )
    elif kind == "emboss":
        x0, y0 = element["bbox_mm"][:2]
        length = element["dash_length_mm"]
        thickness = element["dash_width_mm"]
        body = "".join(
            f'<path d="M{x - x0 - dx * length / 2},{y - y0 - dy * length / 2} l{dx * length},{dy * length}" fill="none" stroke="white" stroke-width="{thickness}" stroke-linecap="round"/>'
            for x, y, dx, dy in emboss_segments(element)
        )
    elif kind == "foil":
        r = element["corner_radius_mm"]
        colors = spec["materials"]["foil_colors"]
        pitch = spec["materials"]["foil_line_pitch_mm"]
        line = spec["materials"]["foil_line_width_mm"]
        body = f'<defs><clipPath id="foil"><rect width="{w}" height="{h}" rx="{r}"/></clipPath></defs><g clip-path="url(#foil)"><rect width="{w}" height="{h}" fill="{spec["colors"][element["color"]]["hex"]}"/>'
        if element.get("shape") == "ellipse":
            body = body.replace(
                f'<rect width="{w}" height="{h}" rx="{r}"/>',
                f'<ellipse cx="{w / 2}" cy="{h / 2}" rx="{w / 2}" ry="{h / 2}"/>',
            )
        for i in range(math.ceil((w + h) / pitch)):
            c = spec["colors"][colors[i % len(colors)]]["hex"]
            q = i * pitch
            body += f'<path d="M{q},0 L{q - h},{h}" fill="none" stroke="{c}" stroke-width="{line}"/>'
        for j, c in enumerate(colors):
            fill = spec["colors"][c]["hex"]
            margin = (j + 1) * pitch * 2
            body += f'<path d="M{w / 2},{margin} L{w - margin},{h / 2} L{w / 2},{h - margin} L{margin},{h / 2} Z" fill="none" stroke="{fill}" stroke-width="{line * 3}"/>'
        body += "</g>"
    else:
        raise ValueError(f"Unsupported artwork kind: {kind}")
    rotation = element.get("rotation_deg", 0)
    if rotation == 90:
        body = f'<g transform="translate({h} 0) rotate(90)">{body}</g>'
        w, h = h, w
    elif rotation == 270:
        body = f'<g transform="translate(0 {w}) rotate(-90)">{body}</g>'
        w, h = h, w
    elif rotation != 0:
        raise ValueError("Only panel-aligned quarter turns are supported")
    return (
        w,
        h,
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">{body}</svg>',
    )


def generate_artwork(spec, output: Path | None = None):
    started = time.perf_counter()
    validate_spec(spec)
    root = workspace_root()
    output = Path(output or root / "assets/generated" / spec["sku"])
    if not output.resolve().is_relative_to((root / "assets/generated").resolve()):
        raise ValueError("Invalid generated output path")
    output.mkdir(parents=True, exist_ok=True)
    (output / "vectors").mkdir(exist_ok=True)
    (output / "layout_masks").mkdir(exist_ok=True)
    dieline = build_dieline(spec)
    atlas = dieline["atlas"]
    ppm = spec["atlas"]["dpi"] / 25.4
    size = tuple(math.ceil(atlas[k] * ppm) for k in ("width_mm", "height_mm"))
    base = Image.new("RGB", size, spec["colors"]["paper"]["hex"])
    rough = Image.new("L", size, round(spec["materials"]["paper_roughness"] * 255))
    metal = Image.new("L", size, 0)
    height = Image.new("L", size, 0)
    records = []
    atlas_svg = []
    for e in spec["elements"]:
        w, h, svg = element_svg(e, spec)
        vector_path = output / "vectors" / f"{e['id']}.svg"
        vector_path.write_text(svg, encoding="utf-8")
        layer = Image.open(
            io.BytesIO(
                cairosvg.svg2png(
                    bytestring=svg.encode(),
                    output_width=max(1, math.ceil(w * ppm)),
                    output_height=max(1, math.ceil(h * ppm)),
                )
            )
        ).convert("RGBA")
        alpha = layer.getchannel("A")
        bounds = alpha.point(lambda v: 255 if v >= 128 else 0).getbbox()
        if not bounds:
            raise ValueError(f"Required element has empty raster: {e['id']}")
        region = atlas["regions"][e["panel"]]
        x = e["bbox_mm"][0] + region[0]
        y = e["bbox_mm"][1] + region[1]
        px, py = round(x * ppm), round(y * ppm)
        if e["kind"] not in ("braille", "emboss"):
            base.paste(layer, (px, py), alpha)
            if e["kind"] not in ("band", "path"):
                rough.paste(
                    round(spec["materials"]["ink_roughness"] * 255),
                    (px, py, px + layer.width, py + layer.height),
                    alpha,
                )
        if e["kind"] == "foil":
            metal.paste(255, (px, py, px + layer.width, py + layer.height), alpha)
            rough.paste(
                round(spec["materials"]["foil_roughness"] * 255),
                (px, py, px + layer.width, py + layer.height),
                alpha,
            )
        if e["kind"] in ("braille", "emboss"):
            height.paste(255, (px, py, px + layer.width, py + layer.height), alpha)
        alpha.save(output / "layout_masks" / f"{e['id']}.png")
        actual = [
            (px + bounds[0]) / ppm - region[0],
            (py + bounds[1]) / ppm - region[1],
            (bounds[2] - bounds[0]) / ppm,
            (bounds[3] - bounds[1]) / ppm,
        ]
        records.append(
            dict(
                id=e["id"],
                panel=e["panel"],
                kind=e["kind"],
                actual_bbox_mm=actual,
                raster_bbox_px=list(bounds),
                atlas_origin_px=[px, py],
                mask=f"layout_masks/{e['id']}.png",
                mask_sha256=sha256(output / "layout_masks" / f"{e['id']}.png"),
            )
        )
        body = ET.fromstring(svg)
        inner = "".join(ET.tostring(c, encoding="unicode") for c in body)
        if e["kind"] not in ("braille", "emboss"):
            atlas_svg.append(f'<g transform="translate({x} {y})">{inner}</g>')
    (output / "artwork.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{atlas["width_mm"]}mm" height="{atlas["height_mm"]}mm" viewBox="0 0 {atlas["width_mm"]} {atlas["height_mm"]}"><rect width="100%" height="100%" fill="{spec["colors"]["paper"]["hex"]}"/>'
        + "".join(atlas_svg)
        + "</svg>",
        encoding="utf-8",
    )
    rng = np.random.default_rng(spec["render"]["seed"])
    grain_seed = rng.integers(0, 256, size=(size[1], size[0]), dtype=np.uint8)
    grain_img = Image.fromarray(grain_seed).filter(
        ImageFilter.GaussianBlur(spec["materials"]["grain_correlation_px"])
    )
    # The embossed features are already closed 3D meshes. Keep their declared
    # height mask as an export, but do not bump them a second time in the shader.
    relief_path = output / "emboss_braille_height.png"
    height.save(relief_path, compress_level=1)
    height = grain_img
    grain = np.asarray(grain_img, dtype=np.float32) / 255 - 0.5
    values = np.asarray(rough, dtype=np.float32) + grain * (
        255 * spec["materials"]["grain_roughness_amplitude"] * 2
    )
    rough = Image.fromarray(np.uint8(np.clip(values, 0, 255)))
    del values
    dy, dx = np.gradient(grain)
    factor = spec["materials"]["grain_height_mm"] * ppm
    normal = np.empty((size[1], size[0], 3), dtype=np.uint8)
    normal[:, :, 0] = np.uint8(np.clip(127.5 - dx * factor * 127.5, 0, 255))
    normal[:, :, 1] = np.uint8(np.clip(127.5 + dy * factor * 127.5, 0, 255))
    normal[:, :, 2] = 255
    normal_image = Image.fromarray(normal)
    del grain, dx, dy
    maps = {}
    for name, img in [
        ("base_color", base),
        ("roughness", rough),
        ("metallic", metal),
        ("height", height),
        ("normal", normal_image),
    ]:
        path = output / f"{name}.png"
        img.save(path, compress_level=1, dpi=(spec["atlas"]["dpi"],) * 2)
        maps[name] = dict(
            path=path.relative_to(root).as_posix(), sha256=sha256(path), size=list(size)
        )
    result = dict(
        version="1.0",
        spec_sha256=__import__("hashlib")
        .sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode())
        .hexdigest(),
        maps=maps,
        atlas=atlas,
        elements=records,
        relief_export={
            "path": relief_path.relative_to(root).as_posix(),
            "sha256": sha256(relief_path),
        },
        generation_seconds=time.perf_counter() - started,
        dpi=spec["atlas"]["dpi"],
    )
    (output / "artwork-manifest.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result
