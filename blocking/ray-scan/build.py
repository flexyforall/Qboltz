"""Build the ray-scan blocking in Blender and save it, ready to press Space.

    blender -b -P build.py            # or any python with the bpy module
    SEEDANCE_BLOCKING_SKILL=/path/to/seedance-blocking  (if the skill lives elsewhere)

Needs bake.json from:  python3 <skill>/scripts/solve_shot.py ray_scan.py
Writes ray_scan.blend next to this file, in camera view, solid shading, frame 1.
"""
import bpy, os, sys, math
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.environ.get("SEEDANCE_BLOCKING_SKILL") or os.path.expanduser(
    "~/.claude/skills/synced/2e623fd7-ac22-46ba-b37c-39561800dd24_067e2674-8948-4b62-abc0-1439544d4e73/seedance-blocking")
sys.path.insert(0, HERE)
import rays as R

# step 4: push the core in (once per session)
mod = type(bpy)("PV"); mod.__dict__["__file__"] = SK + "/scripts/previz_core.py"
exec(open(SK + "/scripts/previz_core.py").read(), mod.__dict__)
bpy.app.driver_namespace["PV"] = mod
PV = mod

# step 5: the default build, plus the hub and the six rays
PV.wipe()
PV.reset(fps=R.FPS, seconds=R.SECONDS)
PV.checker(size=400.0)                       # wide: MAGENTA's tip runs ~200 m out
PV.sun()
PV.actor("HERO", size=(0.6, 0.6, 0.6), color="red")       # the attention proxy (hidden below)
PV.load_bake(os.path.join(HERE, "bake.json"), clip=(0.05, 450.0))

PV.slab("SET_hub", (0.3, 0.3, 0.3), R.HUB, "white", emit=8.0)
N = int(round(R.SECONDS * R.FPS))
for i, name in enumerate(R.NAMES):
    o = PV.cyl(f"SET_ray_{name}", 0.035, 1.0, (0, 0, 0), color=name, verts=10, emit=6.0)
    o.data.transform(Matrix.Translation((0, 0, 0.5)))      # base on the hub, grows along +Z
    o.location = R.HUB
    o.rotation_mode = 'QUATERNION'
    quats, lens, prev = [], [], None
    for f in range(N):
        t = f / R.FPS
        q = Vector((0, 0, 1)).rotation_difference(Vector(R.direction(i, t)))
        if prev is not None and q.dot(prev) < 0:
            q.negate()                                       # keep the sign continuous
        quats.append(q); prev = q
        lens.append(R.length(i, t))
    ch = {("rotation_quaternion", k): [q[k] for q in quats] for k in range(4)}
    ch[("scale", 2)] = lens
    PV.bake(o, ch, name=f"ACT_ray_{name}")

# the audit gates the proxy, so it runs before the proxy is hidden
report = PV.audit()
print("PV.audit:", report)
for o in (bpy.data.objects["HERO_block"], bpy.data.objects["RIG_HERO_root"]):
    o.hide_viewport = o.hide_render = True

# viewport_ready(), headless: set every 3D view in the saved file to camera view, clean
sc = bpy.context.scene
sc.sync_mode = 'FRAME_DROP'
sc.frame_set(sc.frame_start)
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            s = area.spaces.active
            s.region_3d.view_perspective = 'CAMERA'
            s.shading.type = 'SOLID'
            s.overlay.show_overlays = False
            s.show_gizmo = False
            s.clip_start, s.clip_end = 0.05, 450.0

out = os.path.join(HERE, "ray_scan.blend")
bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
print("saved", out, "| audit PASS" if report["PASS"] else "| AUDIT FAILED")
