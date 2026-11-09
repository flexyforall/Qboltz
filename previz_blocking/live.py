"""
CEDENCE / ORCA ONBOARD - previz builder (Blender 4.2+ / 5.x)

Run it in Blender: Scripting tab > Open this file > Run Script.
It only touches data whose names start with "PV_", so it is safe to run in an
existing file and to re-run after tweaking the numbers below.

What it builds
  PV_Room_Open   0-3 s   operator presses Enter, push into the big screen
  PV_Space       3-17 s  float to the satellite, uplink, ORCA readout,
                         into the lens, POV descent to the harbor, capture
  PV_Room_Close  17-28 s harbor still on the operator's monitor, pull back
                         over the shoulder, rise to reveal the big screen
  PV_Edit        the 28 s film: the three shots cut together in the sequencer,
                 with timeline markers for every beat and voice line.
                 Render PV_Edit to get the previz video.

Matching frames
  The big screen shows a render of PV_Space frame 1, and the room shot ends
  with that screen exactly filling the frame. The operator's monitor shows a
  render of PV_Space's last frame, and the closing shot starts with that
  monitor exactly filling the frame. Both stills are rendered by this script
  (set RENDER_TEXTURES = False to skip and keep flat placeholders).
"""
import bpy, bmesh, math, os, random, tempfile
from mathutils import Vector, Matrix

# ---------------------------------------------------------------- settings
FPS = 24
RES = (1920, 1080)
FOCAL = 24.0                      # all shots use a 24 mm lens on a 36 mm sensor
K = 18.0 / FOCAL                  # half frame width / distance = 0.75
RENDER_TEXTURES = True            # render the screen + monitor stills
TEX_RES = (1280, 720)
OUT_DIR = os.environ.get("PV_OUT") or (
    os.path.join(os.path.dirname(bpy.data.filepath), "cedence_previz_textures")
    if bpy.data.filepath else os.path.join(tempfile.gettempdir(), "cedence_previz_textures"))

# shot lengths (seconds)
T_OPEN, T_SPACE, T_CLOSE = 3.0, 14.0, 11.0
CLOSE_OFFSET = 1000               # PV_Room_Close uses frames 1001+ so its
                                  # animation never overlaps PV_Room_Open's

# space: scaled Earth (radius 1000 units), satellite 120 units above the harbor
R_EARTH = 1000.0
SAT_Z = 120.0
HARBOR_W = 4.0                    # captured frame is HARBOR_W x HARBOR_W*9/16
FINAL_ALT = (HARBOR_W / 2) / K    # altitude where the harbor fills the frame

# room (metres): big screen on the front wall, 4 tiered rows
SCREEN_W, SCREEN_H = 12.0, 12.0 * 9 / 16
SCREEN_Y, SCREEN_Z0 = 12.0, 1.5
SCREEN_C = Vector((0, SCREEN_Y, SCREEN_Z0 + SCREEN_H / 2))
ROWS_Y = [6.0, 2.0, -2.0, -6.0]   # front -> back
ROW_H = [0.0, 0.4, 0.8, 1.2]      # platform heights
OP_X = 1.6                        # operator: back row, right of the aisle
MON_W, MON_H = 0.704, 0.396       # operator's main monitor (16:9)

random.seed(7)

def _report_error(exc_type, exc, tb):
    import traceback
    msg = ''.join(traceback.format_exception(exc_type, exc, tb))
    print(msg)
    if not bpy.app.background and bpy.context.window is not None:
        def _err(menu, _ctx):
            for ln in msg.strip().splitlines()[-6:]:
                menu.layout.label(text=ln[:160])
        bpy.context.window_manager.popup_menu(_err, title='CEDENCE previz failed (copy this to Claude)', icon='ERROR')

import sys as _sys
_sys.excepthook = _report_error

# ---------------------------------------------------------------- helpers
def f_of(t, offset=0):
    return int(round(t * FPS)) + 1 + offset

def smooth(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)

def hermite(knots, t):
    """knots: [(time, Vector pos, Vector vel)] - cubic Hermite, velocities in units/s."""
    if t <= knots[0][0]:
        return knots[0][1].copy()
    for (t0, p0, v0), (t1, p1, v1) in zip(knots, knots[1:]):
        if t <= t1:
            d = t1 - t0
            u = (t - t0) / d
            h00, h10 = 2*u**3 - 3*u**2 + 1, u**3 - 2*u**2 + u
            h01, h11 = -2*u**3 + 3*u**2, u**3 - u**2
            return h00*p0 + h10*(v0*d) + h01*p1 + h11*(v1*d)
    return knots[-1][1].copy()

def look_rot(forward, up_hint, prev=None):
    f = forward.normalized()
    r = f.cross(up_hint).normalized()
    u = r.cross(f)
    m = Matrix((r, u, -f)).transposed()
    return m.to_euler('XYZ', prev) if prev is not None else m.to_euler('XYZ')

_OLD_INTERP = []

def set_linear_keys(on):
    prefs = bpy.context.preferences.edit
    if on:
        _OLD_INTERP.append(prefs.keyframe_new_interpolation_type)
        prefs.keyframe_new_interpolation_type = 'LINEAR'
    elif _OLD_INTERP:
        prefs.keyframe_new_interpolation_type = _OLD_INTERP.pop()

def mix_in(node, which):
    """Colour input A/B or colour output of a Mix node, looked up by identifier."""
    ident = {'A': 'A_Color', 'B': 'B_Color', 'OUT': 'Result_Color'}[which]
    socks = node.outputs if which == 'OUT' else node.inputs
    return next(sk for sk in socks if sk.identifier == ident)

def bake_camera(cam, frames, pose_fn):
    """pose_fn(frame) -> (location, forward, up_hint). One key per frame, linear."""
    set_linear_keys(True)
    prev = None
    for f in frames:
        loc, fwd, up = pose_fn(f)
        rot = look_rot(fwd, up, prev)
        prev = rot
        cam.location = loc
        cam.rotation_euler = rot
        cam.keyframe_insert('location', frame=f)
        cam.keyframe_insert('rotation_euler', frame=f)
    set_linear_keys(False)

def vis(ob, f_on=None, f_off=None):
    """Hidden outside [f_on, f_off). Keys both viewport and render visibility."""
    keys = [(-100000, True)]
    if f_on is not None:
        keys.append((f_on, False))
    if f_off is not None:
        keys.append((f_off, True))
    for f, hide in keys:
        ob.hide_render = hide
        ob.hide_viewport = hide
        ob.keyframe_insert('hide_render', frame=f)
        ob.keyframe_insert('hide_viewport', frame=f)

