"""
Qboltz — "Light Scan" scenes for Blender (tested on 5.2, written for 4.2 LTS and newer).

A floating light scans a field of round, drifting particles, finds the right spot,
becomes one light and floats away.

Two variants:
  lighthouse  Option 1. Beams sweep the field slowly like a lighthouse, swing onto one
              cluster, the light flies there, flares, folds into one star and floats away.
              12 s.
  search      Option 2. The light fires a narrow fan of beams at one candidate cluster
              after another. Each one pulses, gets rejected, dims and drifts off. It locks on
              the right one, absorbs it and glides away on an arc. 15 s.

Run it
  In Blender: Scripting workspace > Open this file > set VARIANT below > Run Script.
  Every run builds a new scene ("QB_Lighthouse" / "QB_Search") and switches to it,
  replacing the previous build of that variant. Your other scenes are left alone.

  From a terminal:
    blender --background --python qboltz_light_scan.py -- --variant search --render
  Options after "--":
    --variant lighthouse|search   which scene to build
    --engine eevee|cycles         render engine (default: eevee)
    --scale 50                    resolution percentage (default: 100 -> 1920x1080)
    --samples N                   render samples
    --render                      render the animation to --output
    --still FRAME                 render a single frame to --output
    --output PATH                 output path (default: //renders/qboltz_<variant>_)
    --save PATH.blend             save the generated .blend

Everything glows through emission shaders plus the compositor's Glare node (fog glow + streaks
for the star glint), so it looks the same in EEVEE and Cycles. Particles are real ico-spheres
instanced by Geometry Nodes and drift on 4D noise, so they stay perfectly round.
"""

import math
import random
import sys

import bpy  # before bmesh, so it also works with the pip `bpy` module
import bmesh
from mathutils import Quaternion, Vector

VARIANT = "answer"  # "answer" (the final one), "lighthouse" (option 1) or "search" (option 2)
ENGINE = "eevee"        # "eevee" or "cycles"
RES_X, RES_Y = 1920, 1080
FPS = 24
SEED = 7

# Look
PARTICLE_COLOR = (0.82, 0.88, 1.0)
BEAM_HALO_COLOR = (0.80, 0.85, 1.0)
CONE_COLOR = (0.40, 0.46, 0.95)  # the blue-violet scan haze
CONE_HALF_ANGLE = math.radians(16)


# --------------------------------------------------------------------------- helpers

def F(t):
    """Seconds -> frame number (the timeline starts at frame 1)."""
    return 1 + int(round(t * FPS))


