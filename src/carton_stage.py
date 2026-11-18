"""Fixed studio and render contract; four cameras in one scene."""

import math
import os
import struct
import zlib
from pathlib import Path
from src.carton_materials import linear_rgba


def stable_png_bytes(data: bytes) -> bytes:
    """Drop volatile text/time chunks; retain every encoded pixel/color byte.

    Cycles always writes per-layer wall-clock times, even with use_stamp=False.
    This is lossless metadata serialization, with no pixel decode/re-encode.
    """
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise ValueError("Not a PNG")
    result = bytearray(signature)
    offset = len(signature)
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("Truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + length + 12
        if end > len(data):
            raise ValueError("Truncated PNG payload")
        kind = data[offset + 4 : offset + 8]
        checksum = struct.unpack_from(">I", data, end - 4)[0]
        if zlib.crc32(data[offset + 4 : end - 4]) != checksum:
            raise ValueError("PNG checksum mismatch")
        if kind not in {b"tEXt", b"iTXt", b"zTXt", b"tIME"}:
            result.extend(data[offset:end])
        offset = end
        if kind == b"IEND":
            if offset != len(data):
                raise ValueError("Data after PNG end")
            return bytes(result)
    raise ValueError("Missing PNG end")


def build_stage(api, spec):
    from mathutils import Vector

    scene = api.context.scene
    stage = spec["stage"]
    render = spec["render"]
    os.environ["OIDN_NUM_THREADS"] = str(render["denoising_threads"])
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1
    scene.unit_settings.length_unit = "MILLIMETERS"
    target = Vector([v / 1000 for v in stage["target_mm"]])
    world = api.data.worlds.new("Physical studio world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = linear_rgba(
        stage["world_color"]
    )
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = stage[
        "world_strength"
    ]
    scene.world = world
    floor = api.data.materials.new("Studio matte sweep")
    floor.use_nodes = True
    floor.node_tree.nodes["Principled BSDF"].inputs[
        "Base Color"
    ].default_value = linear_rgba(stage["background_color"])
    floor.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = spec[
        "materials"
    ]["paper_roughness"]
    api.ops.mesh.primitive_plane_add(
        size=stage["floor_size_mm"] / 1000, location=(0, 0, 0)
    )
    obj = api.context.object
    obj.name = "Studio floor / contact shadow"
    obj.data.materials.append(floor)
    obj.pass_index = 0
    profile = []
    radius = stage["sweep_radius_mm"]
    start = stage["sweep_start_mm"]
    for i in range(stage["sweep_segments"] + 1):
        angle = -math.pi / 2 + math.pi / 2 * i / stage["sweep_segments"]
        profile.append(
            (start + radius * math.cos(angle), radius + radius * math.sin(angle))
        )
    profile.append((start + radius, stage["sweep_height_mm"]))
    # A continuous circular sweep covers every camera direction in the same
    # physical studio; there is no camera-facing backdrop or per-view override.
    count = stage["sweep_radial_segments"]
    vertices = [
        (
            radius * math.cos(2 * math.pi * j / count) / 1000,
            radius * math.sin(2 * math.pi * j / count) / 1000,
            z / 1000,
        )
        for radius, z in profile
        for j in range(count)
    ]
    faces = [
        (
            i * count + j,
            (i + 1) * count + j,
            (i + 1) * count + (j + 1) % count,
            i * count + (j + 1) % count,
        )
        for i in range(len(profile) - 1)
        for j in range(count)
    ]
    mesh = api.data.meshes.new("Continuous studio sweep")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    sweep = api.data.objects.new("Studio cyclorama", mesh)
    api.context.collection.objects.link(sweep)
    mesh.materials.append(floor)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    for definition in stage["lights"]:
        data = api.data.lights.new(definition["name"], "AREA")
        data.energy = definition["energy_w"]
        data.shape = "DISK"
        data.size = definition["size_mm"] / 1000
        data.color = linear_rgba(definition["color"])[:3]
        light = api.data.objects.new(definition["name"], data)
        api.context.collection.objects.link(light)
        light.location = [v / 1000 for v in definition["position_mm"]]
        light.rotation_euler = (
            (target - light.location).to_track_quat("-Z", "Y").to_euler()
        )
    for definition in stage["cameras"]:
        camera_data = api.data.cameras.new(definition["name"])
        camera_data.lens = definition["lens_mm"]
        camera_data.sensor_width = definition["sensor_mm"]
        camera_data.sensor_fit = "HORIZONTAL"
        camera = api.data.objects.new("camera_" + definition["name"], camera_data)
        api.context.collection.objects.link(camera)
        yaw, pitch = map(
            math.radians, [definition["azimuth_deg"], definition["elevation_deg"]]
        )
        distance = definition["distance_mm"] / 1000
        camera.location = (
            target
            + Vector(
                (
                    -math.sin(yaw) * math.cos(pitch),
                    -math.cos(yaw) * math.cos(pitch),
                    math.sin(pitch),
                )
            )
            * distance
        )
        camera.rotation_euler = (
            (target - camera.location).to_track_quat("-Z", "Y").to_euler()
        )
        camera.rotation_euler.rotate_axis("Z", math.radians(definition["roll_deg"]))
        camera.data.clip_start = spec["geometry"]["board_thickness_mm"] / 1000
        camera.data.clip_end = stage["floor_size_mm"] / 1000
        camera.data.dof.use_dof = False
    scene.camera = api.data.objects["camera_hero"]
    scene.render.engine = render["engine"]
    scene.cycles.device = render["device"]
    scene.cycles.samples = render["samples"]
    scene.cycles.seed = render["seed"]
    scene.cycles.use_animated_seed = False
    scene.cycles.use_adaptive_sampling = render["adaptive_sampling"]
    scene.cycles.use_denoising = render["denoiser"] != "NONE"
    if scene.cycles.use_denoising:
        scene.cycles.denoiser = render["denoiser"]
        scene.cycles.denoising_use_gpu = render["denoising_device"] == "GPU"
    scene.cycles.max_bounces = render["max_bounces"]
    scene.cycles.transparent_max_bounces = render["transparent_bounces"]
    scene.view_settings.view_transform = render["view_transform"]
    scene.view_settings.look = render["look"]
    scene.view_settings.exposure = render["exposure"]
    scene.view_settings.gamma = render["gamma"]
    scene.render.resolution_x = scene.render.resolution_y = render["resolution"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = render["png_depth"]
    scene.render.image_settings.compression = render["png_compression"]
    scene.render.film_transparent = False
    scene.render.filter_size = render["filter_width"]
    scene.render.use_stamp = False
    scene.render.use_stamp_date = False
    scene.render.use_stamp_render_time = False
    if render["threads"]:
        scene.render.threads_mode = "FIXED"
        scene.render.threads = render["threads"]
    scene.view_layers[0].use_pass_object_index = True
    scene.frame_set(1)
    api.context.view_layer.update()
    return scene


def setup_mask_output(api, scene, directory, stem):
    # Blender 5 compositor API; unchanged beauty output plus a true IndexOB pass.
    group = api.data.node_groups.new(
        "Physical baseline diagnostics", "CompositorNodeTree"
    )
    scene.compositing_node_group = group
    group.interface.new_socket(
        name="Image", in_out="OUTPUT", socket_type="NodeSocketColor"
    )
    layers = group.nodes.new("CompositorNodeRLayers")
    layers.scene = scene
    output = group.nodes.new("NodeGroupOutput")
    group.links.new(layers.outputs["Image"], output.inputs["Image"])
    file = group.nodes.new("CompositorNodeOutputFile")
    file.directory = str(Path(directory))
    file.file_name = stem
    file.format.media_type = "IMAGE"
    file.format.file_format = "PNG"
    file.format.color_mode = "BW"
    file.format.color_depth = "8"
    file.save_as_render = False
    file.file_output_items.new("RGBA", "Mask")
    group.links.new(layers.outputs["Object Index"], file.inputs[0])
    scene.compositing_node_group = group
    return file