def new_mat(name):
    m = bpy.data.materials.new(name)
    if hasattr(m, 'use_nodes'):
        try:
            m.use_nodes = True
        except Exception:
            pass
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    return m, nt, out

def mat_basic(name, color, metal=0.0, rough=0.5, back_black=False):
    m, nt, out = new_mat(name)
    b = nt.nodes.new('ShaderNodeBsdfPrincipled')
    b.inputs['Base Color'].default_value = (*color, 1)
    b.inputs['Metallic'].default_value = metal
    b.inputs['Roughness'].default_value = rough
    if back_black:   # inside of the satellite renders black ("into the lens")
        geo = nt.nodes.new('ShaderNodeNewGeometry')
        blk = nt.nodes.new('ShaderNodeBsdfDiffuse')
        blk.inputs['Color'].default_value = (0, 0, 0, 1)
        mix = nt.nodes.new('ShaderNodeMixShader')
        nt.links.new(geo.outputs['Backfacing'], mix.inputs[0])
        nt.links.new(b.outputs[0], mix.inputs[1])
        nt.links.new(blk.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs['Surface'])
    else:
        nt.links.new(b.outputs[0], out.inputs['Surface'])
    return m

def mat_emit(name, color, strength):
    m, nt, out = new_mat(name)
    e = nt.nodes.new('ShaderNodeEmission')
    e.inputs['Color'].default_value = (*color, 1)
    e.inputs['Strength'].default_value = strength
    nt.links.new(e.outputs[0], out.inputs['Surface'])
    return m

def mat_image(name, fallback_color, strength=1.0):
    """Emissive screen that shows an image (assigned later) - flat colour until then."""
    m, nt, out = new_mat(name)
    tex = nt.nodes.new('ShaderNodeTexImage'); tex.name = 'PV_IMAGE'
    rgb = nt.nodes.new('ShaderNodeRGB'); rgb.outputs[0].default_value = (*fallback_color, 1)
    e = nt.nodes.new('ShaderNodeEmission'); e.inputs['Strength'].default_value = strength
    nt.links.new(rgb.outputs[0], e.inputs['Color'])
    nt.links.new(e.outputs[0], out.inputs['Surface'])
    return m

def mat_set_image(m, path):
    nt = m.node_tree
    tex = nt.nodes['PV_IMAGE']
    img = bpy.data.images.load(path, check_existing=False)
    img.name = 'PV_' + os.path.basename(path)
    tex.image = img
    em = [n for n in nt.nodes if n.type == 'EMISSION'][0]
    nt.links.new(tex.outputs['Color'], em.inputs['Color'])

def mat_ui(name, seed):
    """Glowing monitor UI: scrolling bands and blocks in cyan / blue / a little amber."""
    m, nt, out = new_mat(name)
    tc = nt.nodes.new('ShaderNodeTexCoord')
    wave = nt.nodes.new('ShaderNodeTexWave'); wave.inputs['Scale'].default_value = 6 + seed
    wave.bands_direction = 'Y' if seed % 2 else 'X'
    vor = nt.nodes.new('ShaderNodeTexVoronoi'); vor.inputs['Scale'].default_value = 9 + 3 * seed
    mixc = nt.nodes.new('ShaderNodeMix'); mixc.data_type = 'RGBA'
    mixc.inputs[0].default_value = 0.5
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    el = ramp.color_ramp.elements
    el[0].position, el[0].color = 0.25, (0.01, 0.03, 0.08, 1)
    el[1].position, el[1].color = 0.9, (0.25, 0.75, 1.0, 1)
    if seed % 3 == 0:
        e3 = el.new(0.6); e3.color = (1.0, 0.55, 0.15, 1)
    e = nt.nodes.new('ShaderNodeEmission'); e.inputs['Strength'].default_value = 2.5
    nt.links.new(tc.outputs['UV'], wave.inputs['Vector'])
    nt.links.new(tc.outputs['UV'], vor.inputs['Vector'])
    nt.links.new(wave.outputs['Fac'], mix_in(mixc, 'A'))
    nt.links.new(vor.outputs['Distance'], mix_in(mixc, 'B'))
    nt.links.new(mix_in(mixc, 'OUT'), ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], e.inputs['Color'])
    nt.links.new(e.outputs[0], out.inputs['Surface'])
    return m

def finish(name, bm, coll, mat=None, smooth_shade=False, sides_only=False):
    if sides_only:   # smooth the round sides, keep flat caps flat
        for fc in bm.faces:
            fc.smooth = abs(fc.normal.z) < 0.5
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    if smooth_shade and not sides_only:
        me.shade_smooth()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    if mat:
        me.materials.append(mat)
    return ob

def box(name, size, loc, coll, mat=None, rot=(0, 0, 0), parent=None):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    ob = finish(name, bm, coll, mat)
    ob.location, ob.rotation_euler, ob.parent = loc, rot, parent
    return ob

def cyl(name, r, depth, loc, coll, mat=None, rot=(0, 0, 0), seg=32, cap=True, r2=None, parent=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=cap, cap_tris=False, segments=seg,
                          radius1=r, radius2=r if r2 is None else r2, depth=depth)
    ob = finish(name, bm, coll, mat, sides_only=True)
    ob.location, ob.rotation_euler, ob.parent = loc, rot, parent
    return ob

def sphere(name, r, loc, coll, mat=None, u=32, v=16, parent=None):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=r)
    ob = finish(name, bm, coll, mat, smooth_shade=True)
    ob.location, ob.parent = loc, parent
    return ob

