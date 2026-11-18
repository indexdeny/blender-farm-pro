"""Blender adapter for real panel shells, flaps, embossed caps and foil.

The API is injected by render_driver; geometry numbers come from design_spec.
"""

from __future__ import annotations
import math
from src.carton_dieline import panel_point, braille_points, emboss_segments


def make_geometry(api, spec, dieline, artwork, material):
    geometry = spec["geometry"]
    atlas = artwork["atlas"]
    ppm = artwork["dpi"] / 25.4
    image_size = artwork["maps"]["base_color"]["size"]
    panels = {p["name"]: p for p in dieline["panels"]}
    objects = []
    board_mappings = {}

    def uv(region, u, v):
        x, y, _, _ = atlas["regions"][region]
        return ((x + u) * ppm / image_size[0], 1 - (y + v) * ppm / image_size[1])

    def mesh_object(name, vertices, faces, face_uvs, kind, bevel=0, smooth=False):
        mesh = api.data.meshes.new(name)
        mesh.from_pydata([[v / 1000 for v in point] for point in vertices], [], faces)
        mesh.update()
        obj = api.data.objects.new(name, mesh)
        api.context.collection.objects.link(obj)
        obj.data.materials.append(material)
        obj.pass_index = 1
        obj["physical_kind"] = kind
        layer = mesh.uv_layers.new(name="PanelUV")
        for polygon, coords in zip(mesh.polygons, face_uvs):
            for index, coord in zip(polygon.loop_indices, coords):
                layer.data[index].uv = coord
            polygon.use_smooth = smooth
        api.context.view_layer.objects.active = obj
        obj.select_set(True)
        if bevel:
            modifier = obj.modifiers.new("Physical edge radius", "BEVEL")
            modifier.width = bevel / 1000
            modifier.segments = geometry["bevel_segments"]
            modifier.limit_method = "ANGLE"
            api.ops.object.modifier_apply(modifier=modifier.name)
            obj["bevel_mm"] = bevel
        triangulate = obj.modifiers.new("Explicit triangulation", "TRIANGULATE")
        api.ops.object.modifier_apply(modifier=triangulate.name)
        obj.select_set(False)
        objects.append(obj)
        return obj

    def board(name, panel, rect, offset, thickness, kind, region=None):
        x, y, w, h = rect
        points = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        vertices = [panel_point(panel, u, v, offset) for u, v in points] + [
            panel_point(panel, u, v, offset - thickness) for u, v in points
        ]
        faces = [
            [0, 3, 2, 1],
            [4, 5, 6, 7],
            [0, 1, 5, 4],
            [1, 2, 6, 5],
            [2, 3, 7, 6],
            [3, 0, 4, 7],
        ]
        own = region or name
        face_uvs = [
            [uv(own, *[(0, 0), (0, h), (w, h), (w, 0)][i]) for i in range(4)],
            [uv(own + "_inside", *p) for p in [(0, 0), (w, 0), (w, h), (0, h)]],
        ]
        for i, length in enumerate((w, h, w, h)):
            face_uvs.append(
                [
                    uv(own + f"_edge_{i}", *p)
                    for p in [(0, 0), (length, 0), (length, thickness), (0, thickness)]
                ]
            )
        obj = mesh_object(
            name,
            vertices,
            faces,
            face_uvs,
            kind,
            min(geometry["bevel_mm"], thickness / 2),
            False,
        )
        obj["panel"] = panel["name"]
        obj["thickness_mm"] = thickness
        board_mappings[name] = (rect, offset, thickness, own)
        return obj

    for panel in panels.values():
        w, h = panel["size"]
        gap = geometry["panel_gap_mm"]
        board(
            panel["name"],
            panel,
            [gap / 2, gap / 2, w - gap, h - gap],
            0,
            geometry["board_thickness_mm"],
            "panel",
        )
    for flap in dieline["flaps"]:
        board(
            flap["name"],
            panels[flap["panel"]],
            flap["bbox"],
            -flap["inset"],
            geometry["board_thickness_mm"],
            "flap",
        )

    # A real scored hinge in the top board, not a dark painted line. The cutter
    # is construction tooling and is removed after the closed boolean result.
    top = next(o for o in objects if o.name == "top")
    width = spec["dimensions_mm"]["width"]
    depth = spec["dimensions_mm"]["depth"]
    height = spec["dimensions_mm"]["height"]
    api.ops.mesh.primitive_cube_add(size=1)
    cutter = api.context.object
    cutter.name = "Temporary crease tooling"
    cutter.dimensions = (
        (width + 2 * geometry["board_thickness_mm"]) / 1000,
        geometry["crease_width_mm"] / 1000,
        2 * geometry["crease_depth_mm"] / 1000,
    )
    cutter.location = (
        0,
        (depth / 2 - geometry["crease_position_mm"]) / 1000,
        height / 1000,
    )
    api.ops.object.transform_apply(location=False, rotation=False, scale=True)
    cutter.data.materials.append(material)
    cutter_uv = cutter.data.uv_layers.active
    for polygon in cutter.data.polygons:
        for index in polygon.loop_indices:
            point = (
                cutter.matrix_world
                @ cutter.data.vertices[cutter.data.loops[index].vertex_index].co
            )
            cutter_uv.data[index].uv = uv(
                "top", point.x * 1000 + width / 2, depth / 2 - point.y * 1000
            )
    api.context.view_layer.objects.active = top
    cut = top.modifiers.new("Scored top hinge", "BOOLEAN")
    cut.operation = "DIFFERENCE"
    cut.solver = "EXACT"
    cut.object = cutter
    api.ops.object.modifier_apply(modifier=cut.name)
    api.data.objects.remove(cutter, do_unlink=True)
    triangulate = top.modifiers.new("Triangulated score", "TRIANGULATE")
    api.ops.object.modifier_apply(modifier=triangulate.name)
    top["crease_width_mm"] = geometry["crease_width_mm"]
    top["crease_depth_mm"] = geometry["crease_depth_mm"]

    def relief_prism(name, panel, points, height, kind):
        # Ordered panel-space polygon, extruded into a closed physical solid.
        n = len(points)
        vertices = [panel_point(panel, p[0], p[1], height) for p in points] + [
            panel_point(panel, p[0], p[1], 0) for p in points
        ]
        faces = [list(reversed(range(n))), list(range(n, 2 * n))]
        faces += [[i, (i + 1) % n, (i + 1) % n + n, i + n] for i in range(n)]
        face_uvs = []
        for face in faces:
            face_uvs.append([uv(panel["name"], *points[j % n]) for j in face])
        obj = mesh_object(
            name,
            vertices,
            faces,
            face_uvs,
            kind,
            min(geometry["bevel_mm"], height / 2),
            False,
        )
        obj["panel"] = panel["name"]
        obj["relief_height_mm"] = height
        return obj

    for element in spec["elements"]:
        panel = panels[element["panel"]]
        if element["kind"] == "braille":
            radius = element["dot_diameter_mm"] / 2
            height = element["dot_height_mm"]
            segments = geometry["braille_segments"]
            rings = geometry["braille_rings"]
            for index, (cx, cy) in enumerate(braille_points(element)):
                coords = [(cx, cy)]
                vertices = [panel_point(panel, cx, cy, height)]
                for ring in range(1, rings + 1):
                    angle = math.pi / 2 * ring / rings
                    r = radius * math.sin(angle)
                    z = height * math.cos(angle)
                    for j in range(segments):
                        u = cx + r * math.cos(2 * math.pi * j / segments)
                        v = cy + r * math.sin(2 * math.pi * j / segments)
                        coords.append((u, v))
                        vertices.append(panel_point(panel, u, v, z))
                coords.append((cx, cy))
                vertices.append(panel_point(panel, cx, cy, 0))
                bottom = len(vertices) - 1
                faces = [[0, 1 + (j + 1) % segments, 1 + j] for j in range(segments)]
                for ring in range(rings - 1):
                    a = 1 + ring * segments
                    b = a + segments
                    for j in range(segments):
                        k = (j + 1) % segments
                        faces.append([a + j, a + k, b + k, b + j])
                start = 1 + (rings - 1) * segments
                faces += [
                    [bottom, start + j, start + (j + 1) % segments]
                    for j in range(segments)
                ]
                face_uvs = [
                    [uv(panel["name"], *coords[i]) for i in face] for face in faces
                ]
                obj = mesh_object(
                    f"{element['id']}_{index:03}",
                    vertices,
                    faces,
                    face_uvs,
                    "braille",
                    smooth=True,
                )
                obj["panel"] = panel["name"]
                obj["dot_height_mm"] = height
                obj["dot_diameter_mm"] = element["dot_diameter_mm"]
        elif element["kind"] == "emboss":
            for i, (cx, cy, dx, dy) in enumerate(emboss_segments(element)):
                length = element["dash_length_mm"] / 2
                width = element["dash_width_mm"] / 2
                points = [
                    (cx + dx * a - dy * b, cy + dy * a + dx * b)
                    for a, b in [
                        (-length, -width),
                        (length, -width),
                        (length, width),
                        (-length, width),
                    ]
                ]
                relief_prism(
                    f"{element['id']}_{i:03}",
                    panel,
                    points,
                    element["height_mm"],
                    "emboss",
                )
        elif element["kind"] == "foil":
            x, y, w, h = element["bbox_mm"]
            r = element["corner_radius_mm"]
            points = []
            for cx, cy, start in [
                (x + r, y + r, math.pi),
                (x + w - r, y + r, 1.5 * math.pi),
                (x + w - r, y + h - r, 0),
                (x + r, y + h - r, 0.5 * math.pi),
            ]:
                for j in range(geometry["ring_segments"] + 1):
                    angle = start + math.pi / 2 * j / geometry["ring_segments"]
                    points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
            if element.get("shape") == "ellipse":
                count = 4 * geometry["ring_segments"]
                points = [
                    (
                        x + w / 2 + w / 2 * math.cos(2 * math.pi * i / count),
                        y + h / 2 + h / 2 * math.sin(2 * math.pi * i / count),
                    )
                    for i in range(count)
                ]
            relief_prism(
                element["id"], panel, points, geometry["foil_thickness_mm"], "foil"
            )
    # Modifier interpolation is not bitwise repeatable (bevel UVs differed by
    # one float32 ULP; boolean tooling also introduced an unused UV layer).
    # Project the final, already applied mesh analytically. No inherited UV data
    # or rounding participates, and all cameras use this same physical UV map.
    for obj in objects:
        mesh = obj.data
        panel = panels[obj["panel"]]
        while mesh.uv_layers:
            mesh.uv_layers.remove(mesh.uv_layers[0])
        layer = mesh.uv_layers.new(name="PanelUV")
        layer.active_render = True
        coordinates = []
        for vertex in mesh.vertices:
            delta = [vertex.co[i] * 1000 - panel["origin"][i] for i in range(3)]
            coordinates.append(
                tuple(
                    sum(delta[i] * panel[axis][i] for i in range(3))
                    for axis in ("u", "v", "normal")
                )
            )
        for face in mesh.polygons:
            own = panel["name"]
            side = 0
            mapping = board_mappings.get(obj.name)
            if mapping:
                (x, y, w, h), offset, thickness, own = mapping
                center = [
                    sum(coordinates[i][axis] for i in face.vertices)
                    / len(face.vertices)
                    for axis in range(3)
                ]
                # Closest source plane also maps the recessed crease walls onto
                # their top-panel ink, while carton edges retain separate UVs.
                distances = [
                    abs(center[2] - offset),
                    abs(center[2] - offset + thickness),
                    abs(center[1] - y),
                    abs(center[0] - x - w),
                    abs(center[1] - y - h),
                    abs(center[0] - x),
                ]
                side = min(range(len(distances)), key=distances.__getitem__)
            for index in face.loop_indices:
                u, v, z = coordinates[mesh.loops[index].vertex_index]
                region = own
                if mapping:
                    u, v = u - x, v - y
                    if side == 1:
                        region += "_inside"
                    elif side >= 2:
                        along = (u, v, w - u, h - v)[side - 2]
                        u, v = along, offset - z
                        region += f"_edge_{side - 2}"
                layer.data[index].uv = uv(region, u, v)
    api.context.view_layer.update()
    return objects
