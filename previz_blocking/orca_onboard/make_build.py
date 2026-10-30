"""Regenerates build_orca_onboard.py: ONE self-contained file to run in Blender
(and ../live.py, which the live bridge watches). Embeds previz_core, the solved
bake and scene.json, so nothing has to sit at a particular path."""
import json, os
H = os.path.dirname(os.path.abspath(__file__))
def rnd(o):
    if isinstance(o, float): return round(o, 4)
    if isinstance(o, (list, tuple)): return [rnd(x) for x in o]
    if isinstance(o, dict): return {k: rnd(v) for k, v in o.items()}
    return o
core = open(os.path.join(H, "previz_core.py")).read()
bake = json.dumps(rnd(json.load(open(os.path.join(H, "bake.json")))), separators=(",", ":"))
scene = json.dumps(json.load(open(os.path.join(H, "scene.json"))), separators=(",", ":"))

BUILD = r'''
import bpy, bmesh, json, math, os, random, tempfile
from mathutils import Vector, Matrix

mod = type(bpy)("PV"); mod.__dict__["__file__"] = "previz_core.py"
exec(CORE, mod.__dict__)
bpy.app.driver_namespace["PV"] = PV = mod
G = json.loads(SCENE)
FPS, NF = G["fps"], G["frames"]
def F(t): return int(round(t * FPS)) + 1          # seconds -> frame

for o in list(bpy.data.objects):                    # text/HUD objects too
    if o.name.startswith(("SET_", "HUD_")): bpy.data.objects.remove(o, do_unlink=True)
PV.wipe()
PV.reset(fps=FPS, seconds=NF / FPS)
sc = bpy.context.scene
sc.world.color = (0.006, 0.007, 0.010)              # space is black; the room is lit by studio light
sc.view_settings.view_transform = 'AgX'

def keys(o, chans):
    """sparse keys: {(path, index): [(frame, value), ...]} -- linear"""
    cb = PV._cbag(o, "ACT_" + o.name, 'OBJECT', o.name)
    for (path, idx), kv in chans.items():
        fc = cb.fcurves.new(path, index=idx)
        fc.keyframe_points.add(len(kv))
        fc.keyframe_points.foreach_set("co", [x for f, v in kv for x in (f, v)])
        fc.keyframe_points.foreach_set("interpolation", [1] * len(kv)); fc.update()

def pop(on, off=None, dur=0.35):
    """scale keys: appears at `on` seconds, vanishes at `off`"""
    k = [(1, 0.0), (F(on), 0.0), (F(on + dur), 1.0)]
    if off is not None: k += [(F(off), 1.0), (F(off + dur), 0.0)]
    return k

def mesh_obj(name, verts, faces, color):
    me = bpy.data.meshes.new(name + "_m"); me.from_pydata(verts, [], faces); me.update()
    o = bpy.data.objects.new(name, me); PV.coll("SET").objects.link(o)
    o.data.materials.append(PV._matfor(color))
    return o

def on_surface(o, p, lift=0.0):
    """sit o on Earth at p, local +Z along the surface normal"""
    c = Vector(G["earth"]["c"]); n = (Vector(p) - c).normalized()
    o.rotation_mode = 'QUATERNION'
    o.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(n)
    o.location = Vector(p) + n * lift

# =============================================================== the room ===
# mission control: console tiers stepping up to the back, a giant video wall
# at the front (plane y = 0). Empty -- no operators.
R, SCR, T = G["room"], G["screen"], G["tier"]
hw, back, ceil = R["half_w"], R["back"], R["ceil"]
WALL, FLOOR, DESK, CHAIR = (0.11, 0.12, 0.14), (0.07, 0.075, 0.085), (0.20, 0.21, 0.23), (0.05, 0.05, 0.06)
UI, UI_HI, SCREEN_GLOW = (0.05, 0.13, 0.22), (0.10, 0.24, 0.38), (0.45, 0.70, 0.95)

PV.slab("SET_floor_front", (2 * hw, -T["front"] + 0.3, 0.2), (0, T["front"] / 2, -0.1), FLOOR)
for i in range(T["n"]):
    yf = T["front"] - T["depth"] * i; yb = yf - T["depth"]; zt = T["rise"] * (i + 1)
    PV.slab(f"SET_tier_{i}", (2 * hw, T["depth"], zt), (0, (yf + yb) / 2, 0), FLOOR, base=True)
    PV.slab(f"SET_desk_{i}", (2 * hw - 2.4, 0.8, 0.75), (0, yf - 0.55, zt), DESK, base=True)
    nmon = int((2 * hw - 3.6) / 1.5)
    PV.row(f"SET_mon_{i}", (0.8, 0.06, 0.5), (-hw + 1.9, yf - 0.32, zt + 0.75), nmon, 1.5,
           axis="x", color=UI_HI, base=True)
    PV.row(f"SET_chair_{i}", (0.55, 0.55, 0.95), (-hw + 1.9, yf - 1.55, zt), nmon, 1.5,
           axis="x", color=CHAIR, base=True)
yb = T["front"] - T["depth"] * T["n"]
PV.slab("SET_walkway", (2 * hw, yb - back, T["rise"] * (T["n"] + 1)), (0, (yb + back) / 2, 0), FLOOR, base=True)
PV.slab("SET_rail", (2 * hw, 0.08, 1.0), (0, yb + 0.1, T["rise"] * (T["n"] + 1)), DESK, base=True)

PV.slab("SET_wall_L", (0.3, -back, ceil), (-hw - 0.15, back / 2, 0), WALL, base=True)
PV.slab("SET_wall_R", (0.3, -back, ceil), (hw + 0.15, back / 2, 0), WALL, base=True)
PV.slab("SET_wall_back", (2 * hw + 0.6, 0.3, ceil), (0, back - 0.15, 0), WALL, base=True)
PV.slab("SET_ceiling", (2 * hw + 0.6, -back + 0.3, 0.3), (0, back / 2, ceil + 0.15), WALL)
for x in (-9.0, -4.5, 0.0, 4.5, 9.0):                      # recessed ceiling light panels
    PV.row(f"SET_lamp_{x:+.0f}", (1.3, 1.3, 0.06), (x, back + 1.5, ceil - 0.03), 6, 3.0,
           axis="y", color=(0.85, 0.88, 0.92))
# wall-side panels (the dark acoustic panels down both side walls)
for sx in (-1, 1):
    PV.row(f"SET_sidepanel_{sx:+d}", (0.08, 2.6, 3.0), (sx * (hw - 0.05), back + 2.0, 3.2), 6, 3.0,
           axis="y", color=(0.09, 0.10, 0.13), base=True)

# the video wall: a frame round the centre-screen OPENING (space is behind it)
w2, z0, z1 = SCR["w"] / 2, SCR["z0"], SCR["z0"] + SCR["h"]
PV.slab("SET_vwall_L", (hw - w2, 0.3, ceil), (-(hw + w2) / 2, 0.15, 0), WALL, base=True)
PV.slab("SET_vwall_R", (hw - w2, 0.3, ceil), ((hw + w2) / 2, 0.15, 0), WALL, base=True)
PV.slab("SET_vwall_top", (SCR["w"], 0.3, ceil - z1), (0, 0.15, z1), WALL, base=True)
PV.slab("SET_vwall_bot", (SCR["w"], 0.3, z0), (0, 0.15, 0), WALL, base=True)
BZ = (0.015, 0.015, 0.02)
PV.slab("SET_bezel_top", (SCR["w"] + 0.4, 0.12, 0.2), (0, -0.06, z1 + 0.1), BZ)
PV.slab("SET_bezel_bot", (SCR["w"] + 0.4, 0.12, 0.2), (0, -0.06, z0 - 0.1), BZ)
PV.slab("SET_bezel_L", (0.2, 0.12, SCR["h"]), (-w2 - 0.1, -0.06, (z0 + z1) / 2), BZ)
PV.slab("SET_bezel_R", (0.2, 0.12, SCR["h"]), (w2 + 0.1, -0.06, (z0 + z1) / 2), BZ)
# side display panels, angled toward the room (the wall curves)
for sx in (-1, 1):
    a = math.radians(12) * -sx
    cx = sx * (w2 + 0.25 + 1.75); cy = -0.45
    PV.slab(f"SET_side_{sx:+d}", (3.5, 0.08, SCR["h"]), (cx, cy, (z0 + z1) / 2), UI, rot=(0, 0, a))
    for j, (h, dz) in enumerate(((1.3, 1.45), (1.3, 0.0), (1.3, -1.45))):
        PV.slab(f"SET_side_{sx:+d}_{j}", (3.2, 0.03, h), (cx - 0.06 * math.sin(a) * 0, cy - 0.06,
                (z0 + z1) / 2 + dz), UI_HI if j == 0 else (0.08, 0.20, 0.32), rot=(0, 0, a))
PV.slab("SET_vwall_strip", (2 * hw, 0.1, 0.12), (0, -0.08, z1 + 0.55), (0.30, 0.40, 0.50))

# ============================================================== the space ===
E = G["earth"]
bpy.ops.mesh.primitive_uv_sphere_add(segments=160, ring_count=80, radius=E["r"], location=E["c"])
o = bpy.context.active_object; o.name = "SET_earth"
for c in list(o.users_collection): c.objects.unlink(o)
PV.coll("SET").objects.link(o); o.data.materials.append(PV._matfor((0.05, 0.16, 0.45)))
bpy.ops.object.shade_smooth()
rnd = random.Random(3)
# land and cloud patches near the harbour, so the planet has a surface to read
hx, hy = G["harbor"][0], G["harbor"][1]
LAND = [(hx + 9, hy + 3, 8.0), (hx + 20, hy - 8, 10.0), (hx - 6, hy + 22, 7.0), (hx + 12, hy + 30, 9.0),
        (hx - 25, hy + 8, 11.0), (hx + 35, hy + 18, 12.0), (hx - 14, hy - 18, 6.0), (hx + 2, hy + 55, 14.0)]
for i, (x, y, r) in enumerate(LAND):
    me_o = PV.cyl(f"SET_land_{i}", r, 0.3, (0, 0, 0), color=(0.16, 0.30, 0.12), verts=9)
    me_o.scale = (1.0, rnd.uniform(0.55, 1.0), 1.0)
    me_o.location = (x, y, 0)
for i in range(16):
    x, y = hx + rnd.uniform(-45, 45), hy + rnd.uniform(-30, 70)
    cl = PV.cyl(f"SET_cloud_{i}", rnd.uniform(2.5, 7.0), 0.2, (0, 0, 0), color=(0.62, 0.66, 0.70), verts=10)
    cl.scale = (1.0, rnd.uniform(0.3, 0.7), 1.0)
    cl.location = (x, y, 0)
# sit every patch on the true surface point of the sphere
def _fix(o):
    c = Vector(E["c"]); p = Vector((o.location.x, o.location.y, 0.0))
    z = c.z + math.sqrt(max(E["r"] ** 2 - (p.x - c.x) ** 2 - (p.y - c.y) ** 2, 0.0))
    lift = 0.05 if o.name.startswith("SET_land") else 1.2
    on_surface(o, (p.x, p.y, z), lift)
for o in bpy.data.objects:
    if o.name.startswith(("SET_land_", "SET_cloud_")): _fix(o)

# stars: one mesh of tiny icospheres on a far shell (behind the video wall)
bm = bmesh.new()
for i in range(700):
    while True:
        v = Vector((rnd.gauss(0, 1), rnd.gauss(0, 1), rnd.gauss(0, 1))).normalized()
        if v.y > -0.15: break
    p = Vector((0, 60, 0)) + v * 320
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=rnd.uniform(0.25, 0.6),
                               matrix=Matrix.Translation(p))
me = bpy.data.meshes.new("SET_stars_m"); bm.to_mesh(me); bm.free()
st = bpy.data.objects.new("SET_stars", me); PV.coll("SET").objects.link(st)
st.data.materials.append(PV._matfor((0.85, 0.87, 0.90)))

# the satellite: gold body along y, two big solar panels facing the camera path
SX, SY, SZ = G["sat"]
GOLD, PANEL, SILVER = (0.72, 0.52, 0.12), (0.06, 0.10, 0.32), (0.62, 0.63, 0.65)
PV.cyl("SET_sat_body", 0.9, 3.6, (SX, SY, SZ), color=GOLD, axis="y", verts=16)
PV.cyl("SET_sat_front", 0.75, 0.5, (SX, SY - 2.0, SZ), color=SILVER, axis="y", verts=16)
PV.cyl("SET_sat_lens", 0.45, 0.2, (SX, SY - 2.3, SZ), color=(0.02, 0.02, 0.03), axis="y", verts=16)
for sx in (-1, 1):
    PV.slab(f"SET_sat_arm_{sx:+d}", (1.2, 0.12, 0.12), (SX + sx * 1.4, SY + 0.3, SZ), SILVER)
    PV.slab(f"SET_sat_panel_{sx:+d}", (5.0, 0.06, 1.8), (SX + sx * 4.5, SY + 0.3, SZ), PANEL)
    PV.cyl(f"SET_sat_ant_{sx:+d}", 0.05, 1.1, (SX + sx * 0.45, SY + 0.6, SZ + 1.4), color=SILVER, verts=6)

# one rig for the whole satellite, yawed so it reads side-on
sat = bpy.data.objects.new("SET_sat", None); PV.coll("SET").objects.link(sat)
sat.location = (SX, SY, SZ); bpy.context.view_layer.update()
for o in list(bpy.data.objects):
    if o.name.startswith("SET_sat_"):
        o.parent = sat; o.matrix_parent_inverse = sat.matrix_world.inverted()
sat.rotation_euler = (math.radians(-6), 0, math.radians(G["sat_yaw"]))

# the signal beam: rises from the ground station on Earth up to the satellite
def beam(name, a, b, radius, color):
    a, b = Vector(a), Vector(b); d = b - a
    bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=radius, depth=1.0, location=(0, 0, 0))
    o = bpy.context.active_object; o.name = name
    for c in list(o.users_collection): c.objects.unlink(o)
    PV.coll("SET").objects.link(o)
    o.data.transform(Matrix.Translation((0, 0, 0.5)))       # base on the origin
    o.data.materials.append(PV._matfor(color))
    o.rotation_mode = 'QUATERNION'
    o.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d.normalized())
    o.location = a
    return o, d.length
ev = G["ev"]
bm_o, L = beam("SET_signal", G["beam_foot"], (SX, SY, SZ - 0.9), 0.12, (0.45, 0.85, 1.0))
u0, u1 = ev["beam_up"]; f0, f1 = ev["beam_off"]
keys(bm_o, {("scale", 2): [(1, 0.001), (F(u0), 0.001), (F(u1), L), (F(f0), L), (F(f1), 0.001)],
            ("scale", 0): [(1, 1), (F(f0), 1), (F(f1), 0.001)],
            ("scale", 1): [(1, 1), (F(f0), 1), (F(f1), 0.001)]})
gs = PV.cyl("SET_groundstation", 0.8, 0.4, (0, 0, 0), color=(0.45, 0.85, 1.0), verts=12)
on_surface(gs, G["beam_foot"], 0.2)

# the hexagon imaging zone on the harbour + its scan bar + the imaging cone
HR = 6.0
outer = [(HR * math.cos(math.radians(60 * k + 30)), HR * math.sin(math.radians(60 * k + 30)), 0) for k in range(6)]
inner = [(0.88 * x, 0.88 * y, 0) for x, y, _ in outer]
hexo = mesh_obj("SET_hex", outer + inner, [(k, (k + 1) % 6, 6 + (k + 1) % 6, 6 + k) for k in range(6)],
                (0.95, 0.55, 0.10))
on_surface(hexo, G["harbor"], 0.4)
hexo.scale = (1, 1, 1)
fill = mesh_obj("SET_hex_fill", inner, [tuple(range(6))], (0.95, 0.55, 0.10))
fill.parent = hexo; fill.location = (0, 0, -0.02)
bar = PV.slab("SET_hex_scan", (0.35, 2 * HR * 0.9, 0.08), (0, 0, 0.05), (1.0, 0.95, 0.85))
bar.parent = hexo
s0, s1 = ev["scan"]
sweep = [(1, -0.75 * HR)] + [(F(s0 + k * (s1 - s0) / 4), (-0.75 if k % 2 == 0 else 0.75) * HR) for k in range(5)]
keys(bar, {("location", 0): sweep, ("location", 1): [(1, 0.0)], ("location", 2): [(1, 0.05)]})
keys(hexo, {("scale", k): pop(ev["hex_on"]) for k in range(3)})
cone_o, Lc = beam("SET_img_cone", (SX, SY, SZ - 0.9), G["harbor"], 1.0, (1.0, 0.80, 0.30))
# turn the cylinder into a hexagonal cone: narrow at the satellite, wide on the zone
me = cone_o.data
for v in me.vertices:
    k = v.co.z                               # 0 at the satellite .. 1 at the zone
    v.co.x *= 0.15 + (HR - 0.15) * k; v.co.y *= 0.15 + (HR - 0.15) * k
c0, c1 = ev["cone"]
keys(cone_o, {("scale", 2): [(1, Lc)], ("scale", 0): pop(c0, c1), ("scale", 1): pop(c0, c1)})

# ================================================================ camera ====
bake_path = os.path.join(tempfile.gettempdir(), "orca_onboard_bake.json")
open(bake_path, "w").write(BAKE)
PV.load_bake(bake_path)
hero = bpy.data.objects.get("HERO") or bpy.data.objects.get("RIG_HERO_root")
for o in bpy.data.objects:                   # the attention point is invisible
    if o.name.startswith(("HERO", "RIG_HERO")): o.hide_viewport = o.hide_render = True
cam = bpy.data.objects["CAM_01"]
cam.data.clip_start, cam.data.clip_end = 0.05, 1200.0

# ============================================================ HUD cards =====
# screen-space cards, parented to the camera 1 m in front of the lens
def card(name, size, loc, lines, on, off, line_on=None):
    pl = PV.slab("HUD_" + name, (size[0], size[1], 0.004), (0, 0, 0), (0.02, 0.05, 0.09))
    for c in list(pl.users_collection): c.objects.unlink(pl)
    PV.coll("HUD").objects.link(pl)
    pl.parent = cam; pl.location = loc
    keys(pl, {("scale", k): pop(on, off, 0.3) for k in range(3)})
    for j, (txt, sz) in enumerate(lines):
        cu = bpy.data.curves.new("HUD_" + name + f"_t{j}", 'FONT'); cu.body = txt; cu.size = sz
        t = bpy.data.objects.new("HUD_" + name + f"_t{j}", cu); PV.coll("HUD").objects.link(t)
        t.data.materials.append(PV._matfor((0.85, 0.92, 1.0)))
        t.parent = pl; t.location = (-size[0] / 2 + 0.012, size[1] / 2 - 0.012 - sz - j * sz * 1.45, 0.004)
        if line_on and line_on[j] is not None:
            keys(t, {("scale", k): pop(line_on[j]) for k in range(3)})
    return pl
card("cmd", (0.40, 0.055), (0.0, -0.21, -1.0), [("Image the harbor at first light.", 0.024)],
     *ev["card1"])
card("orca", (0.25, 0.155), (0.27, 0.06, -1.0),
     [("ORCA ONBOARD", 0.026), ("Intent received", 0.020), ("Planning", 0.020), ("Guardrails cleared", 0.020)],
     *ev["card2"], line_on=[None, ev["st_intent"], ev["st_plan"], ev["st_guard"]])
card("exec", (0.20, 0.05), (0.30, -0.20, -1.0), [("Status: Executing", 0.022)], *ev["card3"])

# ============================================================== shading =====
# object colour = material colour, so the viewport and motion_render agree
for o in bpy.data.objects:
    if o.name.startswith(("SET_", "HUD_")) and o.material_slots and o.material_slots[0].material:
        o.color = tuple(o.material_slots[0].material.diffuse_color)
# light, not objects: the imaging cone and the zone fill are see-through
bpy.data.objects["SET_img_cone"].color[3] = 0.22
bpy.data.objects["SET_hex_fill"].color[3] = 0.35
ds = sc.display.shading
ds.light, ds.color_type = 'STUDIO', 'OBJECT'
try: ds.background_type = 'WORLD'
except Exception: pass
print(PV.viewport_ready(clip=(0.05, 1200.0)))
for w in bpy.context.window_manager.windows:
    for a in w.screen.areas:
        if a.type != 'VIEW_3D': continue
        sh = a.spaces.active.shading
        sh.light, sh.color_type, sh.background_type = 'STUDIO', 'OBJECT', 'WORLD'
        a.spaces.active.show_gizmo = True
        rg = next((r for r in a.regions if r.type == 'WINDOW'), None)
        try:
            with bpy.context.temp_override(window=w, screen=w.screen, area=a, region=rg):
                bpy.ops.view3d.view_center_camera()
        except Exception as e:
            print("frame camera bounds skipped:", e)
'''

out = ('"""orca_onboard -- blocking build. Run in Blender: Scripting tab -> Open this\n'
       'file -> Run Script. Rebuilds the whole pass each time; touches nothing else.\n'
       'Generated by make_build.py -- edit orca_onboard.py and re-solve, not this file."""\n'
       "CORE = %r\nBAKE = %r\nSCENE = %r\n" % (core, bake, scene)) + BUILD
open(os.path.join(H, "build_orca_onboard.py"), "w").write(out)
open(os.path.join(os.path.dirname(H), "live.py"), "w").write(out)
print("build ->", os.path.join(H, "build_orca_onboard.py"), "%.0f KB" % (len(out) / 1024))
