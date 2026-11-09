"""
ORCA shot 3 - motion previz (space -> capture -> office -> pop-up -> photo).
Loaded by live_link.py, or run directly in Blender (Scripting tab > Run Script).
Only touches data whose names start with "PV3_".

Scenes
  PV3_Space   13 s  top view, antenna glow, satellite rotates in place (lens tips
                    down), camera descends past it, lines up under the lens, then an
                    optical zoom (focal length only, same angle) onto the harbor, hold.
  PV3_Office  12 s  the same harbor on the video wall, slow pull-back to the seated
                    operator, he swivels back to his desk, pop-up, click, photo opens.
  PV3_Edit    25 s  both shots cut together in the sequencer, markers for every beat.
                    Render PV3_Edit (Render > Render Animation) for the motion reference.

The harbor is one material used on the Earth, on the video wall and in the image
viewer, and the zoom ends with that patch exactly filling the frame, so the cut
from the capture to the wall is frame-identical.
"""
import bpy, bmesh, math, os
from mathutils import Vector, Matrix

FPS = 24
RES = (1920, 1080)
SENSOR = 36.0
T_SPACE, T_OFFICE = 13.0, 12.0

R_EARTH = 1000.0
SAT_Z = 120.0
PATCH_W = 8.0                       # harbor patch = the captured frame (16:9)
PATCH_H = PATCH_W * 9 / 16
Z_ALIGN, Z_FINAL = 116.0, 112.0     # camera height when lined up / at the capture
F_FINAL = SENSOR * (Z_FINAL - 0.03) / PATCH_W   # focal length that frames the patch exactly

SCREEN_W, SCREEN_H = 12.0, 12.0 * 9 / 16
SCREEN_Y, SCREEN_Z0 = 12.0, 1.5
SCREEN_C = Vector((0, SCREEN_Y, SCREEN_Z0 + SCREEN_H / 2))
DESK_Y = -7.2                       # operator's desk (he faces -Y when working)
OP_X = 1.6

# ---------------------------------------------------------------- helpers
def f_of(t):
    return int(round(t * FPS)) + 1

def smooth(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)

def hermite(knots, t):
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

_OLD = []
def linear_keys(on):
    p = bpy.context.preferences.edit
    if on:
        _OLD.append(p.keyframe_new_interpolation_type)
        p.keyframe_new_interpolation_type = 'LINEAR'
    elif _OLD:
        p.keyframe_new_interpolation_type = _OLD.pop()

def bake(ob, frames, fn, lens=None):
    """fn(t) -> (loc, forward, up[, focal]). One key per frame."""
    linear_keys(True)
    prev = None
    for f in frames:
        res = fn((f - frames[0]) / FPS)
        loc, fwd, up = res[:3]
        rot = look_rot(fwd, up, prev)
        prev = rot
        ob.location, ob.rotation_euler = loc, rot
        ob.keyframe_insert('location', frame=f)
        ob.keyframe_insert('rotation_euler', frame=f)
        if len(res) > 3:
            ob.data.lens = res[3]
            ob.data.keyframe_insert('lens', frame=f)
    linear_keys(False)

def vis(ob, f_on=None, f_off=None):
    keys = [(-100000, True)]
    if f_on is not None:
        keys.append((f_on, False))
    if f_off is not None:
        keys.append((f_off, True))
    for f, hide in keys:
        ob.hide_render = ob.hide_viewport = hide
        ob.keyframe_insert('hide_render', frame=f)
        ob.keyframe_insert('hide_viewport', frame=f)

def new_mat(name):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    nt.nodes.clear()
    return m, nt, nt.nodes.new('ShaderNodeOutputMaterial')

def mat_basic(name, color, metal=0.0, rough=0.5):
    m, nt, out = new_mat(name)
    b = nt.nodes.new('ShaderNodeBsdfPrincipled')
    b.inputs['Base Color'].default_value = (*color, 1)
    b.inputs['Metallic'].default_value = metal
    b.inputs['Roughness'].default_value = rough
    nt.links.new(b.outputs[0], out.inputs['Surface'])
    m.diffuse_color = (*color, 1)
    return m

