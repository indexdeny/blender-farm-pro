"""Shared physical shader. All image reads are verified generated maps."""

from src.carton_spec import resolve_asset, verify_generated


def linear_rgba(value):
    rgb = [int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(
        v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb
    ) + (1,)


def build_material(api, spec, artwork):
    verify_generated(artwork)
    material = api.data.materials.new("Physical carton / shared masked PBR")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    settings = spec["materials"]
    images = {}
    for name, record in artwork["maps"].items():
        image = api.data.images.load(
            str(resolve_asset(record["path"], generated=True)), check_existing=True
        )
        image.colorspace_settings.name = "sRGB" if name == "base_color" else "Non-Color"
        image["artwork_sha256"] = record["sha256"]
        texture = nodes.new("ShaderNodeTexImage")
        texture.name = "generated_" + name
        texture.image = image
        texture.interpolation = "Linear"
        texture.extension = "EXTEND"
        images[name] = texture
    for name, socket in [
        ("base_color", "Base Color"),
        ("roughness", "Roughness"),
        ("metallic", "Metallic"),
    ]:
        links.new(images[name].outputs["Color"], shader.inputs[socket])
    normal = nodes.new("ShaderNodeNormalMap")
    links.new(images["normal"].outputs["Color"], normal.inputs["Color"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Distance"].default_value = settings["grain_height_mm"] / 1000
    links.new(images["height"].outputs["Color"], bump.inputs["Height"])
    links.new(normal.outputs["Normal"], bump.inputs["Normal"])
    links.new(bump.outputs["Normal"], shader.inputs["Normal"])
    shader.inputs["IOR"].default_value = settings["ior"]
    shader.inputs["Coat Roughness"].default_value = settings["coat_roughness"]
    shader.inputs["Specular IOR Level"].default_value = settings["specular_ior_level"]
    coated = nodes.new("ShaderNodeMath")
    coated.operation = "LESS_THAN"
    coated.inputs[1].default_value = (
        settings["paper_roughness"] + settings["ink_roughness"]
    ) / 2
    links.new(images["roughness"].outputs["Color"], coated.inputs[0])
    coat_weight = nodes.new("ShaderNodeMath")
    coat_weight.operation = "MULTIPLY"
    coat_weight.inputs[1].default_value = settings["coat_weight"]
    links.new(coated.outputs[0], coat_weight.inputs[0])
    links.new(coat_weight.outputs[0], shader.inputs["Coat Weight"])
    anisotropy = nodes.new("ShaderNodeMath")
    anisotropy.operation = "MULTIPLY"
    anisotropy.inputs[1].default_value = settings["anisotropy"]
    links.new(images["metallic"].outputs["Color"], anisotropy.inputs[0])
    links.new(anisotropy.outputs[0], shader.inputs["Anisotropic"])
    material["spec_sha256"] = artwork["spec_sha256"]
    return material
