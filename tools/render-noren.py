import json
import math
import os
import sys

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

ARGS = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
MODE = ARGS[0] if ARGS else "still"
OUT = ARGS[1] if len(ARGS) > 1 else "/tmp/noren-render"
SHAPE = ARGS[2] if len(ARGS) > 2 else "landscape"
SIZE = {"landscape": (1920, 1080), "portrait": (1080, 1920), "master": (6000, 3150)}[SHAPE]
EXPOSURE = float(os.environ.get("NOREN_EXPOSURE", "-0.7"))
HERE = os.path.dirname(os.path.abspath(__file__))
CLOTH_TEXTURE = os.path.join(HERE, "cloth.webp")

FPS = 30
WIND = float(os.environ.get("NOREN_WIND", "5"))
LOOP = 240
FADE = 30
WARMUP = 90
LAST = WARMUP + LOOP + FADE

ART = {
    "left": 43.6,
    "right": 561.4,
    "top": 33,
    "bottom": 496,
    "rod_y": 44,
    "rod_radius": 8,
    "rod_left": 22,
    "rod_right": 578,
    "pocket_bottom": 51,
    "slit_top": 128,
    "slits": [214.2, 385.8],
}

WIDTH = 0.9
SCALE = WIDTH / (ART["right"] - ART["left"])
ROD_Y = 0.4
ROD_RADIUS = ART["rod_radius"] * SCALE
COLS = 72
POCKET_ROWS = 9
NOREN_LENGTH = 1.2
LETTER_MIDDLE = 282
ABOVE = (140, 215)
BELOW = (360, 470)
EXTRA = NOREN_LENGTH - (ART["bottom"] - ART["rod_y"]) * SCALE
EXTRA_ABOVE = (ART["slit_top"] + ART["bottom"] - 2 * LETTER_MIDDLE) * SCALE / 2 + EXTRA / 2
BANDS = [
    (ABOVE[0], ABOVE[1], 1 + EXTRA_ABOVE / ((ABOVE[1] - ABOVE[0]) * SCALE)),
    (BELOW[0], BELOW[1], 1 + (EXTRA - EXTRA_ABOVE) / ((BELOW[1] - BELOW[0]) * SCALE)),
]

FLOOR = ROD_Y - 1.75
HALF_OPENING = 0.5
POST = 0.1
DEPTH = 0.1
LINTEL_Y = ROD_Y + 0.035
LINTEL_H = 0.05
BEAM_Y = ROD_Y + 0.42
BACK = -4.0
SIDE = 1.8


def v(x, y, z):
    return Vector((x, -z, y))


def svg_x(c):
    return ART["left"] + c * (ART["right"] - ART["left"]) / (COLS - 1)


def world_x(x):
    return (x - 300) * SCALE


def drop(y):
    total = (y - ART["rod_y"]) * SCALE
    for start, end, factor in BANDS:
        inside = min(max(y, start), end) - start
        total += inside * SCALE * (factor - 1)
    return total


def world_y(y):
    return ROD_Y - drop(y)


def svg_from_world(wy):
    low = ART["top"]
    high = ART["bottom"]
    for _ in range(60):
        middle = (low + high) / 2
        if world_y(middle) > wy:
            low = middle
        else:
            high = middle
    return (low + high) / 2


BODY_TOP = world_y(ART["pocket_bottom"])
BODY_BOTTOM = world_y(ART["bottom"])
BODY_ROWS = round((BODY_TOP - BODY_BOTTOM) / (WIDTH / (COLS - 1)))
ROWS = POCKET_ROWS + BODY_ROWS


def svg_y(r):
    if r < POCKET_ROWS:
        return ART["top"] + r * (ART["pocket_bottom"] - ART["top"]) / (POCKET_ROWS - 1)
    return svg_from_world(BODY_TOP - (r - POCKET_ROWS + 1) * (BODY_TOP - BODY_BOTTOM) / BODY_ROWS)