def smooth(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def smoother(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * u * (u * (6 * u - 15) + 10)


def qbez(a, b, c, s):
    """Quadratic bezier point."""
    a, b, c = Vector(a), Vector(b), Vector(c)
    return (1 - s) ** 2 * a + 2 * (1 - s) * s * b + s * s * c


class Interp:
    """Temporarily change the interpolation of newly inserted keyframes."""

    def __init__(self, kind):
        self.kind = kind

    def __enter__(self):
        self.edit = bpy.context.preferences.edit
        self.prev = self.edit.keyframe_new_interpolation_type
        self.edit.keyframe_new_interpolation_type = self.kind

    def __exit__(self, *exc):
        self.edit.keyframe_new_interpolation_type = self.prev


def key_val(node, t, v):
    """Keyframe a Value node at time t (seconds)."""
    node.outputs[0].default_value = v
    node.outputs[0].keyframe_insert("default_value", frame=F(t))


def key_loc(obj, t, loc):
    obj.location = loc
    obj.keyframe_insert("location", frame=F(t))


def key_scale(obj, t, s):
    obj.scale = (s, s, s) if isinstance(s, (int, float)) else s
    obj.keyframe_insert("scale", frame=F(t))


def key_quat(obj, t, q):
    # stay on the same hemisphere as the previous key so interpolation takes the short way
    prev = obj.get("_qprev")
    if prev is not None and Quaternion(prev).dot(q) < 0:
        q = -q
    obj["_qprev"] = list(q)
    obj.rotation_quaternion = q
    obj.keyframe_insert("rotation_quaternion", frame=F(t))


def direction_quat(d):
    return Vector(d).normalized().to_track_quat("Z", "Y")


def link(scene, obj, parent=None):
    scene.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def new_empty(scene, name, parent=None, size=0.3):
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = size
    e.empty_display_type = "PLAIN_AXES"
    return link(scene, e, parent)


def mesh_object(scene, name, build, parent=None, mat=None):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    if mat:
        me.materials.append(mat)
    # pure emitters: keep them out of shadow / indirect rays in Cycles
    for attr in ("visible_shadow", "visible_diffuse", "visible_glossy", "visible_transmission"):
        if hasattr(obj, attr):
            setattr(obj, attr, False)
    return link(scene, obj, parent)


def cylinder(radius, z0, z1, segments=12):
    def build(bm):
        bmesh.ops.create_cone(bm, cap_ends=False, cap_tris=False, segments=segments,
                              radius1=radius, radius2=radius, depth=z1 - z0)
        bmesh.ops.translate(bm, verts=bm.verts, vec=(0, 0, (z0 + z1) / 2))
    return build


def cone(length, half_angle, segments=48):
    """Closed cone (a volume), apex at the origin, opening along +Z."""
    def build(bm):
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                              radius1=0.0, radius2=length * math.tan(half_angle), depth=length)
        bmesh.ops.translate(bm, verts=bm.verts, vec=(0, 0, length / 2))
    return build


def sphere(radius, segs=32):
    def build(bm):
        bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=segs // 2, radius=radius)
    return build


# --------------------------------------------------------------------------- shader nodes

class NB:
    """Tiny node-tree builder: math on sockets or plain numbers."""

    def __init__(self, nt):
        self.nt = nt
        self.count = 0
        nt.nodes.clear()

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        n.location = (self.count % 6 * 200, -(self.count // 6) * 220)
        self.count += 1
        return n

    def put(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.nt.links.new(v, sock)
        else:
            sock.default_value = v

    def math(self, op, a, b=0.0):
        n = self.node("ShaderNodeMath", operation=op)
        self.put(n.inputs[0], a)
        self.put(n.inputs[1], b)
        return n.outputs[0]

    def mul(self, *xs):
        out = xs[0]
        for x in xs[1:]:
            out = self.math("MULTIPLY", out, x)
        return out

    def maprange(self, v, fmin, fmax, tmin, tmax, smooth=False):
        n = self.node("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP" if smooth else "LINEAR")
        for i, x in enumerate((v, fmin, fmax, tmin, tmax)):
            self.put(n.inputs[i], x)
        return n.outputs[0]

    def value(self, name, v):
        n = self.node("ShaderNodeValue")
        n.name = n.label = name
        n.outputs[0].default_value = v
        return n

    def obj_coords(self, obj=None):
        tc = self.node("ShaderNodeTexCoord")
        if obj is not None:
            tc.object = obj
        return tc.outputs["Object"]

    def xyz(self, vec):
        s = self.node("ShaderNodeSeparateXYZ")
        self.put(s.inputs[0], vec)
        return s.outputs["X"], s.outputs["Y"], s.outputs["Z"]

    def length(self, vec):
        n = self.node("ShaderNodeVectorMath", operation="LENGTH")
        self.put(n.inputs[0], vec)
        return n.outputs["Value"]

    def combine(self, x, y, z):
        n = self.node("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self.put(n.inputs[i], v)
        return n.outputs[0]

    def facing_in(self, power):
        """1 where the surface faces the camera, 0 at the silhouette."""
        lw = self.node("ShaderNodeLayerWeight")
        inv = self.math("SUBTRACT", 1.0, lw.outputs["Facing"])
        return self.math("POWER", inv, power)

    def emission(self, color, strength):
        e = self.node("ShaderNodeEmission")
        self.put(e.inputs["Color"], (*color, 1.0))
        self.put(e.inputs["Strength"], strength)
        return e.outputs[0]

    def near_camera_fade(self, start=1.5, end=6.0):
        """0 close to the camera, 1 from `end` on: keeps lines from smearing over the lens."""
        cam = self.node("ShaderNodeCameraData")
        return self.maprange(cam.outputs["View Distance"], start, end, 0.0, 1.0, smooth=True)

    def output(self, shader, additive, volume=False):
        out = self.node("ShaderNodeOutputMaterial")
        if volume:
            self.put(out.inputs["Volume"], shader)
            return
        if additive:
            tr = self.node("ShaderNodeBsdfTransparent")
            add = self.node("ShaderNodeAddShader")
            self.put(add.inputs[0], shader)
            self.put(add.inputs[1], tr.outputs[0])
            shader = add.outputs[0]
        self.put(out.inputs["Surface"], shader)


def new_material(name, additive):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    if additive:
        if hasattr(mat, "surface_render_method"):  # EEVEE Next (4.2+)
            mat.surface_render_method = "BLENDED"
        if hasattr(mat, "blend_method"):
            try:
                mat.blend_method = "BLEND"
            except TypeError:
                pass
        if hasattr(mat, "use_transparency_overlap"):
            mat.use_transparency_overlap = True
    return mat, NB(mat.node_tree)


def particle_material(name, scan_rig, glow=1.0):
    """Round particles. They light up inside the scan cone and near the light."""
    mat, nb = new_material(name, additive=False)
    v = {
        "Glow": nb.value("Glow", glow),
        "ScanGain": nb.value("ScanGain", 0.0),
        "NearGain": nb.value("NearGain", 1.0),
    }
    p = nb.obj_coords(scan_rig)  # shading point in the scan rig's space, +Z = scan direction
    x, y, z = nb.xyz(p)
    r = nb.length(nb.combine(x, y, 0.0))
    ratio = nb.math("DIVIDE", r, nb.math("MAXIMUM", z, 0.05))
    tan_a = math.tan(CONE_HALF_ANGLE)
    inside = nb.maprange(ratio, tan_a * 0.45, tan_a, 1.0, 0.0, smooth=True)
    front = nb.math("GREATER_THAN", z, 0.0)
    dist = nb.maprange(z, 0.0, 22.0, 1.0, 0.25)
    scan = nb.mul(inside, front, dist, v["ScanGain"].outputs[0])
    near = nb.mul(nb.maprange(nb.length(p), 0.0, 2.4, 1.0, 0.0, smooth=True), v["NearGain"].outputs[0])
    info = nb.node("ShaderNodeObjectInfo")
    rnd = nb.maprange(info.outputs["Random"], 0.0, 1.0, 0.35, 1.3)
    boost = nb.math("ADD", 1.0, nb.math("ADD", nb.mul(scan, 10.0), nb.mul(near, 4.0)))
    strength = nb.mul(1.3, rnd, v["Glow"].outputs[0], boost)
    nb.output(nb.emission(PARTICLE_COLOR, strength), additive=False)
    return mat, v


def beam_material(name, length, one_sided=False, core=False):
    """Light line. Fades out towards its ends. core=True is the hot thin line, else the soft halo."""
    mat, nb = new_material(name, additive=True)
    master = nb.value("Master", 0.0)
    _, _, z = nb.xyz(nb.obj_coords())
    along = z if one_sided else nb.math("ABSOLUTE", z)
    fade = nb.math("POWER", nb.maprange(along, 0.0, length, 1.0, 0.0, smooth=True), 1.6)
    fade = nb.mul(fade, nb.near_camera_fade())
    if core:
        strength = nb.mul(30.0, fade, master.outputs[0])
        color = (1.0, 1.0, 1.0)
    else:
        strength = nb.mul(0.9, nb.facing_in(3.0), fade, master.outputs[0])
        color = BEAM_HALO_COLOR
    nb.output(nb.emission(color, strength), additive=True)
    return mat, master


def cone_material(name, length, half_angle, strength=1.1):
    """Glowing haze inside the cone: an emission-only volume, brightest on the axis and near the apex."""
    mat, nb = new_material(name, additive=False)
    master = nb.value("Master", 0.0)
    x, y, z = nb.xyz(nb.obj_coords())
    r = nb.length(nb.combine(x, y, 0.0))
    ratio = nb.math("DIVIDE", r, nb.math("MAXIMUM", nb.mul(z, math.tan(half_angle)), 0.01))
    radial = nb.math("POWER", nb.maprange(ratio, 0.0, 1.0, 1.0, 0.0), 2.0)
    fade = nb.math("POWER", nb.maprange(z, 0.0, length, 1.0, 0.0), 2.0)
    s = nb.mul(strength, radial, fade, nb.near_camera_fade(2.0, 7.0), master.outputs[0])
    nb.output(nb.emission(CONE_COLOR, s), additive=False, volume=True)
    return mat, master


def glow_sphere_material(name, color, strength, power):
    """Soft disc of light (halo) or, with power=0, a solid hot core."""
    mat, nb = new_material(name, additive=True)
    val = nb.value("Strength", strength)
    s = val.outputs[0] if power == 0 else nb.mul(val.outputs[0], nb.facing_in(power))
    nb.output(nb.emission(color, s), additive=True)
    return mat, val


# --------------------------------------------------------------------------- particles

def drift_node_group():
    """Points -> drifting round instances (ico-spheres on 4D noise)."""
    ng = bpy.data.node_groups.new("QB_Drift", "GeometryNodeTree")
    it = ng.interface
    it.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    it.new_socket("Material", in_out="INPUT", socket_type="NodeSocketMaterial")
    for name, val in (("Radius", 0.018), ("Amplitude", 0.35), ("Speed", 0.07), ("Noise Scale", 0.16)):
        s = it.new_socket(name, in_out="INPUT", socket_type="NodeSocketFloat")
        s.default_value = val
    s = it.new_socket("Seed", in_out="INPUT", socket_type="NodeSocketInt")
    s.default_value = 0
    it.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    nb = NB(ng)
    gi = nb.node("NodeGroupInput")
    go = nb.node("NodeGroupOutput")
    time = nb.node("GeometryNodeInputSceneTime")
    pos = nb.node("GeometryNodeInputPosition")
    noise = nb.node("ShaderNodeTexNoise", noise_dimensions="4D")
    nb.put(noise.inputs["Vector"], pos.outputs[0])
    nb.put(noise.inputs["W"], nb.math("MULTIPLY", time.outputs["Seconds"], gi.outputs["Speed"]))
    nb.put(noise.inputs["Scale"], gi.outputs["Noise Scale"])
    centered = nb.node("ShaderNodeVectorMath", operation="SUBTRACT")
    nb.put(centered.inputs[0], noise.outputs["Color"])
    centered.inputs[1].default_value = (0.5, 0.5, 0.5)
    offset = nb.node("ShaderNodeVectorMath", operation="SCALE")
    nb.put(offset.inputs[0], centered.outputs[0])
    nb.put(offset.inputs["Scale"], gi.outputs["Amplitude"])
    setpos = nb.node("GeometryNodeSetPosition")
    nb.put(setpos.inputs["Geometry"], gi.outputs["Geometry"])
    nb.put(setpos.inputs["Offset"], offset.outputs[0])

    ico = nb.node("GeometryNodeMeshIcoSphere")
    ico.inputs["Radius"].default_value = 1.0
    ico.inputs["Subdivisions"].default_value = 3
    shade = nb.node("GeometryNodeSetShadeSmooth")
    nb.put(shade.inputs["Geometry"], ico.outputs["Mesh"])
    setmat = nb.node("GeometryNodeSetMaterial")
    nb.put(setmat.inputs["Geometry"], shade.outputs[0])
    nb.put(setmat.inputs["Material"], gi.outputs["Material"])

    rnd = nb.node("FunctionNodeRandomValue", data_type="FLOAT")
    floats = [s for s in rnd.inputs if s.type == "VALUE" and s.enabled]
    mins = [s for s in floats if s.name == "Min"]
    maxs = [s for s in floats if s.name == "Max"]
    mins[0].default_value, maxs[0].default_value = 0.5, 1.5
    nb.put(rnd.inputs["Seed"], gi.outputs["Seed"])
    rout = [s for s in rnd.outputs if s.type == "VALUE" and s.enabled][0]

    iop = nb.node("GeometryNodeInstanceOnPoints")
    nb.put(iop.inputs["Points"], setpos.outputs[0])
    nb.put(iop.inputs["Instance"], setmat.outputs[0])
    nb.put(iop.inputs["Scale"], nb.math("MULTIPLY", rout, gi.outputs["Radius"]))
    nb.put(go.inputs[0], iop.outputs[0])
    return ng


def points_object(scene, name, pts, ng, mat, location=(0, 0, 0), **inputs):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(p) for p in pts], [], [])
    obj = link(scene, bpy.data.objects.new(name, me))
    obj.location = location
    mod = obj.modifiers.new("Drift", "NODES")
    mod.node_group = ng
    values = {"Material": mat, **inputs}
    props = getattr(getattr(mod, "properties", None), "inputs", None)  # 5.2+ typed inputs
    for item in ng.interface.items_tree:
        if getattr(item, "in_out", None) == "INPUT" and item.name in values:
            if props is not None:
                getattr(props, item.identifier).value = values[item.name]
            else:
                mod[item.identifier] = values[item.name]
    for attr in ("visible_shadow", "visible_diffuse", "visible_glossy", "visible_transmission"):
        if hasattr(obj, attr):
            setattr(obj, attr, False)
    return obj


def random_unit(rng):
    while True:
        v = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
        if 0.01 < v.length <= 1:
            return v.normalized()


def field_points(rng, keep_clear=(), rings=18, scatter=900):
    """Dotted orbital arcs around the light (like the references) plus loose dust."""
    pts = []
    for _ in range(rings):
        radius = rng.uniform(2.5, 13.0)
        n = random_unit(rng)
        n = (n + Vector((0, 0, rng.uniform(0.5, 2.0)))).normalized()  # mostly flat-ish orbits
        u = n.orthogonal().normalized()
        w = n.cross(u)
        start = rng.uniform(0, 2 * math.pi)
        arc = rng.uniform(0.35, 1.0) * 2 * math.pi
        count = int(arc * radius * 7)
        for _ in range(count):
            a = start + rng.uniform(0, arc)
            p = radius * (math.cos(a) * u + math.sin(a) * w)
            p += Vector((rng.gauss(0, 0.09), rng.gauss(0, 0.09), rng.gauss(0, 0.09))) * (radius / 6)
            pts.append(p)
    for _ in range(scatter):
        r = 16.0 * rng.random() ** 0.6
        pts.append(random_unit(rng) * r)
    keep_clear = [Vector(c) for c in keep_clear]
    return [p for p in pts if p.length > 1.0 and all((p - c).length > 5.0 for c in keep_clear)]


def cluster_points(rng, n=70, sigma=0.38):
    return [Vector((rng.gauss(0, sigma), rng.gauss(0, sigma), rng.gauss(0, sigma))) for _ in range(n)]


# --------------------------------------------------------------------------- render setup

def set_engine(scene, engine, samples=None):
    if engine == "cycles":
        scene.render.engine = "CYCLES"
        c = scene.cycles
        c.samples = samples or 128
        c.use_denoising = True
        c.max_bounces = 2
        c.transparent_max_bounces = 64
        c.caustics_reflective = c.caustics_refractive = False
    else:
        ids = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
        scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in ids else "BLENDER_EEVEE"
        e = scene.eevee
        e.taa_render_samples = samples or 64
        for attr, val in (("volumetric_tile_size", "4"), ("volumetric_samples", 96),
                          ("volumetric_start", 0.5), ("volumetric_end", 60.0)):
            if hasattr(e, attr):
                setattr(e, attr, val)


def set_output(scene, path):
    r = scene.render
    r.filepath = path
    im = r.image_settings
    try:
        if hasattr(im, "media_type"):  # 5.0+
            im.media_type = "VIDEO"
        im.file_format = "FFMPEG"
        r.ffmpeg.format = "MPEG4"
        r.ffmpeg.codec = "H264"
        r.ffmpeg.constant_rate_factor = "HIGH"
    except (TypeError, AttributeError):
        im.file_format = "PNG"


def set_glare(node, **params):
    """Glare settings are input sockets since 4.4 and node properties before that."""
    legacy = {
        "Type": ("glare_type", {"Fog Glow": "FOG_GLOW", "Streaks": "STREAKS", "Bloom": "BLOOM"}),
        "Quality": ("quality", {"High": "HIGH", "Medium": "MEDIUM", "Low": "LOW"}),
        "Threshold": ("threshold", None),
        "Streaks": ("streaks", None),
        "Streaks Angle": ("angle_offset", None),
        "Fade": ("fade", None),
        "Size": ("size", lambda v: int(round(6 + 3 * v))),  # old size is 6..9
        "Strength": ("mix", lambda v: v - 1.0),            # old mix: -1 image only .. 1 glare only
    }
    for name, v in params.items():
        sock = node.inputs.get(name)
        if sock is not None:
            try:
                sock.default_value = v
                continue
            except (TypeError, ValueError):
                pass
        prop, conv = legacy.get(name, (None, None))
        if prop and hasattr(node, prop):
            val = conv.get(v, v) if isinstance(conv, dict) else (conv(v) if conv else v)
            try:
                setattr(node, prop, val)
            except (TypeError, ValueError):
                pass


def setup_compositor(scene):
    if hasattr(scene, "compositing_node_group"):  # 5.0+
        tree = bpy.data.node_groups.new("QB_Compositor", "CompositorNodeTree")
        tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        scene.compositing_node_group = tree
        out_kind = "NodeGroupOutput"
    else:
        scene.use_nodes = True
        tree = scene.node_tree
        out_kind = "CompositorNodeComposite"
    tree.nodes.clear()
    rl = tree.nodes.new("CompositorNodeRLayers")
    rl.scene = scene
    fog = tree.nodes.new("CompositorNodeGlare")
    set_glare(fog, Type="Fog Glow", Quality="High", Threshold=0.8, Size=0.75, Strength=0.9)
    star = tree.nodes.new("CompositorNodeGlare")
    set_glare(star, Type="Streaks", Quality="High", Threshold=150.0, Streaks=6,
              **{"Streaks Angle": math.radians(18)}, Fade=0.93, Strength=0.7)
    out = tree.nodes.new(out_kind)
    for i, n in enumerate((rl, fog, star, out)):
        n.location = (i * 300, 0)
    tree.links.new(rl.outputs["Image"], fog.inputs["Image"])
    tree.links.new(fog.outputs["Image"], star.inputs["Image"])
    tree.links.new(star.outputs["Image"], out.inputs[0])
    scene.render.use_compositing = True
    if bpy.app.background and hasattr(scene.render, "compositor_device"):
        scene.render.compositor_device = "CPU"  # headless machines may have no GPU context


def new_scene(name):
    old = bpy.data.scenes.get(name)
    if old is not None:
        for obj in list(old.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.scenes.remove(old)
    # drop what the previous build left behind (only unused "QB_" data)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.node_groups, bpy.data.cameras, bpy.data.worlds):
        for block in list(coll):
            if block.name.startswith("QB_") and block.users == 0:
                coll.remove(block)
    scene = bpy.data.scenes.new(name)
    world = bpy.data.worlds.new(name + "_World")
    world.color = (0, 0, 0)
    try:
        world.use_nodes = True
        bg = world.node_tree.nodes.get("Background")
        bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    except (AttributeError, TypeError):
        pass
    scene.world = world
    try:
        scene.view_settings.view_transform = "AgX"
    except TypeError:
        scene.view_settings.view_transform = "Filmic"
    if bpy.context.window is not None:
        bpy.context.window.scene = scene
    return scene


# --------------------------------------------------------------------------- the light rig

class LightRig:
    """
    Source (empty, moves)
      core + halo spheres
      ScanRig (quaternion, +Z = where it looks)
        scan cone (blue haze)
        beams (lines through the source; their spread/roll is keyed per beam)
      TrailRig (damped-tracks an anchor that lags behind, so the trail points back along the path)
        trail line + trail haze
    """

    def __init__(self, scene, beam_offsets, beam_len=16.0):
        self.scene = scene
        self.source = new_empty(scene, "QB_Source", size=0.4)
        core_mat, self.core = glow_sphere_material("QB_SourceCore", (1, 1, 1), 0.0, power=0)
        halo_mat, self.halo = glow_sphere_material("QB_SourceHalo", (0.85, 0.88, 1.0), 0.0, power=6)
        mesh_object(scene, "QB_Core", sphere(0.06), self.source, core_mat)
        mesh_object(scene, "QB_Halo", sphere(0.7), self.source, halo_mat)

        self.scan = new_empty(scene, "QB_ScanRig", self.source)
        self.scan.rotation_mode = "QUATERNION"
        cone_len = 12.0
        cmat, self.cone = cone_material("QB_ScanCone", cone_len, CONE_HALF_ANGLE)
        mesh_object(scene, "QB_Cone", cone(cone_len, CONE_HALF_ANGLE), self.scan, cmat)

        core_beam, self.beam_core = beam_material("QB_BeamCore", beam_len, core=True)
        halo_beam, self.beam_halo = beam_material("QB_BeamHalo", beam_len)
        self.beams = []
        for i, (az, ang) in enumerate(beam_offsets):
            pivot = new_empty(scene, f"QB_Beam{i}", self.scan, size=0.2)
            pivot.rotation_mode = "QUATERNION"
            pivot["az"], pivot["ang"] = az, ang
            mesh_object(scene, f"QB_Beam{i}_Core", cylinder(0.006, -beam_len, beam_len, 8), pivot, core_beam)
            mesh_object(scene, f"QB_Beam{i}_Halo", cylinder(0.035, -beam_len, beam_len, 16), pivot, halo_beam)
            self.beams.append(pivot)

        self.anchor = new_empty(scene, "QB_TrailAnchor", size=0.2)
        self.trail = new_empty(scene, "QB_TrailRig", self.source)
        c = self.trail.constraints.new("DAMPED_TRACK")
        c.target = self.anchor
        c.track_axis = "TRACK_Z"
        trail_len = 12.0
        tcore, self.trail_core = beam_material("QB_TrailCore", trail_len, one_sided=True, core=True)
        thalo, self.trail_halo = beam_material("QB_TrailHalo", trail_len, one_sided=True)
        tcone, self.trail_cone = cone_material("QB_TrailHaze", trail_len, math.radians(9), strength=1.0)
        self.trail_len_obj = new_empty(scene, "QB_TrailLength", self.trail, size=0.2)
        mesh_object(scene, "QB_Trail_Core", cylinder(0.010, 0.0, trail_len, 8), self.trail_len_obj, tcore)
        mesh_object(scene, "QB_Trail_Halo", cylinder(0.035, 0.0, trail_len, 16), self.trail_len_obj, thalo)
        mesh_object(scene, "QB_Trail_Haze", cone(trail_len, math.radians(9)), self.trail_len_obj, tcone)

    # keys -----------------------------------------------------------------
    def look(self, t, target_or_dir, is_point=True, origin=(0, 0, 0)):
        d = Vector(target_or_dir) - Vector(origin) if is_point else Vector(target_or_dir)
        key_quat(self.scan, t, direction_quat(d))

    def fan(self, t, spread, roll=0.0):
        for b in self.beams:
            axis = Vector((math.cos(b["az"] + roll), math.sin(b["az"] + roll), 0.0))
            key_quat(b, t, Quaternion(axis, spread * b["ang"]))

    def beams_on(self, t, v):
        key_val(self.beam_core, t, v)
        key_val(self.beam_halo, t, v)

    def trail_on(self, t, v):
        for n in (self.trail_core, self.trail_halo, self.trail_cone):
            key_val(n, t, v)

    def trail_length(self, t, s):
        key_scale(self.trail_len_obj, t, (1, 1, max(s, 0.001)))

    def depart(self, t0, t1, path, delay=0.3, step=1):
        """Key the source along path(u) (u: 0..1) and the trail anchor `delay` seconds behind it."""
        start = Vector(path(0.0))
        back = (start - Vector(path(0.02))).normalized()
        key_loc(self.anchor, t0 - 0.5, start + back)
        with Interp("LINEAR"):
            f0, f1 = F(t0), F(t1)
            for f in range(f0, f1 + 1, step):
                t = (f - 1) / FPS
                u = (t - t0) / (t1 - t0)
                key_loc(self.source, t, path(u))
                ua = (t - delay - t0) / (t1 - t0)
                key_loc(self.anchor, t, path(ua) if ua > 0 else start + back)


def camera(scene, loc_keys, target_keys, lens=35.0, focus=None, fstop=4.0):
    cam_data = bpy.data.cameras.new("QB_Camera")
    cam_data.lens = lens
    cam_data.clip_end = 300
    cam = link(scene, bpy.data.objects.new("QB_Camera", cam_data))
    target = new_empty(scene, "QB_CamTarget", size=0.5)
    c = cam.constraints.new("TRACK_TO")
    c.target = target
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"
    for t, p in loc_keys:
        key_loc(cam, t, p)
    for t, p in target_keys:
        key_loc(target, t, p)
    if focus is not None:
        cam_data.dof.use_dof = True
        cam_data.dof.focus_object = focus
        cam_data.dof.aperture_fstop = fstop
    scene.camera = cam
    return cam


def key_scan_gain(mats, t, v):
    for _, vals in mats:
        key_val(vals["ScanGain"], t, v)


# --------------------------------------------------------------------------- option 1

def build_lighthouse(scene, rng):
    duration = 12.0
    S0 = Vector((0, 0, 0))
    T = Vector((-3.2, 1.8, 1.3))         # the right spot
    W, E = Vector((1.0, 8.0, 5.0)), Vector((5.0, 18.0, 6.5))  # departure arc
    cam_keys = [(0, (-2.0, -13.0, 1.4)), (duration, (-1.2, -11.8, 1.9))]

    rig = LightRig(scene, beam_offsets=[(0.0, 0.0), (math.radians(20), math.radians(38)),
                                        (math.radians(200), math.radians(62))])
    ng = drift_node_group()

    field_mat = particle_material("QB_Particles", rig.scan)
    field = points_object(scene, "QB_Field", field_points(rng, [c for _, c in cam_keys]), ng, field_mat[0])
    with Interp("LINEAR"):
        field.rotation_euler = (0, 0, 0)
        field.keyframe_insert("rotation_euler", frame=F(0))
        field.rotation_euler = (0, 0, math.radians(8))
        field.keyframe_insert("rotation_euler", frame=F(duration))
    target_mat = particle_material("QB_TargetCluster", rig.scan)
    target = points_object(scene, "QB_Target", cluster_points(rng, 90, 0.42), ng, target_mat[0],
                           location=T, Radius=0.022, Seed=3)
    mats = [field_mat, target_mat]

    camera(scene, cam_keys,
           [(0, (-2.2, 0.0, 0.1)), (9.0, (-2.0, 0.6, 0.4)), (duration, (-0.4, 4.0, 1.6))],
           focus=rig.source)

    # source: appear, bob, fly to the spot, flare, float away
    for t, p in ((0, S0), (1.5, (0, 0, 0.08)), (3.0, (0, 0, -0.05)), (5.0, (0.05, 0, 0.05)),
                 (7.0, (0, 0, 0)), (8.3, S0), (9.2, T)):
        key_loc(rig.source, t, p)
    for t, v in ((0, 0), (0.8, 120), (3.0, 150), (8.3, 180), (9.2, 600), (9.6, 900), (10.2, 320)):
        key_val(rig.core, t, v)
    for t, v in ((0, 0), (1.0, 1.5), (9.0, 2.0), (9.4, 5.0), (10.2, 2.0)):
        key_val(rig.halo, t, v)

    # beams
    for t, v in ((2.4, 0), (3.2, 1.0), (7.0, 1.0), (8.0, 1.3), (9.2, 1.8), (9.8, 0.6), (10.2, 0.0)):
        rig.beams_on(t, v)
    for t, v in ((2.6, 0), (3.4, 1.0), (8.0, 1.2), (9.0, 0.4), (9.6, 0.0)):
        key_val(rig.cone, t, v)
    for t, v in ((2.6, 0), (3.4, 1.0), (8.6, 1.0), (9.4, 0.0)):
        key_scan_gain(mats, t, v)

    # lighthouse sweep: 1.25 turns that ease out exactly onto the target direction
    dir_t = (T - S0).normalized()
    theta_t = math.atan2(dir_t.y, dir_t.x)

    def sweep_dir(theta):
        return Vector((math.cos(theta), math.sin(theta), 0.3 * math.sin(1.7 * theta)))

    t0, t1 = 2.8, 8.0
    rig.look(0, sweep_dir(theta_t - 2.5 * math.pi), is_point=False)
    with Interp("LINEAR"):
        for f in range(F(t0), F(t1) + 1, 3):
            t = (f - 1) / FPS
            u = (t - t0) / (t1 - t0)
            d = sweep_dir(theta_t - 2.5 * math.pi * (1 - smoother(u))).normalized()
            d = d.lerp(dir_t, smooth((u - 0.7) / 0.3))
            rig.look(t, d, is_point=False)
            rig.fan(t, 1.0 if u < 0.85 else 1.0 - 0.8 * smooth((u - 0.85) / 0.15), roll=1.2 * u)
    rig.fan(0, 1.0, 0.0)
    rig.fan(t0, 1.0, 0.0)
    rig.fan(8.3, 0.18, 1.2)
    rig.fan(9.2, 0.55, 1.5)   # beams open into an X as the light arrives on the spot
    rig.fan(9.9, 0.0, 1.6)    # ...and fold into one line

    # the chosen cluster answers, then gets absorbed into the light
    for t, v in ((7.4, 1.0), (8.0, 2.2), (8.4, 1.6), (8.8, 3.0), (9.2, 5.0), (9.6, 6.0)):
        key_val(target_mat[1]["Glow"], t, v)
    key_scale(target, 9.2, 1.0)
    key_scale(target, 10.0, 0.02)

    # one light, floating away with a trail
    rig.trail_on(9.8, 0.0)
    rig.trail_on(10.4, 1.0)
    rig.trail_length(9.9, 0.0)
    rig.trail_length(11.0, 1.0)
    rig.depart(10.0, duration, lambda u: qbez(T, W, E, max(u, 0.0) ** 2))
    return duration


# --------------------------------------------------------------------------- option 2

def build_search(scene, rng):
    duration = 15.0
    S0 = Vector((0, 0, 0))
    candidates = [Vector(c) for c in ((-4.2, 1.2, 1.6), (3.4, -1.8, -1.4), (-2.6, -2.4, -1.9),
                                      (4.0, 3.2, 2.2), (1.2, 5.5, 3.0))]
    RIGHT = Vector((-3.4, 2.6, -0.9))
    decor = [Vector((-5.5, 6.0, -2.5)), Vector((6.0, 7.0, -1.5))]
    W, E = Vector((0.5, 9.0, 4.2)), Vector((7.0, 24.0, 7.5))
    cam_keys = [(0, (-0.6, -16.5, 2.4)), (duration, (-2.6, -11.2, 1.3))]

    rig = LightRig(scene, beam_offsets=[(0.0, 0.0), (math.radians(90), math.radians(24)),
                                        (math.radians(210), math.radians(40)),
                                        (math.radians(320), math.radians(58))])
    ng = drift_node_group()
    field_mat = particle_material("QB_Particles", rig.scan)
    field = points_object(scene, "QB_Field", field_points(rng, [c for _, c in cam_keys], rings=16, scatter=1000),
                          ng, field_mat[0])
    with Interp("LINEAR"):
        field.rotation_euler = (0, 0, 0)
        field.keyframe_insert("rotation_euler", frame=F(0))
        field.rotation_euler = (0, 0, math.radians(-6))
        field.keyframe_insert("rotation_euler", frame=F(duration))
    mats = [field_mat]

    clusters = []
    for i, c in enumerate(candidates + [RIGHT] + decor):
        glow = 0.8 if i < len(candidates) + 1 else 0.6
        m = particle_material(f"QB_Cluster{i}", rig.scan, glow=glow)
        obj = points_object(scene, f"QB_Cluster{i}", cluster_points(rng, 70, 0.36), ng, m[0],
                            location=c, Radius=0.021, Seed=10 + i)
        clusters.append((obj, m))
        mats.append(m)

    camera(scene, cam_keys,
           [(0, (-1.2, 0.0, 0.0)), (10.0, (-1.6, 0.4, 0.0)), (12.2, (-2.6, 1.8, -0.4)),
            (13.6, (-1.2, 4.5, 0.8)), (duration, (-1.0, 5.0, 1.0))],
           focus=rig.source)

    # appear
    key_loc(rig.source, 0, S0)
    for t, v in ((0, 0), (0.8, 120), (2.5, 150)):
        key_val(rig.core, t, v)
    for t, v in ((0, 0), (1.0, 1.5)):
        key_val(rig.halo, t, v)
    for t, v in ((2.0, 0), (2.8, 1.0)):
        rig.beams_on(t, v)
    for t, v in ((2.6, 0), (3.0, 1.0)):
        key_val(rig.cone, t, v)
        key_scan_gain(mats, t, v)
    rig.look(0, (0.6, -0.3, 0.2), is_point=False)
    rig.fan(0, 1.0, 0.0)

    # scan the candidates one by one: snap, pulse, reject (dim + drift off)
    prev = Vector((0.6, -0.3, 0.2)) + S0
    roll = 0.0
    starts = [3.0, 4.25, 5.5, 6.75, 8.0]
    for i, (ts, c) in enumerate(zip(starts, candidates)):
        hold = 0.8 if i == len(starts) - 1 else 1.0  # last one is a quick glance
        new_roll = roll + rng.uniform(0.8, 2.2)
        rig.look(ts, prev)
        rig.look(ts + 0.28, c)
        rig.fan(ts, 1.0, roll)
        rig.fan(ts + 0.28, 0.22, new_roll)
        rig.fan(ts + hold, 0.22, new_roll)
        for dt, v in ((0.3, 1.5), (0.38, 0.7), (0.46, 1.4), (0.6, 1.0)):
            rig.beams_on(ts + dt, v)
        obj, m = clusters[i]
        for dt, v in ((0.25, 0.8), (0.4, 3.2), (0.55, 1.6), (0.7, 3.4), (hold, 1.0), (hold + 0.3, 0.22)):
            key_val(m[1]["Glow"], ts + dt, v)
        away = (c - S0).normalized() * 1.8 + Vector((0, 0, 0.3))
        key_loc(obj, ts + hold - 0.1, c)
        key_loc(obj, ts + hold + 3.5, c + away)
        prev, roll = c, new_roll

    # lock on the right one
    lock = 9.0
    obj, m = clusters[len(candidates)]
    rig.look(lock, prev)
    rig.look(lock + 0.3, RIGHT)
    rig.fan(lock, 1.0, roll)
    rig.fan(lock + 0.3, 0.3, roll + 1.0)
    rig.fan(lock + 0.9, 0.3, roll + 1.2)
    rig.fan(lock + 1.3, 0.0, roll + 1.4)   # every beam merges into one line
    for t, v in ((lock + 0.4, 1.6), (lock + 1.3, 2.0), (lock + 1.8, 1.8), (11.6, 1.8), (12.2, 0.0)):
        rig.beams_on(t, v)
    for t, v in ((lock + 0.3, 0.8), (lock + 0.6, 3.0), (lock + 1.3, 5.0), (11.0, 6.0)):
        key_val(m[1]["Glow"], t, v)
    key_scale(obj, lock + 0.5, 1.0)
    key_scale(obj, lock + 1.6, 0.55)
    key_scale(obj, 11.4, 0.55)
    key_scale(obj, 12.0, 0.02)
    for t, v in ((10.6, 1.0), (11.4, 0.0)):
        key_val(rig.cone, t, v)
    for t, v in ((10.4, 1.0), (11.2, 0.0)):
        key_scan_gain(mats, t, v)

    # flare, glide to it, become one light
    for t, v in ((lock + 1.3, 150), (lock + 1.6, 700), (11.0, 400), (11.9, 900), (12.4, 320)):
        key_val(rig.core, t, v)
    for t, v in ((lock + 1.3, 1.5), (lock + 1.6, 4.0), (11.0, 2.5), (11.9, 5.0), (12.4, 2.0)):
        key_val(rig.halo, t, v)
    key_loc(rig.source, 10.8, S0)
    key_loc(rig.source, 11.8, RIGHT)

    # glide away on an arc with a trail
    rig.trail_on(11.9, 0.0)
    rig.trail_on(12.4, 1.0)
    rig.trail_length(12.0, 0.0)
    rig.trail_length(13.0, 1.0)
    rig.depart(12.2, duration, lambda u: qbez(RIGHT, W, E, max(u, 0.0) ** 1.7))
    return duration


# --------------------------------------------------------------------------- option 3: the answer

class Track:
    """Smooth curve through (time, value) keys: cubic Hermite with Catmull-Rom tangents.
    A key equal to its neighbour is a hold (zero tangent), so holds never overshoot."""

    def __init__(self, keys):
        self.keys = sorted(keys, key=lambda k: k[0])

    def _tangent(self, i):
        ks = self.keys
        p = ks[i][1]
        if i == 0 or i == len(ks) - 1 or ks[i - 1][1] == p or ks[i + 1][1] == p:
            return p * 0
        return (ks[i + 1][1] - ks[i - 1][1]) / (ks[i + 1][0] - ks[i - 1][0])

    def __call__(self, t):
        ks = self.keys
        if t <= ks[0][0]:
            return ks[0][1]
        if t >= ks[-1][0]:
            return ks[-1][1]
        i = max(j for j in range(len(ks) - 1) if ks[j][0] <= t)
        (t0, p0), (t1, p1) = ks[i], ks[i + 1]
        h = t1 - t0
        s = (t - t0) / h
        h00, h10 = 2 * s ** 3 - 3 * s ** 2 + 1, s ** 3 - 2 * s ** 2 + s
        h01, h11 = -2 * s ** 3 + 3 * s ** 2, s ** 3 - s ** 2
        return h00 * p0 + h10 * h * self._tangent(i) + h01 * p1 + h11 * h * self._tangent(i + 1)


def ramp(t, t0, t1, a, b, ease=smooth):
    return a + (b - a) * ease((t - t0) / (t1 - t0)) if t1 > t0 else (b if t >= t1 else a)


def simple_glow_material(name, strength, color=(1, 1, 1), power=0):
    """Plain additive emission. power > 0 softens it towards the silhouette (a halo)."""
    return glow_sphere_material(name, color, strength, power)


def answer_ray_material(name, strength, halo=False):
    """A line through the hub. LenPos / LenNeg set how far it reaches on each side.
    halo=True is the soft glow around the line (fades towards its silhouette)."""
    mat, nb = new_material(name, additive=True)
    v = {k: nb.value(k, d) for k, d in (("Master", 0.0), ("LenPos", 14.0), ("LenNeg", 14.0))}
    _, _, z = nb.xyz(nb.obj_coords())
    pos = nb.maprange(z, 0.0, v["LenPos"].outputs[0], 1.0, 0.0, smooth=True)
    neg = nb.maprange(nb.math("MULTIPLY", z, -1.0), 0.0, v["LenNeg"].outputs[0], 1.0, 0.0, smooth=True)
    fade = nb.math("ADD", nb.mul(pos, nb.math("GREATER_THAN", z, 0.0)),
                   nb.mul(neg, nb.math("LESS_THAN", z, 0.0)))
    s = nb.mul(strength, fade, nb.near_camera_fade(2.0, 8.0), v["Master"].outputs[0])
    if halo:
        s = nb.mul(s, nb.facing_in(2.0))
    nb.output(nb.emission((0.8, 0.85, 1.0) if halo else (1, 1, 1), s), additive=True)
    return mat, v


def answer_dot_material(name, ray_pivots, base=0.9):
    """Plain round dots that brighten when any ray passes close to them."""
    mat, nb = new_material(name, additive=False)
    vals = {"Base": nb.value("Base", base)}
    lit = 0.0
    for i, pivot in enumerate(ray_pivots):
        vals[f"I{i}"] = nb.value(f"I{i}", 0.0)
        x, y, z = nb.xyz(nb.obj_coords(pivot))
        near = nb.maprange(nb.length(nb.combine(x, y, 0.0)), 0.0, 0.5, 1.0, 0.0, smooth=True)
        along = nb.maprange(nb.math("ABSOLUTE", z), 0.0, 14.0, 1.0, 0.0)
        term = nb.mul(near, along, vals[f"I{i}"].outputs[0])
        lit = term if i == 0 else nb.math("ADD", lit, term)
    info = nb.node("ShaderNodeObjectInfo")
    rnd = nb.maprange(info.outputs["Random"], 0.0, 1.0, 0.5, 1.2)
    s = nb.mul(vals["Base"].outputs[0], rnd, nb.math("ADD", 1.0, nb.mul(lit, 9.0)))
    nb.output(nb.emission((1, 1, 1), s), additive=False)
    return mat, vals


def streak_node_group():
    """Points -> ico-spheres stretched along local Z (the tunnel streaks)."""
    ng = bpy.data.node_groups.new("QB_Streaks", "GeometryNodeTree")
    it = ng.interface
    it.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    it.new_socket("Material", in_out="INPUT", socket_type="NodeSocketMaterial")
    it.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nb = NB(ng)
    gi, go = nb.node("NodeGroupInput"), nb.node("NodeGroupOutput")
    ico = nb.node("GeometryNodeMeshIcoSphere")
    ico.inputs["Radius"].default_value = 1.0
    ico.inputs["Subdivisions"].default_value = 2
    setmat = nb.node("GeometryNodeSetMaterial")
    nb.put(setmat.inputs["Geometry"], ico.outputs["Mesh"])
    nb.put(setmat.inputs["Material"], gi.outputs["Material"])
    iop = nb.node("GeometryNodeInstanceOnPoints")
    nb.put(iop.inputs["Points"], gi.outputs["Geometry"])
    nb.put(iop.inputs["Instance"], setmat.outputs[0])
    iop.inputs["Scale"].default_value = (0.009, 0.009, 0.35)
    nb.put(go.inputs[0], iop.outputs[0])
    return ng


def ring(major, minor=0.012, segments=160, sides=6):
    """Thin torus in the XY plane (an orbit line)."""
    def build(bm):
        rows = []
        for i in range(segments):
            a = 2 * math.pi * i / segments
            centre = Vector((major * math.cos(a), major * math.sin(a), 0.0))
            out = Vector((math.cos(a), math.sin(a), 0.0))
            rows.append([bm.verts.new(centre + minor * (math.cos(b) * out + math.sin(b) * Vector((0, 0, 1))))
                         for b in (2 * math.pi * j / sides for j in range(sides))])
        for i in range(segments):
            r0, r1 = rows[i], rows[(i + 1) % segments]
            for j in range(sides):
                bm.faces.new((r0[j], r1[j], r1[(j + 1) % sides], r0[(j + 1) % sides]))
    return build


def orbit_ring_material(name, strength=0.8):
    """Faint orbit line; fades out near the camera so it never smears across the lens."""
    mat, nb = new_material(name, additive=True)
    val = nb.value("Strength", strength)
    nb.output(nb.emission((0.85, 0.88, 1.0), nb.mul(val.outputs[0], nb.near_camera_fade(1.0, 4.0))),
              additive=True)
    return mat, val


def camera_rotation(forward, roll):
    q = forward.normalized().to_track_quat("-Z", "Y")
    return Quaternion(forward.normalized(), roll) @ q


def build_answer(scene, rng):
    """
    Option 3, "The Answer". A plain movement reference: emissive dots and lines, no effects.
    Built to be restyled by video-to-video AI: 16:9, thick rays, big sparse dots, one shot.
      0-2     the hub (dead centre) ignites and 5 rays of different strength grow out of it
      2-5     each ray sweeps the 3D dot field on its own; the camera slowly orbits the hub
      5-6     a faint ray settles on one dot (the answer) and brightens; the others keep scanning
              but steer clear of it
      6-9.6   a pulse of light runs down that ray; the camera pushes in until it is the only
              light in frame and chases the pulse into the dot
      9.6-12  inside the dot: only now the tunnel of streaks appears, a light at its far end
      12-16   still moving forward, out through the tunnel wall; the far light with the tunnel
              trailing behind it eases into the hero frame (light at 72% / 33%), then holds
    """
    duration = 15.0
    A = Vector((0.0, 0.0, 0.0))                       # the answer
    u = Vector((1.0, -0.25, 0.10)).normalized()       # the winning ray (hub -> answer -> tunnel)
    H = A - 6.0 * u                                   # the hub
    E = A + 34.0 * u                                  # the light at the end of the tunnel
    up = Vector((0, 0, 1))
    right = u.cross(up).normalized()                  # camera-right while looking down the tunnel
    lift = Vector((0, 0, 0.25))                       # keeps the camera just off the ray's axis

    # final frame: E at 72% across / 33% down (the site's hero), seen from beside the tunnel
    res_x, res_y = PLAIN["answer"]
    tan_h = 18.0 / 35.0
    tan_v = tan_h * res_y / res_x
    target_ndc = ((0.72 - 0.5) * 2, (0.5 - 0.33) * 2)
    to_E = (Quaternion(up, math.radians(28)) @ u + Vector((0, 0, -0.04))).normalized()
    Cf = E - 15.0 * to_E

    def screen(fwd_vec, direction):
        c = camera_rotation(fwd_vec, 0.0).inverted() @ direction
        return (c.x / -c.z) / tan_h, (c.y / -c.z) / tan_v

    def aim(direction, ndc):
        """Level camera forward that puts `direction` at screen position `ndc`."""
        yaw, pitch = math.atan2(direction.y, direction.x), math.asin(direction.z)
        for _ in range(30):
            def fv(y_, p_):
                return Vector((math.cos(p_) * math.cos(y_), math.cos(p_) * math.sin(y_), math.sin(p_)))
            x0, y0 = screen(fv(yaw, pitch), direction)
            ex, ey = x0 - ndc[0], y0 - ndc[1]
            if abs(ex) + abs(ey) < 1e-6:
                break
            e = 1e-4
            xa, ya = screen(fv(yaw + e, pitch), direction)
            xb, yb = screen(fv(yaw, pitch + e), direction)
            j = ((xa - x0) / e, (xb - x0) / e, (ya - y0) / e, (yb - y0) / e)
            det = j[0] * j[3] - j[1] * j[2]
            yaw -= (j[3] * ex - j[1] * ey) / det
            pitch -= (-j[2] * ex + j[0] * ey) / det
        return fv(yaw, pitch)

    final_fwd = aim(to_E, target_ndc)

    # camera ------------------------------------------------------------------
    # The path (where the camera goes) and the timing (how fast it goes there) are separate:
    # positions come from a smooth curve through the waypoints, re-parameterised by arc length,
    # and the distance travelled over time is its own smooth curve, so the speed never stutters.
    C0, T0 = H + Vector((-5.5, -7.8, 1.6)), H     # the hub starts dead centre; the camera
    C1, T1 = H + Vector((-0.6, -7.6, 0.5)), H     # slowly orbits it, keeping it there
    off = (C1 - H) - (C1 - H).dot(u) * u          # from the ray towards the camera
    off.normalize()
    R0 = H + 2.0 * u + 2.0 * off + Vector((0, 0, 0.4))   # pushing in on the winning ray
    R1 = H + 3.6 * u + 0.6 * off + Vector((0, 0, 0.15))
    R2 = A - 1.4 * u + 0.08 * off
    exit_pt = A + 16.0 * u + 1.2 * right + Vector((0, 0, 0.3))
    #           waypoint                                   looking along                                roll
    waypoints = [(C0, (T0 - C0).normalized(), 0.0),
                 (C1, (T1 - C1).normalized(), 0.0),
                 (R0, (A - R0).normalized(), 0.0),
                 (R1, (A - R1).normalized(), 0.0),
                 (R2, u, 0.0),
                 (A, u, 0.0),                              # right through the dot
                 (A + 4.0 * u + lift, u, 0.25),
                 (A + 12.0 * u + lift, u, 0.35),
                 (exit_pt, (u + final_fwd).normalized(), 0.12),   # out through the wall
                 (Cf, final_fwd, 0.0)]
    chord = [0.0]
    for (a_, _, _), (b_, _, _) in zip(waypoints, waypoints[1:]):
        chord.append(chord[-1] + (b_ - a_).length)
    geo = Track([(c, w[0]) for c, w in zip(chord, waypoints)])
    n_arc = 4000
    arc_c = [chord[-1] * k / n_arc for k in range(n_arc + 1)]
    arc_len = [0.0]
    prev = geo(0.0)
    for c in arc_c[1:]:
        p = geo(c)
        arc_len.append(arc_len[-1] + (p - prev).length)
        prev = p

    def c_of_s(s_):
        lo, hi = 0, n_arc
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if arc_len[mid] <= s_ else (lo, mid)
        k = (s_ - arc_len[lo]) / max(arc_len[hi] - arc_len[lo], 1e-9)
        return arc_c[lo] + k * (arc_c[hi] - arc_c[lo])

    def s_of_c(c):
        k = min(int(c / chord[-1] * n_arc), n_arc - 1)
        return arc_len[k] + (arc_len[k + 1] - arc_len[k]) * (c / chord[-1] * n_arc - k)

    wp_s = [s_of_c(c) for c in chord]
    fwd = Track([(sv, w[1]) for sv, w in zip(wp_s, waypoints)])
    roll = Track([(sv, w[2]) for sv, w in zip(wp_s, waypoints)])

    # distance along the path over time: (time, waypoint index, speed in units/s)
    timing = [(0.0, 0, 0.2), (4.6, 1, 1.5), (9.6, 5, 3.0), (11.8, 7, 6.0)]
    # the last glide lasts exactly as long as a pure ease-out needs (v0 * (1 - x)^2 covers
    # v0 * h / 3), so the camera comes to rest with no jolt; then hold on the hero frame
    t7, _, v7 = timing[-1]
    timing.append((t7 + 3.0 * (wp_s[9] - wp_s[7]) / v7, 9, 0.0))
    duration = timing[-1][0] + 1.4

    def dist(t):
        if t >= timing[-1][0]:
            return wp_s[-1]
        i = max(j for j in range(len(timing) - 1) if timing[j][0] <= t)
        (t0, i0, v0), (t1, i1, v1) = timing[i], timing[i + 1]
        h = t1 - t0
        x = (t - t0) / h
        s0, s1 = wp_s[i0], wp_s[i1]
        return ((2 * x ** 3 - 3 * x ** 2 + 1) * s0 + (x ** 3 - 2 * x ** 2 + x) * h * v0
                + (-2 * x ** 3 + 3 * x ** 2) * s1 + (x ** 3 - x ** 2) * h * v1)

    def cam_pos(t):
        return geo(c_of_s(dist(t)))

    def time_at(s_):
        lo, hi = 0.0, duration
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if dist(mid) < s_ else (lo, mid)
        return lo

    t_in = timing[2][0]                      # camera enters the dot
    t_out = time_at(wp_s[8])                 # camera leaves the tunnel
    # a pulse of light runs down the winning ray from the hub and reaches the dot just ahead
    # of the camera; until it leaves, it sits in the hub (so aiming at it = aiming at the hub)
    t_pulse, t_arrive = 5.6, t_in - 0.8

    def pulse_at(t):
        x = min(max((t - t_pulse) / (t_arrive - t_pulse), 0.0), 1.0)
        return H + (A - H) * x ** 1.6

    cam_data = bpy.data.cameras.new("QB_Camera")
    cam_data.lens = 35.0
    cam_data.clip_start = 0.02
    cam_data.clip_end = 300
    cam = link(scene, bpy.data.objects.new("QB_Camera", cam_data))
    cam.rotation_mode = "QUATERNION"
    scene.camera = cam

    # hub + rays ----------------------------------------------------------------
    hub = new_empty(scene, "QB_Hub", size=0.4)
    hub.location = H
    hub_core_mat, hub_core = simple_glow_material("QB_HubCore", 0.0)
    hub_halo_mat, hub_halo = simple_glow_material("QB_HubHalo", 0.0, (0.9, 0.92, 1.0), power=6)
    mesh_object(scene, "QB_HubCore", sphere(0.05, 16), hub, hub_core_mat)
    mesh_object(scene, "QB_HubHalo", sphere(0.2, 24), hub, hub_halo_mat)

    #        yaw0  yaw/s  wobble wob-f pitch0 p-amp  p-f   phase strength radius
    specs = [(2.4, 0.42, 0.5, 0.31, 0.25, 0.45, 0.27, 0.0, 1.00, 0.030),   # lead
             (-0.6, -0.33, 0.7, 0.23, -0.35, 0.5, 0.36, 1.3, 0.60, 0.022),  # medium
             (0.9, 0.27, 0.4, 0.41, 0.6, 0.35, 0.21, 2.1, 0.50, 0.020),     # medium
             (0.0, 0.50, 0.6, 0.29, 0.0, 0.6, 0.33, 0.7, 0.35, 0.014),      # faint: the winner
             (3.6, -0.45, 0.5, 0.37, -0.5, 0.4, 0.44, 2.8, 0.30, 0.012)]    # faint
    WIN = 3

    def free_angles(spec, t):
        y0, ys, wob, wf, p0, pa, pf, ph = spec[:8]
        return y0 + ys * t + wob * math.sin(wf * t + ph), p0 + pa * math.sin(pf * t + ph)

    # aim the winner's own sweep so that it crosses the answer at 5 s on its own
    t_lock = 5.0
    yw, pw = free_angles(specs[WIN], t_lock)
    yu, pu = math.atan2(u.y, u.x), math.asin(u.z)
    s = list(specs[WIN])
    s[0] += yu - yw
    s[4] += pu - pw
    specs[WIN] = tuple(s)

    def free_dir(spec, t):
        yaw, pitch = free_angles(spec, t)
        return Vector((math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch)))

    pivots, ray_vals, lines = [], [], []
    for i, sp in enumerate(specs):
        pivot = new_empty(scene, f"QB_Ray{i}", hub, size=0.2)
        pivot.rotation_mode = "QUATERNION"
        mat, vals = answer_ray_material(f"QB_Ray{i}", 30.0)
        hmat, hvals = answer_ray_material(f"QB_Ray{i}_Glow", 0.35, halo=True)
        lines.append(mesh_object(scene, f"QB_Ray{i}_Line", cylinder(sp[9], -32.0, 32.0, 8), pivot, mat))
        mesh_object(scene, f"QB_Ray{i}_Glow", cylinder(sp[9] * 3.5, -32.0, 32.0, 12), pivot, hmat)
        pivots.append(pivot)
        ray_vals.append((vals, hvals))

    def ray_start(i):
        return 0.6 + 0.5 * i                 # rays leave the hub one after another

    def ray_length(i, t):
        x = min(max((t - ray_start(i)) / 2.2, 0.0), 1.0)
        return 16.0 * smooth(x) ** 1.2       # visibly grows out of the hub, settles at full length

    def ray_strength(i, t):
        sp = specs[i]
        on = ramp(t, ray_start(i), ray_start(i) + 0.1, 0.0, 1.0)
        flicker = 1.0 if sp[8] > 0.4 else 0.78 + 0.22 * math.sin(9.1 * t + sp[7]) * math.sin(5.3 * t)
        if i == WIN:  # brightens as it locks on; hands over to the tail once we are out
            return ramp(t, 5.0, 5.8, sp[8] * flicker * on, 1.25) * ramp(t, t_out, t_out + 1.5, 1.0, 0.0)
        # the others never fade on screen; they are switched off once we are inside the dot
        return sp[8] * flicker * on * ramp(t, t_in - 0.1, t_in + 0.3, 1.0, 0.0)

    def ray_direction(i, t):
        d = free_dir(specs[i], t)
        if i == WIN:
            return d.slerp(u, smoother((t - 4.4) / 1.2))
        # after the lock the others keep scanning but steer at least 50 deg clear of the
        # winning ray, so once the camera is on it they stay out of frame
        keep_out = smooth((t - 5.0) / 1.0)
        c = d.dot(u)
        limit = math.cos(math.radians(50))
        if keep_out > 0 and abs(c) > limit:
            side_ = d - c * u
            side_ = side_.normalized() if side_.length > 1e-6 else u.orthogonal().normalized()
            want = math.copysign(limit, c) * u + math.sqrt(1 - limit ** 2) * side_
            d = d.slerp(want, keep_out)
        return d

    # the answer: an ordinary dot until a ray settles on it --------------------------
    ans = new_empty(scene, "QB_Answer", size=0.3)
    ans.location = A
    ans_core_mat, ans_core = simple_glow_material("QB_AnswerCore", 0.9)
    ans_halo_mat, ans_halo = simple_glow_material("QB_AnswerHalo", 0.0, (0.9, 0.92, 1.0), power=6)
    ans_core_obj = mesh_object(scene, "QB_AnswerCore", sphere(0.025, 16), ans, ans_core_mat)
    mesh_object(scene, "QB_AnswerHalo", sphere(0.35, 24), ans, ans_halo_mat)   # we fly into this

    pulse = new_empty(scene, "QB_Pulse", size=0.3)
    pulse_core_mat, pulse_core = simple_glow_material("QB_PulseCore", 0.0)
    pulse_halo_mat, pulse_halo = simple_glow_material("QB_PulseHalo", 0.0, (0.9, 0.92, 1.0), power=4)
    mesh_object(scene, "QB_PulseCore", sphere(0.035, 16), pulse, pulse_core_mat)
    mesh_object(scene, "QB_PulseHalo", sphere(0.12, 24), pulse, pulse_halo_mat)

    # orbit rings: static depth guides around the hub and the far light. They make the orbit,
    # the push-in and the pull-out easy to read, and a restyle can turn them into anything.
    ring_mat, _ = orbit_ring_material("QB_Orbits")
    for k, (centre, radius, tilt, heading) in enumerate((
            (H, 2.6, 68, 10), (H, 4.2, 74, 70), (H, 6.5, 62, -35),
            (E, 3.2, 70, 20), (E, 5.6, 64, -50))):
        o = mesh_object(scene, f"QB_Orbit{k}", ring(radius), None, ring_mat)
        o.location = centre
        o.rotation_euler = (math.radians(tilt), 0.0, math.radians(heading))

    # the light at the end of the tunnel, and the tail it keeps in the final frame -------------
    end = new_empty(scene, "QB_EndLight", size=0.3)
    end.location = E
    end_core_mat, end_core = simple_glow_material("QB_EndCore", 0.0)
    end_halo_mat, end_halo = simple_glow_material("QB_EndHalo", 0.0, (0.9, 0.92, 1.0), power=6)
    mesh_object(scene, "QB_EndCore", sphere(0.05, 16), end, end_core_mat)
    mesh_object(scene, "QB_EndHalo", sphere(0.35, 24), end, end_halo_mat)
    tail = new_empty(scene, "QB_Tail", end, size=0.2)
    tail.rotation_mode = "QUATERNION"
    tail.rotation_quaternion = (-u).to_track_quat("Z", "Y")
    tail_mat, tail_vals = answer_ray_material("QB_Tail", 30.0)
    tail_vals["LenPos"].outputs[0].default_value = 6.5
    tail_vals["LenNeg"].outputs[0].default_value = 0.01
    mesh_object(scene, "QB_Tail_Line", cylinder(0.02, 0.0, 7.0, 8), tail, tail_mat)

    # dots ------------------------------------------------------------------------
    cam_samples = [cam_pos(f / FPS) for f in range(0, F(duration), 2)]
    pts = []
    for _ in range(3500):
        pts.append(Vector((rng.uniform(-16, 42), rng.uniform(-22, 20), rng.uniform(-10, 9))))
    for center, count in ((E, 9), (A, 4), (H, 5)):
        for _ in range(count):
            radius = rng.uniform(2.0, 12.0)
            n = (random_unit(rng) + Vector((0, 0, rng.uniform(0.5, 2.0)))).normalized()
            a_ = n.orthogonal().normalized()
            b_ = n.cross(a_)
            start, arc = rng.uniform(0, 2 * math.pi), rng.uniform(0.4, 1.0) * 2 * math.pi
            for _ in range(int(arc * radius * 2.5)):
                ang = start + rng.uniform(0, arc)
                pts.append(center + radius * (math.cos(ang) * a_ + math.sin(ang) * b_)
                           + Vector((rng.gauss(0, 0.04), rng.gauss(0, 0.04), rng.gauss(0, 0.04))))
    keep = []
    for p in pts:
        if min((p - A).length, (p - H).length, (p - E).length) < 0.5:
            continue
        if any((p - c).length < 2.5 for c in cam_samples):
            continue
        keep.append(p)
    ng = drift_node_group()
    dot_mat, dot_vals = answer_dot_material("QB_Dots", pivots)
    points_object(scene, "QB_Dots", keep, ng, dot_mat, Radius=0.04, Amplitude=0.12, Speed=0.05)

    # the tunnel: thin streaks on a tube from the answer to the far light ------------------
    tube = []
    for _ in range(3000):
        a = rng.uniform(0, 2 * math.pi)
        r = 0.7 + rng.gauss(0, 0.05)
        tube.append(Vector((r * math.cos(a), r * math.sin(a), rng.uniform(0.8, (E - A).length - 1.5))))
    tunnel_mat, tunnel_val = simple_glow_material("QB_Tunnel", 0.0)
    tme = bpy.data.meshes.new("QB_Tunnel")
    tme.from_pydata([tuple(p) for p in tube], [], [])
    tunnel = link(scene, bpy.data.objects.new("QB_Tunnel", tme))
    tunnel.location = A
    tunnel.rotation_mode = "QUATERNION"
    tunnel.rotation_quaternion = u.to_track_quat("Z", "Y")
    mod = tunnel.modifiers.new("Streaks", "NODES")
    mod.node_group = streak_node_group()
    props = getattr(getattr(mod, "properties", None), "inputs", None)
    for item in mod.node_group.interface.items_tree:
        if getattr(item, "in_out", None) == "INPUT" and item.name == "Material":
            if props is not None:
                getattr(props, item.identifier).value = tunnel_mat
            else:
                mod[item.identifier] = tunnel_mat

    # camera aim: at the pulse, which sits in the hub until it leaves (so the hub is dead centre),
    # then runs down the ray to the dot. Just before the dot, hand over to looking down the tunnel.
    # The aim is smoothed over time (gaussian, ~0.5 s) so the push-in never whips the camera round.
    frames = range(1, F(duration) + 1)
    s_of_t = [dist((f - 1) / FPS) for f in frames]
    cam_at = [geo(c_of_s(sc)) for sc in s_of_t]
    raw = []
    for f, sc, cp in zip(frames, s_of_t, cam_at):
        at_pulse = (pulse_at((f - 1) / FPS) - cp).normalized()
        k = smoother((sc - wp_s[4]) / (wp_s[5] - wp_s[4]))
        raw.append(at_pulse.slerp(fwd(sc).normalized(), k) if sc < wp_s[5] else fwd(sc).normalized())
    sigma = 0.5 * FPS
    taps = range(-int(3 * sigma), int(3 * sigma) + 1)
    weights = [math.exp(-0.5 * (j / sigma) ** 2) for j in taps]
    looks = []
    for i in range(len(raw)):
        v = Vector((0, 0, 0))
        for j, w_ in zip(taps, weights):
            v += w_ * raw[min(max(i + j, 0), len(raw) - 1)]
        looks.append(v.normalized())

    # key every frame -------------------------------------------------------------------
    with Interp("LINEAR"):
        for f in frames:
            t = (f - 1) / FPS
            s_cam = s_of_t[f - 1]
            cam.location = cam_at[f - 1]
            cam.rotation_quaternion = camera_rotation(looks[f - 1], roll(s_cam))
            cam.keyframe_insert("location", frame=f)
            cam.keyframe_insert("rotation_quaternion", frame=f)
            # the hub ignites with a flash, then settles
            key_val(hub_core, t, ramp(t, 0.0, 0.3, 0.0, 90.0) - ramp(t, 0.3, 1.2, 0.0, 50.0))
            key_val(hub_halo, t, ramp(t, 0.0, 0.3, 0.0, 2.0) - ramp(t, 0.3, 1.2, 0.0, 1.3))

            for i, pivot in enumerate(pivots):
                d = ray_direction(i, t)
                key_quat(pivot, t, d.to_track_quat("Z", "Y"))
                st = ray_strength(i, t)
                length = ray_length(i, t)
                if i == WIN:
                    pos_len = max(length, ramp(t, t_in, t_in + 1.0, 16.0, 30.0))
                    neg_len = min(length, ramp(t, t_in, t_in + 1.8, 16.0, 1.0))
                else:
                    pos_len = neg_len = length
                for vals in ray_vals[i]:
                    key_val(vals["Master"], t, st)
                    key_val(vals["LenPos"], t, max(pos_len, 0.01))
                    key_val(vals["LenNeg"], t, max(neg_len, 0.01))
                key_val(dot_vals[f"I{i}"], t, st * min(length / 16.0, 1.0))

            pulse.location = pulse_at(t)
            pulse.keyframe_insert("location", frame=f)
            p_on = ramp(t, t_pulse, t_pulse + 0.25, 0.0, 1.0) * ramp(t, t_arrive, t_arrive + 0.1, 1.0, 0.0)
            key_val(pulse_core, t, 60.0 * p_on)
            key_val(pulse_halo, t, 1.5 * p_on)
            w = ramp(t, 5.0, 5.8, 1.0, 1.3)
            lines[WIN].scale = (w, w, 1.0)
            lines[WIN].keyframe_insert("scale", frame=f)

            found = ramp(t, 5.3, 5.8, 0.0, 1.0)
            flare = ramp(t, t_arrive - 0.05, t_arrive + 0.1, 0.0, 1.0) * ramp(t, t_arrive + 0.1, t_in + 0.6, 1.0, 0.0)
            merged = ramp(t, t_arrive - 0.05, t_arrive + 0.1, 0.0, 1.0)   # the pulse has arrived
            passed = ramp(t, t_in + 0.05, t_in + 0.4, 1.0, 0.0)     # we are inside it now
            key_val(ans_core, t, (0.9 + 7.0 * found + 30.0 * merged + 40.0 * flare) * passed)
            key_val(ans_halo, t, (0.3 * found + 0.8 * merged + 1.5 * flare) * passed)
            ans_core_obj.scale = (1 + merged,) * 3
            ans_core_obj.keyframe_insert("scale", frame=f)

            lit = ramp(t, t_in, t_in + 0.4, 0.0, 1.0)              # the tunnel exists only inside
            key_val(end_core, t, 40.0 * lit)
            key_val(end_halo, t, 0.9 * lit)
            key_val(tail_vals["Master"], t, ramp(t, t_out, t_out + 1.5, 0.0, 1.0))
            tun = lit * ramp(t, t_out + 0.5, t_out + 2.5, 1.0, 0.0)
            key_val(tunnel_val, t, 2.0 * tun)
    return duration


# --------------------------------------------------------------------------- main

BUILDERS = {
    "lighthouse": ("QB_Lighthouse", build_lighthouse),
    "search": ("QB_Search", build_search),
    "answer": ("QB_Answer", build_answer),
}
# "answer" is a plain movement reference: site-hero size, no glare
PLAIN = {"answer": (1280, 720)}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opts = {"variant": VARIANT, "engine": ENGINE, "scale": 100, "samples": None,
            "render": False, "still": None, "output": None, "save": None}
    i = 0
    while i < len(argv):
        k = argv[i].lstrip("-")
        if k == "render":
            opts["render"] = True
        elif k in opts:
            i += 1
            opts[k] = argv[i]
        i += 1
    for k in ("scale", "samples", "still"):
        if opts[k] is not None:
            opts[k] = int(opts[k])
    return opts


def build(variant=VARIANT, engine=ENGINE, scale=100, samples=None):
    name, builder = BUILDERS[variant]
    scene = new_scene(name)
    duration = builder(scene, random.Random(SEED))
    scene.render.fps = FPS
    scene.frame_start = 1
    scene.frame_end = F(duration)
    scene.render.resolution_x, scene.render.resolution_y = PLAIN.get(variant, (RES_X, RES_Y))
    scene.render.resolution_percentage = scale
    set_engine(scene, engine, samples)
    set_output(scene, f"//renders/qboltz_{variant}_")
    if variant not in PLAIN:
        setup_compositor(scene)
    elif scene.render.engine == "CYCLES":
        scene.cycles.use_denoising = False  # plain emitters: a few samples are already clean
        scene.cycles.max_bounces = 0
    for obj in scene.objects:
        obj.pop("_qprev", None)
    scene.frame_set(1)
    return scene


def main():
    o = parse_args()
    scene = build(o["variant"], o["engine"], o["scale"], o["samples"])
    print(f"[qboltz] built {scene.name}: frames {scene.frame_start}-{scene.frame_end}, {scene.render.engine}")
    if o["output"]:
        scene.render.filepath = o["output"]
    if o["save"]:
        bpy.ops.wm.save_as_mainfile(filepath=o["save"])
    if o["still"] is not None:
        scene.frame_set(o["still"])
        if hasattr(scene.render.image_settings, "media_type"):
            scene.render.image_settings.media_type = "IMAGE"
        scene.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True, scene=scene.name)
    elif o["render"]:
        bpy.ops.render.render(animation=True, scene=scene.name)


if __name__ == "__main__":
    main()