def mat_emit(name, color, strength):
    m, nt, out = new_mat(name)
    e = nt.nodes.new('ShaderNodeEmission')
    e.inputs['Color'].default_value = (*color, 1)
    e.inputs['Strength'].default_value = strength
    nt.links.new(e.outputs[0], out.inputs['Surface'])
    m.diffuse_color = (*color, 1)
    return m

def mix_sock(node, which):
    ident = {'A': 'A_Color', 'B': 'B_Color', 'OUT': 'Result_Color'}[which]
    socks = node.outputs if which == 'OUT' else node.inputs
    return next(s for s in socks if s.identifier == ident)

def mat_harbor(name):
    """Top-down 'satellite photo' of a harbor, driven by UVs (0..1 on a 16:9 plane).
    Emissive so it looks identical on the Earth, the video wall and the monitor."""
    m, nt, out = new_mat(name)
    tc = nt.nodes.new('ShaderNodeTexCoord')
    mp = nt.nodes.new('ShaderNodeMapping'); mp.inputs['Scale'].default_value = (16.0, 9.0, 1.0)
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    nz = nt.nodes.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = 0.35
    shape = nt.nodes.new('ShaderNodeMath'); shape.operation = 'MULTIPLY_ADD'
    shape.inputs[1].default_value = 3.0; shape.inputs[2].default_value = -1.5
    add = nt.nodes.new('ShaderNodeMath'); add.operation = 'ADD'
    coast = nt.nodes.new('ShaderNodeMath'); coast.operation = 'GREATER_THAN'; coast.inputs[1].default_value = 7.0
    brick = nt.nodes.new('ShaderNodeTexBrick')
    brick.inputs['Color1'].default_value = (0.42, 0.40, 0.36, 1)
    brick.inputs['Color2'].default_value = (0.30, 0.30, 0.29, 1)
    brick.inputs['Mortar'].default_value = (0.14, 0.14, 0.15, 1)
    brick.inputs['Mortar Size'].default_value = 0.02
    brick.inputs['Brick Width'].default_value = 0.55
    brick.inputs['Row Height'].default_value = 0.3
    water = nt.nodes.new('ShaderNodeRGB'); water.outputs[0].default_value = (0.03, 0.09, 0.14, 1)
    mix = nt.nodes.new('ShaderNodeMix'); mix.data_type = 'RGBA'
    em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Strength'].default_value = 1.0
    nt.links.new(tc.outputs['UV'], mp.inputs['Vector'])
    nt.links.new(mp.outputs[0], sep.inputs[0])
    nt.links.new(mp.outputs[0], nz.inputs['Vector'])
    nt.links.new(mp.outputs[0], brick.inputs['Vector'])
    nt.links.new(nz.outputs['Fac'], shape.inputs[0])
    nt.links.new(sep.outputs['X'], add.inputs[0]); nt.links.new(shape.outputs[0], add.inputs[1])
    nt.links.new(add.outputs[0], coast.inputs[0])
    nt.links.new(coast.outputs[0], mix.inputs[0])
    nt.links.new(water.outputs[0], mix_sock(mix, 'A')); nt.links.new(brick.outputs['Color'], mix_sock(mix, 'B'))
    nt.links.new(mix_sock(mix, 'OUT'), em.inputs['Color'])
    nt.links.new(em.outputs[0], out.inputs['Surface'])
    m.diffuse_color = (0.25, 0.27, 0.3, 1)
    return m

def finish(name, bm, coll, mat=None, sides_only=False, smooth_all=False):
    if sides_only:
        for fc in bm.faces:
            fc.smooth = abs(fc.normal.z) < 0.5
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    if smooth_all:
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
    ob.parent, ob.location, ob.rotation_euler = parent, loc, rot
    return ob

def cyl(name, r, depth, loc, coll, mat=None, rot=(0, 0, 0), seg=32, cap=True, r2=None, parent=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=cap, cap_tris=False, segments=seg,
                          radius1=r, radius2=r if r2 is None else r2, depth=depth)
    ob = finish(name, bm, coll, mat, sides_only=True)
    ob.parent, ob.location, ob.rotation_euler = parent, loc, rot
    return ob

