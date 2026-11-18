"""Millimetre panel geometry and non-overlapping UV allocation; no raster I/O."""

from __future__ import annotations
import math
from typing import Any


def build_dieline(spec):
    d, g = spec["dimensions_mm"], spec["geometry"]
    w, h, depth = d["width"], d["height"], d["depth"]
    panels: list[dict[str, Any]] = [
        dict(
            name="front",
            size=[w, h],
            origin=[-w / 2, -depth / 2, h],
            u=[1, 0, 0],
            v=[0, 0, -1],
            normal=[0, -1, 0],
        ),
        dict(
            name="back",
            size=[w, h],
            origin=[w / 2, depth / 2, h],
            u=[-1, 0, 0],
            v=[0, 0, -1],
            normal=[0, 1, 0],
        ),
        dict(
            name="left",
            size=[depth, h],
            origin=[-w / 2, depth / 2, h],
            u=[0, -1, 0],
            v=[0, 0, -1],
            normal=[-1, 0, 0],
        ),
        dict(
            name="right",
            size=[depth, h],
            origin=[w / 2, -depth / 2, h],
            u=[0, 1, 0],
            v=[0, 0, -1],
            normal=[1, 0, 0],
        ),
        dict(
            name="top",
            size=[w, depth],
            origin=[-w / 2, depth / 2, h],
            u=[1, 0, 0],
            v=[0, -1, 0],
            normal=[0, 0, 1],
        ),
        dict(
            name="bottom",
            size=[w, depth],
            origin=[-w / 2, -depth / 2, 0],
            u=[1, 0, 0],
            v=[0, 1, 0],
            normal=[0, 0, -1],
        ),
    ]
    t = g["board_thickness_mm"]
    flaps = [
        dict(
            name="top_tuck",
            panel="back",
            bbox=[t, t, w - 2 * t, g["tuck_depth_mm"]],
            inset=t,
        ),
        dict(
            name="bottom_tuck",
            panel="front",
            bbox=[t, h - g["tuck_depth_mm"] - t, w - 2 * t, g["tuck_depth_mm"]],
            inset=t,
        ),
        dict(
            name="top_dust_left",
            panel="top",
            bbox=[t, t, g["dust_depth_mm"], depth - 2 * t],
            inset=t,
        ),
        dict(
            name="top_dust_right",
            panel="top",
            bbox=[w - g["dust_depth_mm"] - t, t, g["dust_depth_mm"], depth - 2 * t],
            inset=t,
        ),
        dict(
            name="bottom_dust_left",
            panel="bottom",
            bbox=[t, t, g["dust_depth_mm"], depth - 2 * t],
            inset=t,
        ),
        dict(
            name="bottom_dust_right",
            panel="bottom",
            bbox=[w - g["dust_depth_mm"] - t, t, g["dust_depth_mm"], depth - 2 * t],
            inset=t,
        ),
        dict(
            name="glue_seam",
            panel="back",
            bbox=[t, t, g["glue_width_mm"], h - 2 * t],
            inset=t,
        ),
    ]
    gutter, atlas_w = spec["atlas"]["gutter_mm"], spec["atlas"]["width_mm"]
    regions = {}
    x = y = gutter
    row_h = 0
    rectangles = []

    def allocate(name, width, height):
        if width + 2 * gutter > atlas_w:
            raise ValueError("Atlas width smaller than a physical panel")
        rectangles.append((name, width, height))

    for panel in panels:
        pw, ph = panel["size"]
        allocate(panel["name"], pw, ph)
        allocate(panel["name"] + "_inside", pw, ph)
        for i, length in enumerate((pw, ph, pw, ph)):
            allocate(panel["name"] + f"_edge_{i}", length, t)
    for flap in flaps:
        fw, fh = flap["bbox"][2:]
        allocate(flap["name"], fw, fh)
        allocate(flap["name"] + "_inside", fw, fh)
        for i, length in enumerate((fw, fh, fw, fh)):
            allocate(flap["name"] + f"_edge_{i}", length, t)
    for name, width, height in sorted(rectangles, key=lambda r: (-r[2], -r[1], r[0])):
        if x + width + gutter > atlas_w:
            x = gutter
            y += row_h + gutter
            row_h = 0
        regions[name] = [x, y, width, height]
        x += width + gutter
        row_h = max(row_h, height)
    atlas_h = y + row_h + gutter
    return dict(
        panels=panels,
        flaps=flaps,
        atlas=dict(width_mm=atlas_w, height_mm=atlas_h, regions=regions),
    )


def panel_point(panel, u, v, offset=0):
    return [
        panel["origin"][i]
        + panel["u"][i] * u
        + panel["v"][i] * v
        + panel["normal"][i] * offset
        for i in range(3)
    ]


def braille_points(element):
    # Uncontracted Latin alphabet / six-dot Braille; digits use the number sign.
    patterns = {
        "a": "1",
        "b": "12",
        "c": "14",
        "d": "145",
        "e": "15",
        "f": "124",
        "g": "1245",
        "h": "125",
        "i": "24",
        "j": "245",
        "k": "13",
        "l": "123",
        "m": "134",
        "n": "1345",
        "o": "135",
        "p": "1234",
        "q": "12345",
        "r": "1235",
        "s": "234",
        "t": "2345",
        "u": "136",
        "v": "1236",
        "w": "2456",
        "x": "1346",
        "y": "13456",
        "z": "1356",
        " ": "",
        "#": "3456",
    }
    x0, y0, _, _ = element["bbox_mm"]
    radius = element["dot_diameter_mm"] / 2
    points = []
    for row, line in enumerate(element["lines"]):
        cells = []
        in_number = False
        for ch in line.lower():
            if ch.isdigit():
                if not in_number:
                    cells.append("#")
                    in_number = True
                cells.append("j" if ch == "0" else chr(ord("a") + int(ch) - 1))
            else:
                in_number = False
                if ch not in patterns:
                    raise ValueError(f"Unsupported Braille character: {ch}")
                cells.append(ch)
        for cell, ch in enumerate(cells):
            for dot in patterns[ch]:
                d = int(dot) - 1
                points.append(
                    [
                        x0
                        + radius
                        + cell * element["cell_pitch_mm"]
                        + (d // 3) * element["dot_pitch_mm"],
                        y0
                        + radius
                        + row * element["row_pitch_mm"]
                        + (d % 3) * element["dot_pitch_mm"],
                    ]
                )
    return points


def emboss_segments(element):
    x, y, w, h = element["bbox_mm"]
    cx = x + w / 2
    cy = y + h / 2
    count = element["dash_count"]
    radius = min(w, h) / 2
    return [
        (
            cx + radius * math.cos(2 * math.pi * i / count),
            cy + radius * math.sin(2 * math.pi * i / count),
            -math.sin(2 * math.pi * i / count),
            math.cos(2 * math.pi * i / count),
        )
        for i in range(count)
    ]