def plane(name, w, h, loc, coll, mat=None, rot=(0, 0, 0), parent=None):
    """w x h plane in local XY facing +Z, UVs 0..1."""
    bm = bmesh.new()
    vs = [bm.verts.new((x * w / 2, y * h / 2, 0)) for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    face = bm.faces.new(vs)
    uv = bm.loops.layers.uv.new('UVMap')
    for loop, co in zip(face.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
        loop[uv].uv = co
    ob = finish(name, bm, coll, mat)
    ob.location, ob.rotation_euler, ob.parent = loc, rot, parent
    return ob

def line(name, a, b, r, coll, mat, r_b=None):
    """Rod from a to b (radius r at a, r_b at b)."""
    d = b - a
    ob = cyl(name, r, d.length, (a + b) / 2, coll, mat, seg=8, r2=r_b)
    ob.rotation_euler = d.to_track_quat('Z', 'Y').to_euler()
    return ob

def text(name, body, size, coll, mat, loc=(0, 0, 0), parent=None, align='CENTER'):
    cu = bpy.data.curves.new(name, 'FONT')
    cu.body, cu.size, cu.align_x = body, size, align
    cu.materials.append(mat)
    ob = bpy.data.objects.new(name, cu)
    coll.objects.link(ob)
    ob.location, ob.parent = loc, parent
    return ob

FACING_BACK = (math.radians(90), 0, 0)     # plane rotated to face -Y (towards the back of the room)

# ---------------------------------------------------------------- clean previous run
for sc in [s for s in bpy.data.scenes if s.name.startswith('PV_')]:
    bpy.data.scenes.remove(sc)
for coll_name in ('objects', 'meshes', 'curves', 'cameras', 'lights', 'materials',
                  'images', 'collections', 'worlds', 'actions'):
    data = getattr(bpy.data, coll_name)
    for item in [i for i in data if i.name.startswith('PV_')]:
        try:
            data.remove(item)
        except Exception:
            pass

def make_scene(name, frame_start, frame_end, world):
    sc = bpy.data.scenes.new(name)
    sc.render.resolution_x, sc.render.resolution_y = RES
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = frame_start, frame_end
    sc.world = world
    sc.view_settings.view_transform = 'Standard'   # screens show their images 1:1
    engines = (os.environ['PV_ENGINE'],) if os.environ.get('PV_ENGINE') else ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT', 'CYCLES')
    for engine in engines:
        try:
            sc.render.engine = engine
            break
        except TypeError:
            continue
    if sc.render.engine == 'CYCLES':
        sc.cycles.samples = int(os.environ.get('PV_SAMPLES', 64))
        sc.cycles.use_denoising = True
    return sc

def make_camera(name, coll, clip=(0.01, 300)):
    cd = bpy.data.cameras.new(name)
    cd.lens, cd.sensor_width, cd.sensor_fit = FOCAL, 36.0, 'HORIZONTAL'
    cd.clip_start, cd.clip_end = clip
    ob = bpy.data.objects.new(name, cd)
    coll.objects.link(ob)
    return ob

# ================================================================= SPACE
w_space = bpy.data.worlds.new('PV_World_Space')
try:
    w_space.use_nodes = True
except Exception:
    pass
nt = w_space.node_tree; nt.nodes.clear()
wo = nt.nodes.new('ShaderNodeOutputWorld')
bg = nt.nodes.new('ShaderNodeBackground')
tc = nt.nodes.new('ShaderNodeTexCoord')
vor = nt.nodes.new('ShaderNodeTexVoronoi'); vor.inputs['Scale'].default_value = 260
lt = nt.nodes.new('ShaderNodeMath'); lt.operation = 'LESS_THAN'; lt.inputs[1].default_value = 0.035
nt.links.new(tc.outputs['Generated'], vor.inputs['Vector'])
nt.links.new(vor.outputs['Distance'], lt.inputs[0])
nt.links.new(lt.outputs[0], bg.inputs['Strength'])
bg.inputs['Color'].default_value = (0.8, 0.85, 1.0, 1)
nt.links.new(bg.outputs[0], wo.inputs['Surface'])

space = make_scene('PV_Space', 1, int(T_SPACE * FPS), w_space)
c_space = bpy.data.collections.new('PV_Space_Set'); space.collection.children.link(c_space)
c_hud = bpy.data.collections.new('PV_HUD'); space.collection.children.link(c_hud)

# Earth ----------------------------------------------------------------
m_earth, nt, out = new_mat('PV_Earth')
b = nt.nodes.new('ShaderNodeBsdfPrincipled'); b.inputs['Roughness'].default_value = 0.7
tc = nt.nodes.new('ShaderNodeTexCoord')
nz = nt.nodes.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = 0.004; nz.inputs['Detail'].default_value = 8
ramp = nt.nodes.new('ShaderNodeValToRGB'); el = ramp.color_ramp.elements
el[0].position, el[0].color = 0.52, (0.01, 0.05, 0.16, 1)
el[1].position, el[1].color = 0.56, (0.20, 0.21, 0.11, 1)
nt.links.new(tc.outputs['Object'], nz.inputs['Vector'])
nt.links.new(nz.outputs['Fac'], ramp.inputs['Fac'])
nt.links.new(ramp.outputs['Color'], b.inputs['Base Color'])
nt.links.new(b.outputs[0], out.inputs['Surface'])
earth = sphere('PV_Earth', R_EARTH, (0, 0, -R_EARTH), c_space, m_earth, 256, 128)

m_cloud, nt, out = new_mat('PV_Clouds')
b = nt.nodes.new('ShaderNodeBsdfPrincipled'); b.inputs['Base Color'].default_value = (0.9, 0.92, 0.95, 1)
tc = nt.nodes.new('ShaderNodeTexCoord')
nz = nt.nodes.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = 0.03; nz.inputs['Detail'].default_value = 10
ramp = nt.nodes.new('ShaderNodeValToRGB'); el = ramp.color_ramp.elements
el[0].position, el[0].color = 0.55, (0, 0, 0, 1)
el[1].position, el[1].color = 0.7, (0.85, 0.85, 0.85, 1)
nt.links.new(tc.outputs['Object'], nz.inputs['Vector'])
nt.links.new(nz.outputs['Fac'], ramp.inputs['Fac'])
nt.links.new(ramp.outputs['Color'], b.inputs['Alpha'])
nt.links.new(b.outputs[0], out.inputs['Surface'])
clouds = sphere('PV_Clouds', R_EARTH + 6, (0, 0, -R_EARTH), c_space, m_cloud, 256, 128)
clouds.visible_shadow = False

m_atmo, nt, out = new_mat('PV_Atmosphere')
lw = nt.nodes.new('ShaderNodeLayerWeight'); lw.inputs['Blend'].default_value = 0.5
pw = nt.nodes.new('ShaderNodeMath'); pw.operation = 'POWER'; pw.inputs[1].default_value = 4.0
tr = nt.nodes.new('ShaderNodeBsdfTransparent')
em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (0.25, 0.55, 1.0, 1); em.inputs['Strength'].default_value = 1.6
mx = nt.nodes.new('ShaderNodeMixShader')
nt.links.new(lw.outputs['Facing'], pw.inputs[0])
nt.links.new(pw.outputs[0], mx.inputs[0])
nt.links.new(tr.outputs[0], mx.inputs[1]); nt.links.new(em.outputs[0], mx.inputs[2])
nt.links.new(mx.outputs[0], out.inputs['Surface'])
atmo = sphere('PV_Atmosphere', R_EARTH + 20, (0, 0, -R_EARTH), c_space, m_atmo, 256, 128)
for attr in ('visible_shadow', 'visible_diffuse', 'visible_glossy', 'visible_transmission'):
    setattr(atmo, attr, False)
for attr in ('visible_diffuse', 'visible_glossy'):
    setattr(clouds, attr, False)

# Harbor (the region that gets imaged) -----------------------------------
m_harbor, nt, out = new_mat('PV_Harbor')
b = nt.nodes.new('ShaderNodeBsdfPrincipled'); b.inputs['Roughness'].default_value = 0.6
tc = nt.nodes.new('ShaderNodeTexCoord')
sep = nt.nodes.new('ShaderNodeSeparateXYZ')
nz = nt.nodes.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = 0.35
nzm = nt.nodes.new('ShaderNodeMath'); nzm.operation = 'MULTIPLY_ADD'
nzm.inputs[1].default_value = 2.4; nzm.inputs[2].default_value = -1.2
add = nt.nodes.new('ShaderNodeMath'); add.operation = 'ADD'
coast = nt.nodes.new('ShaderNodeMath'); coast.operation = 'GREATER_THAN'; coast.inputs[1].default_value = -0.4
brick = nt.nodes.new('ShaderNodeTexBrick')
brick.inputs['Color1'].default_value = (0.55, 0.50, 0.42, 1)
brick.inputs['Color2'].default_value = (0.40, 0.39, 0.36, 1)
brick.inputs['Mortar'].default_value = (0.16, 0.16, 0.17, 1)
brick.inputs['Mortar Size'].default_value = 0.008
brick.inputs['Brick Width'].default_value = 0.11
brick.inputs['Row Height'].default_value = 0.075
brick.inputs['Color1'].default_value = (0.62, 0.56, 0.48, 1)
brick.inputs['Color2'].default_value = (0.34, 0.33, 0.31, 1)
brick.inputs['Mortar'].default_value = (0.12, 0.12, 0.13, 1)
water = nt.nodes.new('ShaderNodeRGB'); water.outputs[0].default_value = (0.012, 0.05, 0.075, 1)
mix = nt.nodes.new('ShaderNodeMix'); mix.data_type = 'RGBA'
nt.links.new(tc.outputs['Object'], sep.inputs[0])
nt.links.new(tc.outputs['Object'], nz.inputs['Vector'])
nt.links.new(tc.outputs['Object'], brick.inputs['Vector'])
nt.links.new(nz.outputs['Fac'], nzm.inputs[0])
nt.links.new(sep.outputs['X'], add.inputs[0]); nt.links.new(nzm.outputs[0], add.inputs[1])
nt.links.new(add.outputs[0], coast.inputs[0])
nt.links.new(coast.outputs[0], mix.inputs[0])
park_nz = nt.nodes.new('ShaderNodeTexNoise'); park_nz.inputs['Scale'].default_value = 1.6; park_nz.inputs['Detail'].default_value = 4
park_m = nt.nodes.new('ShaderNodeMath'); park_m.operation = 'GREATER_THAN'; park_m.inputs[1].default_value = 0.62
park_c = nt.nodes.new('ShaderNodeRGB'); park_c.outputs[0].default_value = (0.09, 0.14, 0.07, 1)
land = nt.nodes.new('ShaderNodeMix'); land.data_type = 'RGBA'
nt.links.new(tc.outputs['Object'], park_nz.inputs['Vector'])
nt.links.new(park_nz.outputs['Fac'], park_m.inputs[0])
nt.links.new(park_m.outputs[0], land.inputs[0])
nt.links.new(brick.outputs['Color'], mix_in(land, 'A')); nt.links.new(park_c.outputs[0], mix_in(land, 'B'))
nt.links.new(water.outputs[0], mix_in(mix, 'A')); nt.links.new(mix_in(land, 'OUT'), mix_in(mix, 'B'))
nt.links.new(mix_in(mix, 'OUT'), b.inputs['Base Color'])
nt.links.new(b.outputs[0], out.inputs['Surface'])
harbor = plane('PV_Harbor', 24, 13.5, (0, 0, 0.02), c_space, m_harbor)

m_pier = mat_basic('PV_Pier', (0.5, 0.5, 0.48), rough=0.7)
m_boat = mat_basic('PV_Boat', (0.9, 0.9, 0.88), rough=0.4)
for i, y in enumerate((-0.9, -0.55, -0.2, 0.15, 0.5, 0.85)):
    ln = random.uniform(0.6, 1.1)
    box(f'PV_Pier_{i}', (ln, 0.035, 0.01), (-0.45 - ln / 2, y, 0.03), c_space, m_pier)
box('PV_Breakwater', (0.05, 2.6, 0.012), (-2.2, 0.0, 0.03), c_space, m_pier, rot=(0, 0, 0.25))
for i in range(16):
    box(f'PV_Boat_{i}', (0.07, 0.022, 0.012),
        (random.uniform(-2.0, -0.6), random.uniform(-1.05, 1.05), 0.035), c_space, m_boat,
        rot=(0, 0, random.uniform(-0.2, 0.2)))

# Satellite --------------------------------------------------------------
c_sat = c_space
sat = bpy.data.objects.new('PV_Satellite', None); c_sat.objects.link(sat)
sat.location = (0, 0, SAT_Z)
m_gold = mat_basic('PV_Sat_Gold', (0.85, 0.58, 0.18), metal=0.6, rough=0.45, back_black=True)
m_silver = mat_basic('PV_Sat_Silver', (0.8, 0.82, 0.85), metal=0.6, rough=0.35, back_black=True)
m_dark = mat_basic('PV_Sat_Dark', (0.03, 0.03, 0.035), metal=0.5, rough=0.4)
m_black = mat_emit('PV_Sat_Aperture', (0, 0, 0), 0)
m_cells, nt, out = new_mat('PV_Sat_Cells')
b = nt.nodes.new('ShaderNodeBsdfPrincipled'); b.inputs['Roughness'].default_value = 0.2; b.inputs['Metallic'].default_value = 0.3
tc = nt.nodes.new('ShaderNodeTexCoord')
br = nt.nodes.new('ShaderNodeTexBrick'); br.offset = 0.0
br.inputs['Color1'].default_value = (0.02, 0.05, 0.18, 1); br.inputs['Color2'].default_value = (0.03, 0.06, 0.2, 1)
br.inputs['Mortar'].default_value = (0.6, 0.62, 0.65, 1); br.inputs['Mortar Size'].default_value = 0.01
br.inputs['Brick Width'].default_value = 0.3; br.inputs['Row Height'].default_value = 0.3
nt.links.new(tc.outputs['Object'], br.inputs['Vector'])
nt.links.new(br.outputs['Color'], b.inputs['Base Color'])
nt.links.new(b.outputs[0], out.inputs['Surface'])

cyl('PV_Sat_Body', 0.8, 2.4, (0, 0, 0), c_sat, m_gold, parent=sat)
cyl('PV_Sat_TopCap', 0.82, 0.1, (0, 0, 1.25), c_sat, m_silver, parent=sat)
cyl('PV_Sat_Module', 0.85, 0.7, (0, 0, -1.55), c_sat, m_silver, parent=sat)
cyl('PV_Sat_ApertureRim', 0.6, 0.14, (0, 0, -1.96), c_sat, m_dark, cap=False, parent=sat)
cyl('PV_Sat_Aperture', 0.58, 0.02, (0, 0, -1.93), c_sat, m_black, parent=sat)
cyl('PV_Sat_Antenna_A', 0.02, 1.2, (0.3, 0.2, 1.85), c_sat, m_silver, parent=sat)
cyl('PV_Sat_Antenna_B', 0.02, 0.9, (-0.3, -0.15, 1.7), c_sat, m_silver, parent=sat)
cyl('PV_Sat_Dish', 0.32, 0.12, (0.0, 0.55, 1.55), c_sat, m_silver, r2=0.03, rot=(math.radians(-60), 0, 0), parent=sat)
for s in (-1, 1):
    cyl(f'PV_Sat_Boom_{s}', 0.05, 0.9, (s * 1.2, 0, 0.1), c_sat, m_silver, rot=(0, math.radians(90), 0), parent=sat)
    for i in range(4):
        box(f'PV_Sat_Panel_{s}_{i}', (1.25, 1.5, 0.04), (s * (2.25 + 1.32 * i), 0, 0.1), c_sat, m_cells,
            rot=(math.radians(35), 0, 0), parent=sat)

# antenna tip (glows when the uplink arrives)
m_glow = mat_emit('PV_Sat_AntennaGlow', (0.7, 0.85, 1.0), 0.0)
glow = sphere('PV_Sat_AntennaGlow', 0.12, (0.3, 0.2, 2.45), c_sat, m_glow, parent=sat)

# Sun --------------------------------------------------------------------
sun_d = bpy.data.lights.new('PV_Sun', 'SUN'); sun_d.energy = 3.5; sun_d.color = (1.0, 0.93, 0.82); sun_d.angle = math.radians(0.6)
sun = bpy.data.objects.new('PV_Sun', sun_d); c_space.objects.link(sun)
sun.rotation_euler = Vector((-0.85, 0.25, -0.45)).normalized().to_track_quat('-Z', 'Y').to_euler()

# Uplink: ground station -> satellite --------------------------------------
gx, gy = 22.0, 250.0
G = Vector((gx, gy, math.sqrt(R_EARTH**2 - gx**2 - gy**2) - R_EARTH + 0.2))
A = Vector((0.3, 0.2, SAT_Z + 2.45))
m_link = mat_emit('PV_Uplink', (0.6, 0.85, 1.0), 6.0)
m_pulse = mat_emit('PV_UplinkPulse', (0.8, 0.92, 1.0), 25.0)
station = sphere('PV_GroundStation_Flash', 2.2, G, c_space, m_pulse)
vis(station, f_of(2.3), f_of(3.0))
thread = line('PV_Uplink_Thread', G, A, 0.12, c_space, m_link)
vis(thread, f_of(2.6), f_of(4.4))
pulse = sphere('PV_Uplink_Pulse', 0.9, G, c_space, m_pulse)
vis(pulse, f_of(2.6), f_of(4.0))
for t in (2.6, 3.9):
    pulse.location = G.lerp(A, (t - 2.6) / 1.3)
    pulse.keyframe_insert('location', frame=f_of(t))
for t, s in ((3.85, 0.0), (4.0, 60.0), (4.7, 0.0)):
    m_glow.node_tree.nodes['Emission'].inputs['Strength'].default_value = s
    m_glow.node_tree.nodes['Emission'].inputs['Strength'].keyframe_insert('default_value', frame=f_of(t))

# Field of view: telescope -> footprint (the captured frame) ---------------
m_fov, nt, out = new_mat('PV_FOV')          # faint, half-transparent lines
em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (0.3, 0.85, 1.0, 1); em.inputs['Strength'].default_value = 1.5
tr = nt.nodes.new('ShaderNodeBsdfTransparent')
mx = nt.nodes.new('ShaderNodeMixShader'); mx.inputs[0].default_value = 0.5
nt.links.new(tr.outputs[0], mx.inputs[1]); nt.links.new(em.outputs[0], mx.inputs[2])
nt.links.new(mx.outputs[0], out.inputs['Surface'])
apex = Vector((0, 0, SAT_Z - 1.95))
hw, hh = HARBOR_W / 2, HARBOR_W * 9 / 32
corners = [Vector((x, y, 0.06)) for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]
fov_objs = [line(f'PV_FOV_Ray_{i}', apex, c, 0.0008, c_hud, m_fov, r_b=0.015) for i, c in enumerate(corners)]
fov_objs += [line(f'PV_FOV_Frame_{i}', corners[i], corners[(i + 1) % 4], 0.012, c_hud, m_fov) for i in range(4)]
for ob in fov_objs:
    ob.visible_shadow = False
    vis(ob, f_of(6.8), None)

# Space camera -----------------------------------------------------------
cam_space = make_camera('PV_Cam_Space', c_space, clip=(0.02, 5000))
space.camera = cam_space
SAT_C = Vector((0, 0, SAT_Z - 1.6))     # aim a little below the satellite: it sits above frame centre
T_TOP, T_DOWN_END = 8.8, 13.5                 # above the satellite / harbor fills frame
z_top = 127.5
space_knots = [
    (0.0, Vector((0.0, -24.0, 126.5)), Vector((0.3, 3.3, -0.1))),
    (3.5, Vector((1.6, -14.0, 125.8)), Vector((0.6, 2.5, 0.0))),
    (6.5, Vector((3.0, -7.4, 125.6)), Vector((0.0, 2.4, 0.7))),
    (T_TOP, Vector((0.0, 0.0, z_top)), Vector((0.0, 0.0, 0.0))),
]

def space_pose(f):
    t = (f - 1) / FPS
    if t <= T_TOP:
        loc = hermite(space_knots, t)
    else:   # constant-ratio descent: same apparent speed all the way down, eased at both ends
        u = smooth((t - T_TOP) / (T_DOWN_END - T_TOP))
        z = math.exp(math.log(z_top) + (math.log(FINAL_ALT) - math.log(z_top)) * u)
        loc = Vector((0, 0, z))
    w = smooth((t - 6.5) / 2.1)                     # tilt from "look at satellite" to "look straight down"
    to_sat = (SAT_C - loc).normalized() if (SAT_C - loc).length > 1e-3 else Vector((0, 0, -1))
    fwd = to_sat.lerp(Vector((0, 0, -1)), w)
    if fwd.length < 1e-4:
        fwd = Vector((0, 0, -1))
    up = Vector((0, 0, 1)).lerp(Vector((0, 1, 0)), w).normalized()
    return loc, fwd, up

bake_camera(cam_space, range(1, space.frame_end + 1), space_pose)

# HUD --------------------------------------------------------------------
m_hud = mat_emit('PV_HUD_Cyan', (0.35, 0.9, 1.0), 4.0)
m_hud_o = mat_emit('PV_HUD_Orange', (1.0, 0.55, 0.15), 4.0)

def tracker(name, loc):
    e = bpy.data.objects.new(name, None); c_hud.objects.link(e)
    e.location = loc
    c = e.constraints.new('TRACK_TO'); c.target = cam_space
    c.track_axis, c.up_axis = 'TRACK_Z', 'UP_Y'
    return e

t1 = tracker('PV_HUD_Task_Anchor', (0, -1.0, SAT_Z - 3.4))
vis(text('PV_HUD_Task', 'IMAGE THE HARBOR AT FIRST LIGHT', 0.42, c_hud, m_hud, parent=t1), f_of(3.0), f_of(6.6))
t2 = tracker('PV_HUD_Orca_Anchor', (4.2, -1.0, SAT_Z + 1.8))
for i, (txt, t_on, m) in enumerate((('ORCA ONBOARD', 4.6, m_hud), ('INTENT RECEIVED', 5.0, m_hud),
                                     ('PLANNING', 5.5, m_hud), ('GUARDRAILS CLEARED', 6.0, m_hud_o))):
    vis(text(f'PV_HUD_Orca_{i}', txt, 0.38 if i == 0 else 0.26, c_hud, m,
             loc=(0, -0.5 * i, 0), parent=t2, align='LEFT'), f_of(t_on), f_of(7.4))
# screen-space HUD on the POV camera (z = -1 in front of the lens; frame half-width there = 0.75)
vis(text('PV_HUD_Status', 'STATUS  <<< EXECUTING >>>', 0.035, c_hud, m_hud_o,
         loc=(-0.7, -0.38, -1.0), parent=cam_space, align='LEFT'), f_of(9.6), f_of(13.5))
vis(text('PV_HUD_Captured', 'IMAGE CAPTURED', 0.045, c_hud, m_hud,
         loc=(-0.7, -0.38, -1.0), parent=cam_space, align='LEFT'), f_of(13.5), None)

# ================================================================= ROOM
w_room = bpy.data.worlds.new('PV_World_Room')
try:
    w_room.use_nodes = True
except Exception:
    pass
ntw = w_room.node_tree; ntw.nodes.clear()
bgw = ntw.nodes.new('ShaderNodeBackground'); bgw.inputs['Color'].default_value = (0.004, 0.005, 0.008, 1)
ntw.links.new(bgw.outputs[0], ntw.nodes.new('ShaderNodeOutputWorld').inputs['Surface'])

c_room = bpy.data.collections.new('PV_Room_Set')
m_floor = mat_basic('PV_Room_Floor', (0.03, 0.035, 0.045), rough=0.55)
m_wall = mat_basic('PV_Room_Wall', (0.04, 0.045, 0.06), rough=0.8)
m_desk = mat_basic('PV_Room_Desk', (0.09, 0.095, 0.11), rough=0.35)
m_chair = mat_basic('PV_Room_Chair', (0.02, 0.02, 0.025), rough=0.6)
m_bezel = mat_basic('PV_Room_Bezel', (0.01, 0.01, 0.012), rough=0.3)
m_cloth = [mat_basic(f'PV_Cloth_{i}', c, rough=0.8) for i, c in
           enumerate(((0.10, 0.12, 0.16), (0.20, 0.20, 0.22), (0.08, 0.08, 0.09), (0.25, 0.27, 0.32)))]
m_skin = mat_basic('PV_Skin', (0.45, 0.32, 0.26), rough=0.5)
m_ui = [mat_ui(f'PV_UI_{i}', i) for i in range(6)]

# shell
box('PV_Floor', (28, 27, 0.1), (0, -0.5, -0.05), c_room, m_floor)
box('PV_Ceiling', (28, 27, 0.1), (0, -0.5, 9.05), c_room, m_wall)
box('PV_Wall_Front', (28, 0.1, 9.2), (0, SCREEN_Y + 0.15, 4.5), c_room, m_wall)
box('PV_Wall_Back', (28, 0.1, 9.2), (0, -13.05, 4.5), c_room, m_wall)
for s in (-1, 1):
    box(f'PV_Wall_Side_{s}', (0.1, 27, 9.2), (s * 14.05, -0.5, 4.5), c_room, m_wall)
for r in range(1, 4):
    depth, cy = (9.0, ROWS_Y[r] - 2.5) if r == 3 else (4.0, ROWS_Y[r])   # back tier runs to the back wall
    box(f'PV_Tier_{r}', (28, depth, ROW_H[r]), (0, cy, ROW_H[r] / 2), c_room, m_floor)

# big screen
m_feed = mat_image('PV_BigScreen', (0.05, 0.12, 0.3), 1.0)
box('PV_BigScreen_Bezel', (SCREEN_W + 0.3, 0.12, SCREEN_H + 0.3), (0, SCREEN_Y + 0.06, SCREEN_C.z), c_room, m_bezel)
plane('PV_BigScreen', SCREEN_W, SCREEN_H, (0, SCREEN_Y - 0.01, SCREEN_C.z), c_room, m_feed, rot=FACING_BACK)
scr_d = bpy.data.lights.new('PV_BigScreen_Light', 'AREA')
scr_d.shape, scr_d.size, scr_d.size_y = 'RECTANGLE', SCREEN_W, SCREEN_H
scr_d.energy, scr_d.color = 3500, (0.55, 0.7, 1.0)
scr_l = bpy.data.objects.new('PV_BigScreen_Light', scr_d); c_room.objects.link(scr_l)
scr_l.location, scr_l.rotation_euler = (0, SCREEN_Y - 0.3, SCREEN_C.z), (math.radians(-90), 0, 0)

def seated(name, x, y, h, cloth, parent_coll):
    hip = bpy.data.objects.new(name, None); parent_coll.objects.link(hip)
    hip.location = (x, y, h + 0.48)
    cyl(name + '_Torso', 0.18, 0.55, (0, 0, 0.27), parent_coll, cloth, parent=hip)
    box(name + '_Shoulders', (0.44, 0.2, 0.12), (0, 0, 0.52), parent_coll, cloth, parent=hip)
    head = sphere(name + '_Head', 0.11, (0, 0.02, 0.72), parent_coll, m_skin, parent=hip)
    for s in (-1, 1):   # forearms resting towards the keyboard
        box(f'{name}_Arm_{s}', (0.08, 0.38, 0.08), (s * 0.2, 0.22, 0.3), parent_coll, cloth, parent=hip)
    return hip, head

def standing(name, x, y, h, cloth, parent_coll):
    root = bpy.data.objects.new(name, None); parent_coll.objects.link(root)
    root.location = (x, y, h)
    cyl(name + '_Legs', 0.15, 0.85, (0, 0, 0.43), parent_coll, m_cloth[2], parent=root)
    cyl(name + '_Torso', 0.19, 0.62, (0, 0, 1.15), parent_coll, cloth, parent=root)
    head = sphere(name + '_Head', 0.11, (0, 0.02, 1.62), parent_coll, m_skin, parent=root)
    return root, head

def chair(name, x, y, h):
    box(name + '_Seat', (0.46, 0.46, 0.06), (x, y, h + 0.45), c_room, m_chair)
    box(name + '_Back', (0.46, 0.06, 0.55), (x, y - 0.24, h + 0.78), c_room, m_chair)

def monitor(name, x, y, z, w, h, mat):
    box(name + '_Body', (w + 0.03, 0.03, h + 0.03), (x, y + 0.02, z), c_room, m_bezel)
    box(name + '_Stand', (0.05, 0.05, z - (z - h / 2 - 0.1)), (x, y + 0.06, z - h / 2 - 0.05), c_room, m_bezel)
    return plane(name, w, h, (x, y - 0.002, z), c_room, mat, rot=FACING_BACK)

operator = op_head = None
for r, (ry, rh) in enumerate(zip(ROWS_Y, ROW_H)):
    for s in (-1, 1):
        box(f'PV_Desk_{r}_{s}', (10.2, 0.8, 0.75), (s * 6.0, ry + 0.3, rh + 0.375), c_room, m_desk)
        for k in range(6):
            x = s * (OP_X + 1.6 * k)
            mz = rh + 0.75 + 0.3
            is_op = (r == 3 and s == 1 and k == 0)
            if is_op:   # operator: one large 16:9 monitor (shows the harbor capture later)
                continue
            for j, dx in enumerate((-0.34, 0.34)):
                monitor(f'PV_Mon_{r}_{s}_{k}_{j}', x + dx, ry + 0.55, mz, 0.6, 0.34, random.choice(m_ui))
            chair(f'PV_Chair_{r}_{s}_{k}', x, ry - 0.7, rh)
            if random.random() < 0.8:
                seated(f'PV_Eng_{r}_{s}_{k}', x, ry - 0.62, rh, random.choice(m_cloth), c_room)

# the operator's station (back row, right of the aisle)
op_h = ROW_H[3]
MON_Y = ROWS_Y[3] + 0.55
MON_Z = op_h + 0.75 + 0.3
MON_C = Vector((OP_X, MON_Y, MON_Z))
m_opmon, opmon_nt, out = new_mat('PV_OperatorMonitor')
opmon_tex = opmon_nt.nodes.new('ShaderNodeTexImage'); opmon_tex.name = 'PV_IMAGE'
ui_rgb = opmon_nt.nodes.new('ShaderNodeRGB'); ui_rgb.outputs[0].default_value = (0.05, 0.25, 0.45, 1)
opmon_mix = opmon_nt.nodes.new('ShaderNodeMix'); opmon_mix.data_type = 'RGBA'; opmon_mix.name = 'PV_SWITCH'
em = opmon_nt.nodes.new('ShaderNodeEmission'); em.inputs['Strength'].default_value = 1.0
opmon_nt.links.new(ui_rgb.outputs[0], mix_in(opmon_mix, 'A')); opmon_nt.links.new(ui_rgb.outputs[0], mix_in(opmon_mix, 'B'))
opmon_nt.links.new(mix_in(opmon_mix, 'OUT'), em.inputs['Color']); opmon_nt.links.new(em.outputs[0], out.inputs['Surface'])
fac = opmon_mix.inputs[0]
for f, v in ((1, 0.0), (CLOSE_OFFSET - 1, 0.0), (CLOSE_OFFSET, 1.0)):   # UI before, harbor photo in the closing shot
    fac.default_value = v; fac.keyframe_insert('default_value', frame=f)
monitor('PV_OperatorMonitor', OP_X, MON_Y, MON_Z, MON_W, MON_H, m_opmon)
monitor('PV_OperatorMonitor_Side', OP_X + 0.62, MON_Y + 0.05, MON_Z, 0.42, 0.26, m_ui[1])
chair('PV_Chair_Operator', OP_X, ROWS_Y[3] - 0.7, op_h)
operator, op_head = seated('PV_Operator', OP_X, ROWS_Y[3] - 0.62, op_h, m_cloth[3], c_room)
colleague, col_head = standing('PV_Colleague_A', OP_X + 1.3, ROWS_Y[3] - 1.2, op_h, m_cloth[1], c_room)
colleague_b, _ = standing('PV_Colleague_B', OP_X + 2.0, ROWS_Y[3] - 1.5, op_h, m_cloth[0], c_room)

# operator acting: lean in and press Enter (open), lean back + turn to colleague (close)
def key_rot(ob, f, rx=0.0, rz=0.0):
    ob.rotation_euler = (math.radians(rx), 0, math.radians(rz))
    ob.keyframe_insert('rotation_euler', frame=f)

for f, rx in ((1, 0), (14, -8), (30, -8), (40, 0)):
    key_rot(operator, f, rx)
for t, rx in ((0, 0), (5.0, 0), (6.5, 10)):
    key_rot(operator, f_of(t, CLOSE_OFFSET), rx)
for t, rz in ((0, 0), (6.4, 0), (7.4, -35), (9.5, -35), (10.3, 0)):
    key_rot(op_head, f_of(t, CLOSE_OFFSET), 0, rz)
for t, rx in ((0, 0), (7.6, 0), (8.0, -12), (8.4, 0)):
    key_rot(col_head, f_of(t, CLOSE_OFFSET), rx)

# ---- Room scenes: same set, two cameras
room_open = make_scene('PV_Room_Open', 1, int(T_OPEN * FPS), w_room)
room_close = make_scene('PV_Room_Close', CLOSE_OFFSET + 1, CLOSE_OFFSET + int(T_CLOSE * FPS), w_room)
room_open.collection.children.link(c_room)
room_close.collection.children.link(c_room)

cam_open = make_camera('PV_Cam_Room_Open', room_open.collection)
room_open.camera = cam_open
END_OPEN = Vector((0, SCREEN_Y - (SCREEN_W / 2) / K, SCREEN_C.z))     # screen exactly fills the frame
open_knots = [
    (0.0, Vector((0, -9.5, ROW_H[3] + 1.7)), Vector((0, 2.0, 0.1))),
    (T_OPEN, END_OPEN, Vector((0, 1.2, 0.0))),
]

def open_pose(f):
    t = (f - 1) / FPS
    loc = hermite(open_knots, t)
    pitch = math.radians(3.0) * (1 - smooth(t / T_OPEN))
    return loc, Vector((0, math.cos(pitch), math.sin(pitch))), Vector((0, 0, 1))

bake_camera(cam_open, range(1, room_open.frame_end + 1), open_pose)

cam_close = make_camera('PV_Cam_Room_Close', room_close.collection)
room_close.camera = cam_close
START_CLOSE = MON_C + Vector((0, -0.002 - (MON_W / 2) / K, 0))      # monitor exactly fills the frame
END_TARGET = Vector((0.2, SCREEN_Y, 3.0))
close_knots = [
    (0.0, START_CLOSE, Vector((0, 0, 0))),
    (1.5, START_CLOSE, Vector((0, 0, 0))),
    (2.6, START_CLOSE + Vector((0.38, -0.12, 0.17)), Vector((0.22, -0.25, 0.1))),
    (4.6, Vector((OP_X + 0.42, ROWS_Y[3] - 1.55, op_h + 1.45)), Vector((0.0, -0.4, 0.12))),
    (10.0, Vector((0.9, -8.6, op_h + 1.9)), Vector((0, 0, 0))),
]

def close_pose(f):
    t = (f - 1 - CLOSE_OFFSET) / FPS
    loc = hermite(close_knots, t)
    if t <= 1.5:
        return loc, Vector((0, 1, 0)), Vector((0, 0, 1))
    w = smooth((t - 4.6) / 5.4)
    target = MON_C.lerp(END_TARGET, w)
    return loc, target - loc, Vector((0, 0, 1))

bake_camera(cam_close, range(room_close.frame_start, room_close.frame_end + 1), close_pose)

# ================================================================= stills on the screens
def render_still(scene, frame, path, hide_hud=True):
    old = (scene.render.resolution_x, scene.render.resolution_y, scene.render.filepath, scene.frame_current)
    scene.render.resolution_x, scene.render.resolution_y = TEX_RES
    scene.render.filepath = path
    c_hud.hide_render = hide_hud
    if bpy.context.window is not None:
        bpy.context.window.scene = scene
    with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
        scene.frame_set(frame)
        bpy.ops.render.render(write_still=True, scene=scene.name)
    c_hud.hide_render = False
    scene.render.resolution_x, scene.render.resolution_y, scene.render.filepath = old[:3]
    scene.frame_set(old[3])

if RENDER_TEXTURES:
    os.makedirs(OUT_DIR, exist_ok=True)
    feed_png = os.path.join(OUT_DIR, 'feed_start.png')
    capture_png = os.path.join(OUT_DIR, 'harbor_capture.png')
    render_still(space, 1, feed_png)
    render_still(space, space.frame_end, capture_png)
    mat_set_image(m_feed, feed_png)
    img = bpy.data.images.load(capture_png, check_existing=False); img.name = 'PV_harbor_capture.png'
    opmon_tex.image = img
    opmon_nt.links.new(opmon_tex.outputs['Color'], mix_in(opmon_mix, 'B'))

# ================================================================= EDIT (the 28 s film)
edit = make_scene('PV_Edit', 1, int((T_OPEN + T_SPACE + T_CLOSE) * FPS), w_room)
se = edit.sequence_editor_create()
strips = se.strips if hasattr(se, 'strips') else se.sequences
f1 = 1
f2 = f1 + room_open.frame_end - room_open.frame_start + 1
f3 = f2 + space.frame_end - space.frame_start + 1
for name, sc, cam, start in (('PV_Shot1_Room_Open', room_open, cam_open, f1),
                             ('PV_Shot2_Space', space, cam_space, f2),
                             ('PV_Shot3_Room_Close', room_close, cam_close, f3)):
    st = strips.new_scene(name, sc, 1, start)
    st.scene_camera = cam
edit.render.filepath = '//cedence_previz_'
try:
    edit.render.image_settings.media_type = 'VIDEO'
except Exception:
    pass
try:
    edit.render.image_settings.file_format = 'FFMPEG'
    edit.render.ffmpeg.format, edit.render.ffmpeg.codec = 'MPEG4', 'H264'
except Exception:
    pass

for t, label in ((0.4, 'Operator types + presses Enter'), (2.9, 'TRANSITION: into the big screen'),
                 (5.6, 'Uplink rises from Earth  | VO 6s: "New task received."'),
                 (6.0, 'HUD: IMAGE THE HARBOR AT FIRST LIGHT'),
                 (7.6, 'HUD: ORCA ONBOARD readout'), (9.0, 'VO 9s: "Task details confirmed."'),
                 (9.5, 'Arc over the satellite, tilt down'), (12.1, 'TRANSITION: into the lens (black)'),
                 (12.6, 'Satellite POV descent'), (13.5, 'VO: "Executing the task."'),
                 (15.1, 'Through the cloud layer'), (16.5, 'CAPTURE: hold + IMAGE CAPTURED'),
                 (17.0, 'TRANSITION: still = operator monitor'), (18.5, 'Pull back over the shoulder'),
                 (22.0, 'Operator leans back, turns to colleague'), (24.0, 'VO: "Image delivered."'),
                 (27.0, 'End: big screen with satellite feed')):
    edit.timeline_markers.new(label, frame=f_of(t))

# ---------------------------------------------------------------- show the result
# PV_Edit only holds the cut (no 3D objects), so open on the first shot (the room)
# and look through its camera. Switch scenes with the scene selector at the top right.
win = None if bpy.app.background else bpy.context.window
if win is not None:
    win.scene = room_open
    room_open.frame_set(1)
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            for sp in area.spaces:
                if sp.type == 'VIEW_3D':
                    sp.region_3d.view_perspective = 'CAMERA'
                    sp.shading.type = 'MATERIAL'

    def _done(menu, _ctx):
        menu.layout.label(text='Scenes: PV_Room_Open, PV_Space, PV_Room_Close, PV_Edit (full cut).')
        menu.layout.label(text='Press Space to play. Watch PV_Edit in the Video Editing workspace.')
    bpy.context.window_manager.popup_menu(_done, title='CEDENCE previz built', icon='CHECKMARK')
print('CEDENCE previz built. Scenes:', [s.name for s in bpy.data.scenes if s.name.startswith('PV_')])