def sphere(name, r, loc, coll, mat=None, u=32, v=16, parent=None):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=r)
    ob = finish(name, bm, coll, mat, smooth_all=True)
    ob.parent, ob.location = parent, loc
    return ob

def plane(name, w, h, loc, coll, mat=None, rot=(0, 0, 0), parent=None):
    bm = bmesh.new()
    vs = [bm.verts.new((x * w / 2, y * h / 2, 0)) for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    face = bm.faces.new(vs)
    uv = bm.loops.layers.uv.new('UVMap')
    for loop, co in zip(face.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
        loop[uv].uv = co
    ob = finish(name, bm, coll, mat)
    ob.parent, ob.location, ob.rotation_euler = parent, loc, rot
    return ob

def text(name, body, size, coll, mat, loc, rot, align='LEFT', parent=None):
    cu = bpy.data.curves.new(name, 'FONT')
    cu.body, cu.size, cu.align_x = body, size, align
    cu.materials.append(mat)
    ob = bpy.data.objects.new(name, cu)
    coll.objects.link(ob)
    ob.parent, ob.location, ob.rotation_euler = parent, loc, rot
    return ob

def make_scene(name, frames, world):
    sc = bpy.data.scenes.new(name)
    sc.render.resolution_x, sc.render.resolution_y = RES
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = 1, frames
    sc.world = world
    sc.view_settings.view_transform = 'Standard'
    engines = (os.environ['PV_ENGINE'],) if os.environ.get('PV_ENGINE') else ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT', 'CYCLES')
    for e in engines:
        try:
            sc.render.engine = e
            break
        except TypeError:
            continue
    if sc.render.engine == 'CYCLES':
        sc.cycles.samples = int(os.environ.get('PV_SAMPLES', 16))
        sc.cycles.use_denoising = True
    return sc

def make_world(name, color):
    w = bpy.data.worlds.new(name)
    try:
        w.use_nodes = True
    except Exception:
        pass
    nt = w.node_tree; nt.nodes.clear()
    bg = nt.nodes.new('ShaderNodeBackground'); bg.inputs['Color'].default_value = (*color, 1)
    nt.links.new(bg.outputs[0], nt.nodes.new('ShaderNodeOutputWorld').inputs['Surface'])
    return w

def make_camera(name, coll, clip=(0.05, 5000)):
    cd = bpy.data.cameras.new(name)
    cd.lens, cd.sensor_width, cd.sensor_fit = 24.0, SENSOR, 'HORIZONTAL'
    cd.clip_start, cd.clip_end = clip
    ob = bpy.data.objects.new(name, cd)
    coll.objects.link(ob)
    return ob

ROT_FACE_NEG_Y = (math.radians(90), 0, 0)               # plane faces -Y (into the room)
ROT_FACE_POS_Y = (math.radians(90), 0, math.radians(180))  # plane faces +Y, not mirrored

# ---------------------------------------------------------------- clean previous run
for sc in [s for s in bpy.data.scenes if s.name.startswith('PV3_')]:
    bpy.data.scenes.remove(sc)
for coll_name in ('objects', 'meshes', 'curves', 'cameras', 'lights', 'materials',
                  'collections', 'worlds', 'actions'):
    data = getattr(bpy.data, coll_name)
    for item in [i for i in data if i.name.startswith('PV3_')]:
        try:
            data.remove(item)
        except Exception:
            pass

m_harbor = mat_harbor('PV3_Harbor')

# ================================================================= SPACE
space = make_scene('PV3_Space', int(T_SPACE * FPS), make_world('PV3_World_Space', (0.0, 0.0, 0.002)))
c_space = bpy.data.collections.new('PV3_Space_Set'); space.collection.children.link(c_space)

m_earth, nt, out = new_mat('PV3_Earth')
b = nt.nodes.new('ShaderNodeBsdfPrincipled'); b.inputs['Roughness'].default_value = 0.8
tc = nt.nodes.new('ShaderNodeTexCoord')
nz = nt.nodes.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = 0.006; nz.inputs['Detail'].default_value = 8
ramp = nt.nodes.new('ShaderNodeValToRGB'); el = ramp.color_ramp.elements
el[0].position, el[0].color = 0.5, (0.02, 0.07, 0.2, 1)
el[1].position, el[1].color = 0.55, (0.22, 0.24, 0.13, 1)
nt.links.new(tc.outputs['Object'], nz.inputs['Vector'])
nt.links.new(nz.outputs['Fac'], ramp.inputs['Fac'])
nt.links.new(ramp.outputs['Color'], b.inputs['Base Color'])
nt.links.new(b.outputs[0], out.inputs['Surface'])
m_earth.diffuse_color = (0.05, 0.12, 0.25, 1)
sphere('PV3_Earth', R_EARTH, (0, 0, -R_EARTH), c_space, m_earth, 256, 128)
plane('PV3_Harbor', PATCH_W, PATCH_H, (0, 0, 0.03), c_space, m_harbor)

# a few cloud puffs between the satellite and the harbor (they drift through the zoom)
m_cloud = mat_basic('PV3_Cloud', (0.9, 0.92, 0.95), rough=0.9)
for i, (x, y, z, s) in enumerate(((7.5, 4.0, 45, 3.0), (-10, -5, 60, 4.0), (6.0, -4.5, 30, 1.6), (-5.5, 3.5, 22, 1.2))):   # all outside the final frame
    ob = sphere(f'PV3_Cloud_{i}', s, (x, y, z), c_space, m_cloud, 16, 8)
    ob.scale = (1.0, 0.6, 0.15)
    ob.visible_shadow = False

sun_d = bpy.data.lights.new('PV3_Sun', 'SUN'); sun_d.energy = 4.0; sun_d.angle = math.radians(0.6)
sun = bpy.data.objects.new('PV3_Sun', sun_d); c_space.objects.link(sun)
sun.rotation_euler = Vector((-0.6, 0.35, -0.7)).normalized().to_track_quat('-Z', 'Y').to_euler()

# satellite: body along X, lens on the -X end; pivots about its own centre around Y
sat = bpy.data.objects.new('PV3_Satellite', None); c_space.objects.link(sat)
sat.location = (0, 0, SAT_Z)
m_foil = mat_basic('PV3_Foil', (0.78, 0.8, 0.84), metal=0.6, rough=0.35)
m_gold = mat_basic('PV3_Gold', (0.85, 0.6, 0.2), metal=0.6, rough=0.4)
m_dark = mat_basic('PV3_LensGlass', (0.02, 0.02, 0.03), metal=0.2, rough=0.1)
m_red = mat_emit('PV3_LensMarker', (1.0, 0.1, 0.05), 2.0)      # previz marker: this end is the lens
m_white = mat_basic('PV3_White', (0.9, 0.9, 0.9), rough=0.4)
m_cells = mat_basic('PV3_Cells', (0.03, 0.06, 0.2), metal=0.3, rough=0.25)
Y90 = (0, math.radians(90), 0)
cyl('PV3_Sat_Body', 0.9, 3.6, (0, 0, 0), c_space, m_foil, rot=Y90, parent=sat)
cyl('PV3_Sat_Band', 0.93, 0.5, (0.4, 0, 0), c_space, m_gold, rot=Y90, parent=sat)
cyl('PV3_Sat_LensBarrel', 0.6, 0.9, (-2.2, 0, 0), c_space, m_dark, rot=Y90, parent=sat)
cyl('PV3_Sat_LensRing', 0.68, 0.12, (-2.62, 0, 0), c_space, m_red, rot=Y90, cap=False, parent=sat)
cyl('PV3_Sat_Dish', 0.55, 0.15, (0.6, 0, 1.35), c_space, m_white, r2=0.05, parent=sat)
cyl('PV3_Sat_Mast', 0.03, 1.4, (-0.4, 0.2, 1.6), c_space, m_white, parent=sat)
m_glow = mat_emit('PV3_AntennaGlow', (0.8, 0.9, 1.0), 0.0)
sphere('PV3_Sat_AntennaGlow', 0.12, (-0.4, 0.2, 2.35), c_space, m_glow, parent=sat)
cyl('PV3_Sat_SmallDish', 0.3, 0.1, (0.2, 0, -1.0), c_space, m_white, r2=0.05, rot=(math.pi, 0, 0), parent=sat)
for s in (-1, 1):
    cyl(f'PV3_Sat_Boom_{s}', 0.05, 1.0, (0.4, s * 1.4, 0), c_space, m_white, rot=(math.radians(90), 0, 0), parent=sat)
    for i in range(3):
        box(f'PV3_Sat_Panel_{s}_{i}', (1.6, 1.5, 0.05), (0.4, s * (2.7 + 1.6 * i), 0), c_space, m_cells,
            rot=(0, 0, math.radians(90)), parent=sat)

# antenna glow: two soft pulses at ~1 s
for t, v in ((0.95, 0), (1.15, 40), (1.4, 5), (1.6, 40), (1.95, 0)):
    s_ = m_glow.node_tree.nodes['Emission'].inputs['Strength']
    s_.default_value = v
    s_.keyframe_insert('default_value', frame=f_of(t))

# rotation in place: lens swings from screen-left (level) to straight down, 2.0 -> 5.5 s
for t, deg in ((0.0, 0.0), (2.0, 0.0), (5.5, -90.0), (T_SPACE, -90.0)):
    sat.rotation_euler = (0, math.radians(deg), 0)
    sat.keyframe_insert('rotation_euler', frame=f_of(t))

cam_space = make_camera('PV3_Cam_Space', c_space)
space.camera = cam_space
SAT_C = Vector((0, 0, SAT_Z))
DOWN, UP_Y = Vector((0, 0, -1)), Vector((0, 1, 0))
space_knots = [
    (0.0, Vector((0.0, 0.0, 142.0)), Vector((0.2, 0.0, -2.5))),
    (2.0, Vector((1.0, 0.0, 137.0)), Vector((1.2, 0.0, -3.0))),
    (5.5, Vector((6.0, 0.0, 127.0)), Vector((0.6, 0.0, -4.5))),
    (7.0, Vector((5.0, 0.0, 117.5)), Vector((-3.0, 0.0, -1.5))),
    (8.0, Vector((0.0, 0.0, Z_ALIGN)), Vector((0.0, 0.0, -1.0))),
]

def space_pose(t):
    if t <= 8.0:
        loc = hermite(space_knots, t)
    else:   # lined up under the lens: keep sinking slowly while the optical zoom runs
        u = smooth((t - 8.0) / 4.0)
        loc = Vector((0, 0, Z_ALIGN + (Z_FINAL - Z_ALIGN) * u))
    w = smooth((t - 6.0) / 1.6)          # look at the satellite, then straight down
    to_sat = (SAT_C - loc).normalized()
    fwd = to_sat.lerp(DOWN, w) if t < 7.6 else DOWN.copy()
    if t <= 8.0:
        focal = 24.0
    else:                                 # constant-ratio zoom 24 mm -> F_FINAL, settled by 12 s
        u = smooth((t - 8.0) / 4.0)
        focal = math.exp(math.log(24.0) + (math.log(F_FINAL) - math.log(24.0)) * u)
    return loc, fwd, UP_Y, focal

bake(cam_space, list(range(1, space.frame_end + 1)), space_pose)

# ================================================================= OFFICE
office = make_scene('PV3_Office', int(T_OFFICE * FPS), make_world('PV3_World_Office', (0.004, 0.005, 0.008)))
c_off = bpy.data.collections.new('PV3_Office_Set'); office.collection.children.link(c_off)
m_floor = mat_basic('PV3_Floor', (0.03, 0.035, 0.045), rough=0.6)
m_wall = mat_basic('PV3_Wall', (0.04, 0.045, 0.06), rough=0.8)
m_desk = mat_basic('PV3_Desk', (0.1, 0.105, 0.12), rough=0.4)
m_black = mat_basic('PV3_Black', (0.01, 0.01, 0.012), rough=0.3)
m_shirt = mat_basic('PV3_Shirt', (0.06, 0.08, 0.2), rough=0.8)
m_skin = mat_basic('PV3_Skin', (0.45, 0.32, 0.26), rough=0.5)
m_hair = mat_basic('PV3_Hair', (0.08, 0.05, 0.03), rough=0.6)
m_ui = mat_emit('PV3_UI', (0.03, 0.15, 0.25), 1.5)
m_lamp = mat_emit('PV3_Lamp', (1.0, 0.7, 0.4), 6.0)
m_card = mat_emit('PV3_Card', (0.02, 0.02, 0.025), 1.0)
m_cardline = mat_emit('PV3_CardLine', (0.6, 0.62, 0.66), 1.5)
m_blue = mat_emit('PV3_Periwinkle', (0.45, 0.6, 1.0), 3.0)
m_txt = mat_emit('PV3_Text', (0.75, 0.8, 0.9), 2.0)

box('PV3_Floor', (28, 27, 0.1), (0, -0.5, -0.05), c_off, m_floor)
box('PV3_Ceiling', (28, 27, 0.1), (0, -0.5, 9.05), c_off, m_wall)
box('PV3_Wall_Front', (28, 0.1, 9.2), (0, SCREEN_Y + 0.15, 4.5), c_off, m_wall)
box('PV3_Wall_Back', (28, 0.1, 9.2), (0, -13.05, 4.5), c_off, m_wall)
for s in (-1, 1):
    box(f'PV3_Wall_Side_{s}', (0.1, 27, 9.2), (s * 14.05, -0.5, 4.5), c_off, m_wall)
box('PV3_Wall_Bezel', (SCREEN_W + 0.2, 0.1, SCREEN_H + 0.2), (0, SCREEN_Y + 0.06, SCREEN_C.z), c_off, m_black)
plane('PV3_VideoWall', SCREEN_W, SCREEN_H, (0, SCREEN_Y - 0.01, SCREEN_C.z), c_off, m_harbor, rot=ROT_FACE_NEG_Y)
wl = bpy.data.lights.new('PV3_WallLight', 'AREA'); wl.shape, wl.size, wl.size_y = 'RECTANGLE', SCREEN_W, SCREEN_H
wl.energy, wl.color = 2500, (0.6, 0.72, 1.0)
wlo = bpy.data.objects.new('PV3_WallLight', wl); c_off.objects.link(wlo)
wlo.location, wlo.rotation_euler = (0, SCREEN_Y - 0.3, SCREEN_C.z), (math.radians(-90), 0, 0)

# rows of desks facing the wall, with monitors (screens face -Y, toward the chairs)
for r, ry in enumerate((6.0, 2.0, -2.0)):
    for s in (-1, 1):
        box(f'PV3_Desk_{r}_{s}', (10.0, 0.8, 0.75), (s * 6.0, ry + 0.3, 0.375), c_off, m_desk)
        for k in range(5):
            x = s * (1.6 + 1.8 * k)
            box(f'PV3_Mon_{r}_{s}_{k}', (0.6, 0.04, 0.36), (x, ry + 0.55, 1.05), c_off, m_black)
            plane(f'PV3_MonScr_{r}_{s}_{k}', 0.56, 0.32, (x, ry + 0.528, 1.05), c_off, m_ui, rot=ROT_FACE_NEG_Y)

# the operator's desk in the back row: he faces -Y when working, his back to the wall
box('PV3_OpDesk', (3.0, 0.8, 0.75), (OP_X, DESK_Y, 0.375), c_off, m_desk)
MON_C = Vector((OP_X, DESK_Y - 0.15, 1.15))
box('PV3_OpMonitor', (0.74, 0.04, 0.44), MON_C + Vector((0, -0.03, 0)), c_off, m_black)
dash = plane('PV3_OpDashboard', 0.704, 0.396, MON_C + Vector((0, 0.0, 0)), c_off, m_ui, rot=ROT_FACE_POS_Y)
text('PV3_OpLogo', 'ORCA  SAT-150', 0.028, c_off, m_txt, MON_C + Vector((0.33, 0.004, 0.16)), ROT_FACE_POS_Y)
# pop-up card (bottom-right of the screen) and the opened photo
pop = bpy.data.objects.new('PV3_Popup', None); c_off.objects.link(pop)
pop.location, pop.rotation_euler = MON_C + Vector((-0.2, 0.006, -0.12)), ROT_FACE_POS_Y
plane('PV3_Popup_Card', 0.2, 0.07, (0, 0, 0), c_off, m_card, parent=pop)
for i, (dx, dy) in enumerate(((-0.1, -0.035), (0.1, -0.035), (0.1, 0.035), (-0.1, 0.035))):
    plane(f'PV3_Popup_Corner_{i}', 0.008, 0.008, (dx, dy, 0.001), c_off, m_blue, parent=pop)
text('PV3_Popup_Title', 'New images', 0.018, c_off, m_blue, (-0.085, 0.008, 0.002), (0, 0, 0), parent=pop)
text('PV3_Popup_Body', 'SAT-150 · Image 001', 0.012, c_off, m_txt, (-0.085, -0.02, 0.002), (0, 0, 0), parent=pop)
photo = plane('PV3_OpPhoto', 0.62, 0.62 * 9 / 16, MON_C + Vector((0, 0.008, -0.01)), c_off, m_harbor, rot=ROT_FACE_POS_Y)
for ob in [pop] + [c for c in pop.children]:
    vis(ob, f_of(8.3), f_of(10.0))
vis(photo, f_of(10.0), None)
lamp = sphere('PV3_DeskLamp', 0.09, (OP_X + 0.9, DESK_Y, 1.35), c_off, m_lamp)
ll = bpy.data.lights.new('PV3_LampLight', 'POINT'); ll.energy, ll.color = 40, (1.0, 0.7, 0.4)
llo = bpy.data.objects.new('PV3_LampLight', ll); c_off.objects.link(llo); llo.location = (OP_X + 0.9, DESK_Y + 0.1, 1.45)

# chair + seated operator, one rig: root rotates (swivel) and moves (rolls in)
rig = bpy.data.objects.new('PV3_ChairRig', None); c_off.objects.link(rig)
box('PV3_Chair_Seat', (0.5, 0.5, 0.08), (0, 0, 0.45), c_off, m_black, parent=rig)
box('PV3_Chair_Back', (0.5, 0.08, 0.6), (0, -0.27, 0.8), c_off, m_black, parent=rig)
cyl('PV3_Chair_Post', 0.04, 0.4, (0, 0, 0.22), c_off, m_black, parent=rig)
hip = bpy.data.objects.new('PV3_Operator', None); c_off.objects.link(hip)
hip.parent, hip.location = rig, (0, 0, 0.5)
cyl('PV3_Op_Torso', 0.19, 0.6, (0, 0, 0.3), c_off, m_shirt, parent=hip)
box('PV3_Op_Shoulders', (0.46, 0.22, 0.12), (0, 0, 0.56), c_off, m_shirt, parent=hip)
head = sphere('PV3_Op_Head', 0.115, (0, 0.02, 0.78), c_off, m_skin, parent=hip)
sphere('PV3_Op_Hair', 0.12, (0, -0.01, 0.82), c_off, m_hair, parent=hip)
for s in (-1, 1):
    box(f'PV3_Op_Arm_{s}', (0.09, 0.4, 0.09), (s * 0.22, 0.2, 0.32), c_off, m_shirt, parent=hip)
    box(f'PV3_Op_Thigh_{s}', (0.15, 0.45, 0.15), (s * 0.11, 0.2, -0.02), c_off, m_shirt, parent=hip)

def key_rig(t, x, y, rz):
    rig.location = (x, y, 0)
    rig.rotation_euler = (0, 0, math.radians(rz))
    rig.keyframe_insert('location', frame=f_of(t))
    rig.keyframe_insert('rotation_euler', frame=f_of(t))

# facing the wall (+Y) at the start; swivel 180 deg to the desk (-Y) and roll in, 5.5 -> 8 s
key_rig(0.0, OP_X, DESK_Y + 1.5, 0)
key_rig(5.5, OP_X, DESK_Y + 1.5, 0)
key_rig(8.0, OP_X, DESK_Y + 0.9, 180)
for t, rx in ((0, 0), (9.0, 0), (9.6, -10), (12.0, -12)):       # leans in toward the monitor
    hip.rotation_euler = (math.radians(rx), 0, 0)
    hip.keyframe_insert('rotation_euler', frame=f_of(t))

cam_off = make_camera('PV3_Cam_Office', c_off, clip=(0.01, 300))
office.camera = cam_off
HEAD = Vector((OP_X, DESK_Y + 1.2, 1.3))
WALL_FILL = Vector((0, SCREEN_Y - (SCREEN_W / 2) / 0.75, SCREEN_C.z))   # wall exactly fills the frame (24 mm)
office_knots = [
    (0.0, WALL_FILL, Vector((0, 0, 0))),
    (0.5, WALL_FILL, Vector((0, 0, 0))),
    (5.5, Vector((OP_X + 1.0, DESK_Y - 1.4, 2.0)), Vector((0, 0, 0))),
    (6.8, Vector((OP_X + 1.5, DESK_Y + 1.8, 2.6)), Vector((-0.9, 0.6, 0))),
    (8.0, Vector((OP_X - 0.6, DESK_Y + 1.7, 1.95)), Vector((0, 0, 0))),
    (12.0, Vector((OP_X - 0.55, DESK_Y + 1.45, 1.85)), Vector((0, 0, 0))),
]

def office_pose(t):
    loc = hermite(office_knots, t)
    if t <= 0.5:
        return loc, Vector((0, 1, 0)), Vector((0, 0, 1))
    low = Vector((0.8, SCREEN_Y, 3.2))   # aim a little lower so he enters the frame
    def towards(a, b, w):                # blend view directions, not target points
        return (a - loc).normalized().lerp((b - loc).normalized(), w)
    if t <= 5.5:
        fwd = towards(SCREEN_C, low, smooth((t - 0.5) / 5.0))
    elif t <= 6.8:
        fwd = towards(low, HEAD, smooth((t - 5.5) / 0.9))    # keep him in frame while he swivels
    else:
        fwd = towards(HEAD, MON_C, smooth((t - 6.8) / 1.2))  # then over his shoulder to the monitor
    return loc, fwd, Vector((0, 0, 1))

bake(cam_off, list(range(1, office.frame_end + 1)), office_pose)

# ================================================================= EDIT (25 s)
edit = make_scene('PV3_Edit', int((T_SPACE + T_OFFICE) * FPS), office.world)
se = edit.sequence_editor_create()
strips = se.strips if hasattr(se, 'strips') else se.sequences
st1 = strips.new_scene('PV3_Shot_Space', space, 1, 1); st1.scene_camera = cam_space
st2 = strips.new_scene('PV3_Shot_Office', office, 1, space.frame_end + 1); st2.scene_camera = cam_off
edit.render.filepath = '//orca_shot3_previz_'
try:
    edit.render.image_settings.media_type = 'VIDEO'
except Exception:
    pass
try:
    edit.render.image_settings.file_format = 'FFMPEG'
    edit.render.ffmpeg.format, edit.render.ffmpeg.codec = 'MPEG4', 'H264'
except Exception:
    pass
for t, label in ((0.0, 'Top view, descending'), (1.0, 'Antenna glow'), (1.5, 'Card: New task'),
                 (2.0, 'Satellite rotates in place, lens tips down'), (5.5, 'Rotation done, camera passes right of it'),
                 (8.0, 'Lined up under the lens, viewfinder in'), (8.5, 'Optical zoom (focal length only)'),
                 (12.0, 'Capture'), (13.0, 'CUT: same photo on the video wall'), (13.5, 'Slow pull-back'),
                 (18.5, 'He swivels back to his desk'), (21.3, 'Pop-up: New images'), (23.0, 'Click: photo opens')):
    edit.timeline_markers.new(label, frame=f_of(t))

win = None if bpy.app.background else bpy.context.window
if win is not None:
    win.scene = space
    space.frame_set(1)
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            for sp in area.spaces:
                if sp.type == 'VIEW_3D':
                    sp.region_3d.view_perspective = 'CAMERA'
                    sp.shading.type = 'MATERIAL'
print('ORCA shot 3 previz built:', [s.name for s in bpy.data.scenes if s.name.startswith('PV3_')])