def slit_between(c0, c1):
    return any(svg_x(c0) <= s < svg_x(c1) for s in ART["slits"])


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for device in prefs.devices:
        device.use = device.type == "OPTIX"
    scene.cycles.samples = 160
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = "OPTIX"
    scene.cycles.max_bounces = 10
    scene.cycles.transmission_bounces = 8
    scene.cycles.caustics_reflective = False
    scene.cycles.caustics_refractive = False
    scene.render.resolution_x = SIZE[0]
    scene.render.resolution_y = SIZE[1]
    scene.render.resolution_percentage = int(os.environ.get("NOREN_PERCENT", "100"))
    scene.render.fps = FPS
    scene.render.use_motion_blur = True
    scene.render.motion_blur_shutter = 0.5
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = EXPOSURE
    scene.frame_start = 1
    scene.frame_end = LAST
    return scene


def node_material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    return mat, mat.node_tree.nodes, mat.node_tree.links


def wood(name, base, dark, along):
    mat, nodes, links = node_material(name)
    bsdf = nodes["Principled BSDF"]
    coord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    wave = nodes.new("ShaderNodeTexWave")
    wave.wave_type = "BANDS"
    wave.bands_direction = "Z" if along == "x" else "X"
    wave.inputs["Scale"].default_value = 22
    wave.inputs["Distortion"].default_value = 1.6
    wave.inputs["Detail"].default_value = 6
    wave.inputs["Detail Scale"].default_value = 3
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 40
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*dark, 1)
    ramp.color_ramp.elements[1].color = (*base, 1)
    mix = nodes.new("ShaderNodeMath")
    mix.operation = "MULTIPLY_ADD"
    mix.inputs[1].default_value = 0.45
    mix.inputs[2].default_value = 0.35
    links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], wave.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(wave.outputs["Fac"], mix.inputs[0])
    links.new(mix.outputs[0], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.05
    links.new(wave.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    bsdf.inputs["Roughness"].default_value = 0.58
    return mat


def plaster():
    mat, nodes, links = node_material("plaster")
    bsdf = nodes["Principled BSDF"]
    blotch = nodes.new("ShaderNodeTexNoise")
    blotch.inputs["Scale"].default_value = 2.5
    blotch.inputs["Detail"].default_value = 6
    tone = nodes.new("ShaderNodeValToRGB")
    tone.color_ramp.elements[0].position = 0.35
    tone.color_ramp.elements[1].position = 0.7
    tone.color_ramp.elements[0].color = (0.79, 0.74, 0.64, 1)
    tone.color_ramp.elements[1].color = (0.85, 0.8, 0.7, 1)
    links.new(blotch.outputs["Fac"], tone.inputs["Fac"])
    links.new(tone.outputs["Color"], bsdf.inputs["Base Color"])
    rough = nodes.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = 0.82
    rough.inputs["To Max"].default_value = 0.97
    links.new(blotch.outputs["Fac"], rough.inputs["Value"])
    links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 180
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.03
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def tatami():
    mat, nodes, links = node_material("tatami")
    bsdf = nodes["Principled BSDF"]
    wave = nodes.new("ShaderNodeTexWave")
    wave.bands_direction = "X"
    wave.inputs["Scale"].default_value = 260
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.46, 0.41, 0.24, 1)
    ramp.color_ramp.elements[1].color = (0.6, 0.55, 0.33, 1)
    links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.15
    links.new(wave.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    bsdf.inputs["Roughness"].default_value = 0.75
    return mat


def paper():
    mat, nodes, links = node_material("paper")
    out = nodes["Material Output"]
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.92, 0.89, 0.82, 1)
    bsdf.inputs["Roughness"].default_value = 0.9
    translucent = nodes.new("ShaderNodeBsdfTranslucent")
    translucent.inputs["Color"].default_value = (1.0, 0.93, 0.8, 1)
    mix = nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.3
    links.new(bsdf.outputs["BSDF"], mix.inputs[1])
    links.new(translucent.outputs["BSDF"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def cloth_material():
    mat, nodes, links = node_material("noren")
    out = nodes["Material Output"]
    bsdf = nodes["Principled BSDF"]
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(CLOTH_TEXTURE)
    tex.interpolation = "Cubic"
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.88
    bsdf.inputs["Sheen Weight"].default_value = 0.35
    bsdf.inputs["Sheen Roughness"].default_value = 0.6

    weave = nodes.new("ShaderNodeTexBrick")
    weave.inputs["Scale"].default_value = 900
    weave.inputs["Mortar Size"].default_value = 0.01
    coord = nodes.new("ShaderNodeTexCoord")
    links.new(coord.outputs["UV"], weave.inputs["Vector"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.12
    links.new(weave.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    translucent = nodes.new("ShaderNodeBsdfTranslucent")
    boost = nodes.new("ShaderNodeVectorMath")
    boost.operation = "MULTIPLY"
    boost.inputs[1].default_value = (1.0, 1.0, 1.1)
    links.new(tex.outputs["Color"], boost.inputs[0])
    links.new(boost.outputs["Vector"], translucent.inputs["Color"])

    fabric = nodes.new("ShaderNodeMixShader")
    fabric.inputs["Fac"].default_value = 0.12
    links.new(bsdf.outputs["BSDF"], fabric.inputs[1])
    links.new(translucent.outputs["BSDF"], fabric.inputs[2])

    clear = nodes.new("ShaderNodeBsdfTransparent")
    cut = nodes.new("ShaderNodeMixShader")
    links.new(tex.outputs["Alpha"], cut.inputs["Fac"])
    links.new(clear.outputs["BSDF"], cut.inputs[1])
    links.new(fabric.outputs["Shader"], cut.inputs[2])
    links.new(cut.outputs["Shader"], out.inputs["Surface"])
    return mat


def box(w, h, d, x, y, z, mat, name="box"):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1)
    bmesh.ops.scale(bm, vec=(w, d, h), verts=bm.verts)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = v(x, y, z)
    obj.data.materials.append(mat)
    bevel = obj.modifiers.new("bevel", "BEVEL")
    bevel.width = min(0.004, min(w, h, d) * 0.25)
    bevel.segments = 2
    bpy.context.collection.objects.link(obj)
    return obj


def flat(name, color, roughness, metallic=0.0):
    mat, nodes, _ = node_material(name)
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def planks():
    mat, nodes, links = node_material("planks")
    bsdf = nodes["Principled BSDF"]
    coord = nodes.new("ShaderNodeTexCoord")
    grain = nodes.new("ShaderNodeTexWave")
    grain.bands_direction = "Y"
    grain.inputs["Scale"].default_value = 14
    grain.inputs["Distortion"].default_value = 8
    grain.inputs["Detail"].default_value = 5
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.26, 0.15, 0.07, 1)
    ramp.color_ramp.elements[1].color = (0.4, 0.24, 0.11, 1)
    seams = nodes.new("ShaderNodeTexBrick")
    seams.inputs["Scale"].default_value = 1
    seams.inputs["Brick Width"].default_value = 1.8
    seams.inputs["Row Height"].default_value = 0.13
    seams.inputs["Mortar Size"].default_value = 0.0025
    seams.inputs["Color1"].default_value = (1, 1, 1, 1)
    seams.inputs["Color2"].default_value = (0.92, 0.92, 0.92, 1)
    seams.inputs["Mortar"].default_value = (0.25, 0.25, 0.25, 1)
    multiply = nodes.new("ShaderNodeVectorMath")
    multiply.operation = "MULTIPLY"
    links.new(coord.outputs["Object"], grain.inputs["Vector"])
    links.new(coord.outputs["Object"], seams.inputs["Vector"])
    links.new(grain.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], multiply.inputs[0])
    links.new(seams.outputs["Color"], multiply.inputs[1])
    links.new(multiply.outputs["Vector"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.32
    bsdf.inputs["Coat Weight"].default_value = 0.25
    return mat


def karakami():
    mat, nodes, links = node_material("karakami")
    bsdf = nodes["Principled BSDF"]
    pattern = nodes.new("ShaderNodeTexVoronoi")
    pattern.inputs["Scale"].default_value = 38
    pattern.feature = "DISTANCE_TO_EDGE"
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.02
    ramp.color_ramp.elements[1].position = 0.05
    ramp.color_ramp.elements[0].color = (0.84, 0.8, 0.7, 1)
    ramp.color_ramp.elements[1].color = (0.81, 0.77, 0.67, 1)
    links.new(pattern.outputs["Distance"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    shine = nodes.new("ShaderNodeMapRange")
    shine.inputs["From Min"].default_value = 0.02
    shine.inputs["From Max"].default_value = 0.06
    shine.inputs["To Min"].default_value = 0.35
    shine.inputs["To Max"].default_value = 0.85
    links.new(pattern.outputs["Distance"], shine.inputs["Value"])
    links.new(shine.outputs["Result"], bsdf.inputs["Roughness"])
    return mat


def build_room():
    honey = wood("honey", (0.34, 0.21, 0.11), (0.22, 0.13, 0.065), "z")
    honey_across = wood("honey_across", (0.34, 0.21, 0.11), (0.22, 0.13, 0.065), "x")
    dark = wood("dark", (0.25, 0.14, 0.07), (0.17, 0.09, 0.04), "x")
    lacquer = flat("lacquer", (0.02, 0.018, 0.016), 0.22)
    pull = flat("hikite", (0.12, 0.09, 0.05), 0.35, 0.6)
    wall = plaster()
    mat_paper = paper()
    floor = tatami()
    boards = planks()
    paper_door = karakami()

    lintel_top = LINTEL_Y + LINTEL_H
    post_h = lintel_top - FLOOR
    post_x = HALF_OPENING + POST / 2
    outer = HALF_OPENING + POST
    run = 7.5

    def shoji(width, height, x, y, z, cols, rows):
        pane = box(width, height, 0.003, x, y, z, mat_paper, "paper")
        bar = 0.012
        frame = 0.03
        depth = 0.018
        front = z + depth / 2 + 0.003
        for i in range(1, cols):
            box(bar, height, depth, x - width / 2 + i * width / cols, y, front, honey, "kumiko")
        for j in range(1, rows):
            box(width, bar, depth, x, y - height / 2 + j * height / rows, front, honey_across, "kumiko")
        box(frame, height, depth * 1.6, x - width / 2 + frame / 2, y, front, honey, "frame")
        box(frame, height, depth * 1.6, x + width / 2 - frame / 2, y, front, honey, "frame")
        box(width, frame, depth * 1.6, x, y + height / 2 - frame / 2, front, honey_across, "frame")
        box(width, frame * 2.4, depth * 1.6, x, y - height / 2 + frame * 1.2, front, honey_across, "frame")
        return pane

    def fusuma(width, height, x, y, z, pull_side):
        box(width, height, 0.02, x, y, z, paper_door, "fusuma")
        rim = 0.018
        front = z + 0.006
        box(rim, height, 0.026, x - width / 2 + rim / 2, y, front, lacquer, "fuchi")
        box(rim, height, 0.026, x + width / 2 - rim / 2, y, front, lacquer, "fuchi")
        box(width, rim, 0.026, x, y + height / 2 - rim / 2, front, lacquer, "fuchi")
        box(width, rim, 0.026, x, y - height / 2 + rim / 2, front, lacquer, "fuchi")
        bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.006, vertices=48)
        knob = bpy.context.active_object
        knob.rotation_euler = (math.radians(90), 0, 0)
        knob.location = v(x + pull_side * (width / 2 - 0.08), y - 0.05, z + 0.011)
        knob.data.materials.append(pull)

    door_h = post_h - 0.06
    door_y = FLOOR + door_h / 2 + 0.03
    for side in (-1, 1):
        box(POST, post_h, DEPTH, side * post_x, FLOOR + post_h / 2, 0, honey, "post")
        box(POST, BEAM_Y - FLOOR, DEPTH, side * (outer + 1.07), FLOOR + (BEAM_Y - FLOOR) / 2, 0, honey, "post")
        shoji(1.0, door_h, side * (outer + 0.52), door_y, -0.02, 4, 8)
        box(0.02, post_h + 0.4, 0.62, side * (outer + 1.13), FLOOR + post_h / 2, -0.32, wall, "side room")
        start = outer + 1.12
        fusuma(0.86, door_h, side * (start + 0.43), door_y, -0.012, -side)
        fusuma(0.86, door_h, side * (start + 1.27), door_y, -0.03, side)
        box(POST, BEAM_Y - FLOOR, DEPTH, side * (start + 1.75), FLOOR + (BEAM_Y - FLOOR) / 2, 0, honey, "post")
        box(0.02, post_h, 0.6, side * (start + 0.85), FLOOR + post_h / 2, -0.35, wall, "behind fusuma")

    box(run, LINTEL_H, DEPTH, 0, LINTEL_Y + LINTEL_H / 2, 0, honey_across, "kamoi")
    box(run, BEAM_Y - lintel_top, 0.04, 0, lintel_top + (BEAM_Y - lintel_top) / 2, -0.03, wall, "band")
    box(run, 0.08, 0.12, 0, BEAM_Y + 0.04, 0.01, honey_across, "nageshi")
    box(run, 0.8, 0.04, 0, BEAM_Y + 0.48, -0.03, wall, "upper wall")
    box(run, 0.04, DEPTH, 0, FLOOR + 0.02, 0, dark, "shikii")

    hall_ceiling = BEAM_Y + 0.5
    box(run, 0.03, 2.6, 0, FLOOR - 0.015, 1.35, boards, "hallway floor")
    box(run, 0.02, 2.6, 0, hall_ceiling, 1.35, honey_across, "hallway ceiling")
    box(run, 0.06, 0.06, 0, hall_ceiling - 0.04, 0.05, honey_across, "mawaribuchi")

    ceiling = ROD_Y + 0.62
    box(SIDE * 2, 0.02, -BACK, 0, FLOOR, BACK / 2, floor, "back floor")
    heri = flat("heri", (0.05, 0.06, 0.045), 0.6)
    for x in (-0.9, 0, 0.9):
        box(0.03, 0.004, -BACK, x, FLOOR + 0.011, BACK / 2, heri, "heri")
    for z in (-0.95, -1.85):
        box(SIDE * 2, 0.004, 0.03, 0, FLOOR + 0.011, z, heri, "heri")
    box(SIDE * 2, 0.02, -BACK, 0, ceiling, BACK / 2, honey_across, "ceiling")
    shade = flat("room wall", (0.32, 0.27, 0.21), 0.9)
    box(0.02, ceiling - FLOOR, -BACK, -SIDE, (ceiling + FLOOR) / 2, BACK / 2, shade, "wall")
    box(0.02, ceiling - FLOOR, -BACK, SIDE, (ceiling + FLOOR) / 2, BACK / 2, shade, "wall")
    box(SIDE * 2, ceiling - FLOOR, 0.02, 0, (ceiling + FLOOR) / 2, BACK - 0.012, shade, "back wall")
    for side in (-1, 1):
        for z in (-0.05, BACK / 2, BACK + 0.05):
            box(POST, ceiling - FLOOR, POST, side * (SIDE - 0.05), (ceiling + FLOOR) / 2, z, honey, "room post")
        box(0.05, LINTEL_H, -BACK, side * (SIDE - 0.035), LINTEL_Y + LINTEL_H / 2, BACK / 2, honey_across, "room kamoi")
        box(0.07, 0.08, -BACK, side * (SIDE - 0.045), BEAM_Y + 0.04, BACK / 2, honey_across, "room nageshi")
    box(SIDE * 2, 0.08, 0.07, 0, BEAM_Y + 0.04, BACK + 0.045, honey_across, "room nageshi")


    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    nodes = world.node_tree.nodes
    sky = nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_disc = False
    sky.sun_elevation = math.radians(35)
    nodes["Background"].inputs["Strength"].default_value = 0.35
    balance = nodes.new("ShaderNodeVectorMath")
    balance.operation = "MULTIPLY"
    balance.inputs[1].default_value = (1.25, 1.0, 0.72)
    world.node_tree.links.new(sky.outputs["Color"], balance.inputs[0])
    world.node_tree.links.new(balance.outputs["Vector"], nodes["Background"].inputs["Color"])
    bpy.context.scene.world = world
    bpy.context.scene.world = world

    rod_mat = wood("rod", (0.3, 0.18, 0.09), (0.2, 0.12, 0.06), "x")
    rod_len = (ART["rod_right"] - ART["rod_left"]) * SCALE
    bpy.ops.mesh.primitive_cylinder_add(radius=ROD_RADIUS, depth=rod_len, vertices=48)
    rod = bpy.context.active_object
    rod.name = "rod"
    rod.rotation_euler = (0, math.radians(90), 0)
    rod.location = v(world_x((ART["rod_left"] + ART["rod_right"]) / 2), ROD_Y, 0)
    rod.data.materials.append(rod_mat)
    bpy.ops.object.shade_smooth()
    for side in (-1, 1):
        box(0.022, 0.034, 0.03, side * (HALF_OPENING - 0.011), ROD_Y + 0.006, 0, dark, "bracket")


FONTS = os.path.expanduser("~/.local/share/fonts/ajito")


def gilt():
    mat, nodes, _ = node_material("gilt")
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.78, 0.55, 0.24, 1)
    bsdf.inputs["Metallic"].default_value = 1
    bsdf.inputs["Roughness"].default_value = 0.38
    return mat


def carving(text, font, size, y, front, mat, spacing=1.0):
    curve = bpy.data.curves.new(text, "FONT")
    curve.body = text
    curve.font = bpy.data.fonts.load(os.path.join(FONTS, font))
    curve.size = size
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.space_character = spacing
    curve.extrude = 0.005
    obj = bpy.data.objects.new(text, curve)
    obj.location = v(0, y, front - 0.0015)
    obj.rotation_euler = (math.radians(90), 0, 0)
    obj.data.materials.append(mat)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    for other in bpy.context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.ops.object.convert(target="MESH")
    return bpy.context.view_layer.objects.active


def build_sign():
    band_middle = (LINTEL_Y + LINTEL_H + BEAM_Y) / 2
    width = 0.98
    height = 0.24
    thick = 0.035
    back = -0.01
    board_z = back + thick / 2 + 0.006
    front = board_z + thick / 2
    keyaki = wood("keyaki", (0.16, 0.09, 0.045), (0.09, 0.05, 0.025), "x")
    board = box(width, height, thick, 0, band_middle, board_z, keyaki, "kanban")
    for side in (-1, 1):
        box(0.012, 0.03, 0.008, side * (width / 2 - 0.06), band_middle + height / 2 + 0.006, board_z, keyaki, "hanger")

    gold = gilt()
    cutters = bpy.data.collections.new("carving")
    bpy.context.scene.collection.children.link(cutters)
    for obj in (
        carving("準備中", "ShipporiMinchoB1-Bold.ttf", 0.05, band_middle + 0.058, front, gold, 1.35),
        carving("Opening January 2027", "ShipporiMinchoB1-ExtraBold.ttf", 0.085, band_middle - 0.03, front, gold),
    ):
        for collection in obj.users_collection:
            collection.objects.unlink(obj)
        cutters.objects.link(obj)
        obj.hide_render = True

    carve = board.modifiers.new("carve", "BOOLEAN")
    carve.operation = "DIFFERENCE"
    carve.operand_type = "COLLECTION"
    carve.collection = cutters
    carve.solver = "EXACT"
    carve.material_mode = "TRANSFER"


def build_cloth():
    mesh = bpy.data.meshes.new("noren")
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    radius = ROD_RADIUS + 0.004
    first = svg_y(0)
    end = svg_y(POCKET_ROWS - 1)
    verts = []

    for r in range(ROWS):
        row = []
        for c in range(COLS):
            x = world_x(svg_x(c))
            if r < POCKET_ROWS:
                angle = (svg_y(r) - first) / (end - first) * math.pi
                gather = 1 + 0.1 * max(0, math.sin(c * 1.7) * math.sin(c * 0.53 + 1))
                y = ROD_Y + math.cos(angle) * radius * gather
                z = math.sin(angle) * radius * gather
            else:
                y = world_y(svg_y(r))
                panel = sum(1 for slit in ART["slits"] if svg_x(c) > slit)
                phase = (0.3, 1.9, 4.1)[panel]
                depth = min(1, (ROD_Y - y) / 0.25)
                z = depth * (0.011 * math.sin(x * 31 + phase) + 0.005 * math.sin(x * 67 + 2 * phase))
            row.append(bm.verts.new(v(x, y, z)))
        verts.append(row)

    bm.verts.ensure_lookup_table()
    for r in range(ROWS - 1):
        for c in range(COLS - 1):
            if slit_between(c, c + 1) and svg_y(r + 1) > ART["slit_top"]:
                continue
            quad = [verts[r][c], verts[r + 1][c], verts[r + 1][c + 1], verts[r][c + 1]]
            face = bm.faces.new(quad)
            for loop, (rr, cc) in zip(face.loops, [(r, c), (r + 1, c), (r + 1, c + 1), (r, c + 1)]):
                u = cc / (COLS - 1)
                vv = 1 - (svg_y(rr) - ART["top"]) / (ART["bottom"] - ART["top"])
                loop[uv_layer].uv = (u, vv)

    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("noren", mesh)
    bpy.context.collection.objects.link(obj)
    for poly in mesh.polygons:
        poly.use_smooth = True
    obj.data.materials.append(cloth_material())

    group = obj.vertex_groups.new(name="pin")
    group.add([r * COLS + c for r in range(POCKET_ROWS) for c in range(COLS)], 1.0, "REPLACE")

    sub = obj.modifiers.new("detail", "SUBSURF")
    cloth = obj.modifiers.new("cloth", "CLOTH")
    obj.modifiers.move(1, 0)
    settings = cloth.settings
    settings.quality = 12
    settings.mass = float(os.environ.get("NOREN_MASS", "0.002"))
    settings.tension_stiffness = 15
    settings.compression_stiffness = 15
    settings.shear_stiffness = 15
    settings.bending_stiffness = 1.0
    settings.tension_damping = 5
    settings.compression_damping = 5
    settings.shear_damping = 5
    settings.bending_damping = 0.5
    settings.air_damping = 1
    settings.vertex_group_mass = "pin"
    cloth.collision_settings.use_collision = False
    cloth.point_cache.frame_start = 1
    cloth.point_cache.frame_end = LAST
    sub.levels = 0
    sub.render_levels = 2
    return obj


def build_wind():
    bpy.ops.object.effector_add(type="WIND", location=v(0, ROD_Y - 0.3, -1.2))
    wind = bpy.context.active_object
    wind.rotation_euler = (math.radians(90), 0, 0)
    field = wind.field
    field.flow = 0.6
    field.noise = 0.4
    field.seed = 7
    field.shape = "PLANE"
    period = LOOP
    for frame in range(1, LAST + 1, 4):
        t = (frame - WARMUP) / period * 2 * math.pi
        field.strength = WIND * (4 + 14 * math.sin(t) + 5 * math.sin(2 * t + 0.7))
        field.keyframe_insert("strength", frame=frame)

    bpy.ops.object.effector_add(type="TURBULENCE", location=v(0, 0, 0))
    turbulence = bpy.context.active_object.field
    turbulence.strength = 2.5
    turbulence.size = 0.35
    turbulence.flow = 0.3


def build_camera(scene):
    cam_data = bpy.data.cameras.new("camera")
    cam_data.sensor_fit = "VERTICAL"
    cam_data.sensor_height = 24
    aspect = SIZE[0] / SIZE[1]
    dist = 1.9 if aspect > 1 else 2.3
    eye = FLOOR + 1.25
    top = BEAM_Y + 0.1
    bottom = FLOOR - 0.05
    if aspect < 1:
        top = BEAM_Y + 0.35
        bottom = FLOOR - 0.25
    if SHAPE == "master":
        dist = 1.9
        top = BEAM_Y + 0.45
        bottom = FLOOR - 0.4
    cam_data.lens = 12 / ((top - bottom) / 2 / dist)
    visible_h = top - bottom
    cam_data.shift_y = ((top + bottom) / 2 - eye) / max(visible_h, visible_h * aspect)
    cam_data.dof.use_dof = True
    cam_data.dof.aperture_fstop = 4
    cam_data.dof.focus_distance = dist
    cam = bpy.data.objects.new("camera", cam_data)
    cam.location = v(0, eye, dist)
    cam.rotation_euler = (math.radians(90), 0, 0)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    return cam


def band_position(scene, cam):
    bpy.context.view_layer.update()
    lintel_top = LINTEL_Y + LINTEL_H
    a = world_to_camera_view(scene, cam, v(0, lintel_top, 0))
    b = world_to_camera_view(scene, cam, v(0, BEAM_Y, 0))
    left = world_to_camera_view(scene, cam, v(-0.75, BEAM_Y + 0.12, 0))
    right = world_to_camera_view(scene, cam, v(0.75, FLOOR - 0.1, 0))
    return {
        "bandTop": 1 - b.y,
        "bandBottom": 1 - a.y,
        "safe": {"left": left.x, "top": 1 - left.y, "right": right.x, "bottom": 1 - right.y},
    }


def main():
    scene = reset()
    build_room()
    build_sign()
    build_cloth()
    build_wind()
    cam = build_camera(scene)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"layout-{SHAPE}.json"), "w") as f:
        json.dump(band_position(scene, cam), f)

    if MODE == "sim":
        noren = bpy.data.objects["noren"]
        probe = (ROWS - 1) * COLS + COLS // 2
        rest = noren.data.vertices[probe].co.copy()
        for frame in range(1, LAST + 1):
            scene.frame_set(frame)
            if frame % 15 == 0:
                moved = noren.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices
                co = moved[probe * 1].co if len(moved) == len(noren.data.vertices) else None
                print("SIM", frame, None if co is None else tuple(round(a, 3) for a in (co - rest)))
        return

    if MODE == "still":
        for obj in bpy.data.objects:
            if obj.field and obj.field.type in ("WIND", "TURBULENCE"):
                obj.animation_data_clear()
                obj.field.strength = 0
        for frame in range(1, 61):
            scene.frame_set(frame)
        scene.render.filepath = os.path.join(OUT, f"still-{SHAPE}.png")
        bpy.ops.render.render(write_still=True)
        return

    scene.frame_start = WARMUP
    scene.frame_end = LAST
    for frame in range(1, WARMUP):
        scene.frame_set(frame)
    scene.render.filepath = os.path.join(OUT, "frame-")
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(animation=True)


main()
