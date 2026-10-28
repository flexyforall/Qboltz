"""source_whoosh -- a light source in deep space, seen from afar. The camera arcs
round it at a distance while six rays sweep the space and light up the particles
around it; the rays fold into one that stretches far away; then the camera
whooshes in, through the source's glow, and ends flying just above the beam.

    python3 source_whoosh.py            -> writes rays.json (rays, lengths, particles)
    python3 solve_shot.py source_whoosh.py  -> solves + gates the camera, bake.json

The solver's "subject" is the camera's ATTENTION target: the source, then a
point out along the beam. It is hidden in the build.
"""
import math, json, os, random

FPS, SECONDS = 24, 13.0
NF = int(round(FPS * SECONDS))
HUB = (0.0, 0.0, 0.0)                 # the source, floating in space
RAY_LEN = 150.0                       # slab length; drawn shorter via scale
SCAN_LEN = 20.0                       # rays reach this far while searching (tapered: no hard end)

def sm(x):
    x = max(0.0, min(1.0, x)); return x * x * x * (x * (6 * x - 15) + 10)
def lerp(a, b, u): return a + (b - a) * u

# ------------------------------------------------------------------ rays ----
RAYS = [
    dict(name="A", az=-30, color="cyan",   w=(0.71, 1.13, 0.53, 0.97), p=(1.98, 1.44, 1.82, 0.44), el=25),
    dict(name="B", az= 30, color="green",  w=(0.83, 0.59, 1.07, 0.61), p=(4.12, 3.52, 1.78, 4.5),  el=-20),
    dict(name="C", az=150, color="red",    w=(0.64, 1.21, 0.77, 0.49), p=(0.07, 6.23, 5.02, 1.3),  el=5),
    dict(name="D", az= 90, color="yellow", w=(0.92, 0.67, 0.58, 1.17), p=(1.75, 3.44, 1.17, 5.64), el=30),
    dict(name="E", az=210, color="yellow", w=(0.57, 1.03, 0.89, 0.73), p=(5.2, 4.82, 6.19, 0.63),  el=-25),
    dict(name="F", az=270, color="yellow", w=(1.09, 0.79, 0.66, 0.84), p=(3.88, 5.67, 0.45, 6.21), el=10),
]
IC = 2
AZ_AMP, EL_AMP, SWEEP = math.radians(45), math.radians(22), 1.6

ORB_A0, ORB_SWEEP = math.radians(-170), math.radians(140)   # a big, readable arc
ORB_END = ORB_A0 + ORB_SWEEP                       # camera's final bearing from the source
# the beam points straight AWAY from where the arc ENDS: the arc keeps going until
# the camera sits dead on the beam's axis, beam centred. The fold happens while the
# camera is still off-axis, so the stretch reads before it lines up.
BEAM_OFF = 0.0
C_HOLD_AZ, C_HOLD_EL = ORB_END + math.pi + BEAM_OFF, math.radians(4)
C_SETTLE = (4.6, 6.6)
MERGE_T0, MERGE_T1 = 6.1, 7.9                      # the other five fold into C
GROW_T0, GROW_T1 = 5.9, 7.9                        # ...and the one beam stretches far away

def c_hold(t): return C_HOLD_AZ + math.radians(2) * math.sin(0.4 * t), C_HOLD_EL
def c_hold_dir(t):
    az, el = c_hold(t)
    return (math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))

def ray_angles(i, t):
    r = RAYS[i]; w = [x * SWEEP for x in r["w"]]; p = r["p"]
    az = math.radians(r["az"]) + AZ_AMP * (0.6 * math.sin(w[0] * t + p[0]) + 0.4 * math.sin(w[1] * t + p[1]))
    el = math.radians(r["el"]) + EL_AMP * (0.55 * math.sin(w[2] * t + p[2]) + 0.45 * math.sin(w[3] * t + p[3]))
    if r["name"] == "C":
        s = sm((t - C_SETTLE[0]) / (C_SETTLE[1] - C_SETTLE[0]))
        haz, hel = c_hold(t)
        d = (haz - az + math.pi) % (2 * math.pi) - math.pi
        az, el = az + s * d, (1 - s) * el + s * hel
    else:
        m = sm((t - MERGE_T0) / (MERGE_T1 - MERGE_T0))
        if m > 0.0:
            caz, cel = ray_angles(IC, t)
            d = (caz - az + math.pi) % (2 * math.pi) - math.pi
            az, el = az + m * d, el + m * (cel - el)
    return az, el

def ray_len(i, t):
    return lerp(SCAN_LEN, RAY_LEN - (0 if i == IC else 0.6), sm((t - GROW_T0) / (GROW_T1 - GROW_T0)))

def ray_dir(i, t):
    az, el = ray_angles(i, t)
    return (math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))

def _integrate(vel):
    out, dt = [0.0], 1.0 / (FPS * 4)
    for k in range(1, NF * 4 + 8):
        out.append(out[-1] + vel(k * dt) * dt)
    return lambda t: out[min(int(round(t * FPS * 4)), len(out) - 1)]

# ---------------------------------------------------------------- camera ----
# 1) far ARC: 26 m out, a slow 70 deg arc, always facing the source.
ORB_R, ORB_T0, ORB_T1, ORB_RAMP = 26.0, 0.0, 8.6, 2.2
ORB_H0, ORB_H1 = 5.0, 2.0
_ORB = _integrate(lambda t: sm((t - ORB_T0 + 0.8) / ORB_RAMP) * (1 - sm((t - (ORB_T1 - ORB_RAMP)) / ORB_RAMP)))
def orbit_angle(t): return ORB_A0 + ORB_SWEEP * _ORB(t) / _ORB(SECONDS)

# 2) WHOOSH: along the beam's line from the far side, through the source's glow,
#    then brake to a cruise just above the beam. s = distance past the source.
def _whoosh_v(t): return 16.0 * sm((t - 7.3) / 1.8) * (1.0 - 0.8 * sm((t - 9.8) / 1.4))
_WH = _integrate(_whoosh_v)
def whoosh_s(t): return -ORB_R + _WH(t)
def w_whoosh(t): return sm((t - 7.2) / 1.4)

def _bearing(az, dist, h):
    return [HUB[0] + dist * math.cos(az), HUB[1] + dist * math.sin(az), HUB[2] + h]

def cam_pos(t):
    orb = _bearing(orbit_angle(t), ORB_R, lerp(ORB_H0, ORB_H1, sm(t / 8.0)))
    s = whoosh_s(t); az, el = c_hold(t)
    # the path comes in along the arc's bearing and bends through the source onto
    # the beam's line, so the camera ends dead above the beam
    b = sm((s + 3.0) / 6.0); az_in = ORB_END + math.pi
    hx_ = s * ((1 - b) * math.cos(az_in) + b * math.cos(az))
    hy_ = s * ((1 - b) * math.sin(az_in) + b * math.sin(az))
    h = (lerp(ORB_H1, 0.45, sm((s + 26.0) / 24.0))           # sink to skim just over the source
         + 0.55 * sm(s / 3.0)                                 # then ride ~1 m above the beam
         + max(s, 0.0) * math.tan(el))
    wh = [HUB[0] + hx_, HUB[1] + hy_, HUB[2] + h]
    w = w_whoosh(t)
    return [lerp(orb[k], wh[k], w) for k in range(3)]

def attention(t):
    d = c_hold_dir(t); r = max(whoosh_s(t), 0.0) + 8.0
    p = [HUB[k] + d[k] * r for k in range(3)]
    w = w_whoosh(t)
    return [lerp(HUB[k], p[k], w) for k in range(3)]

ATT = 1.0
def subj_wp(t):
    a = attention(t); return (t, a[0], a[1], a[2] - ATT / 2)

STEP = 0.25
TS = [round(k * STEP, 3) for k in range(int(SECONDS / STEP) + 1)]
def LENS(t):          # distant source framed with its rays -> wide whoosh -> ride
    return lerp(30.0, lerp(18.0, 20.0, sm((t - 10.5) / 2.0)), sm((t - 7.8) / 1.6))

SHOT = {
  "name": "source_whoosh", "fps": FPS, "seconds": SECONDS,
  "rig": "fpv_drone",
  "subject": {"mode": "waypoints", "size": [ATT, ATT, ATT],
              "waypoints": [subj_wp(t) for t in TS]},
  "shots": [{"t0": 0.0, "t1": SECONDS, "name": "whoosh", "camera": {
      "fit": 0.6, "aim_distance": 6.0, "subject_smooth": 6, "lens_smooth": 10,
      "waypoints": [{"t": t, "pos": cam_pos(t), "lens": LENS(t), "aim": [0, 0, ATT / 2]}
                    for t in TS]}}],
  "beats": [
    (0.0,  "a light source far away, ~26 m; particles swirl around it; six rays sweep the space"),
    (0.0,  "the camera arcs round the source at a distance, 140 deg, always facing it"),
    (6.1,  "the rays fold into one beam as the arc carries us toward its axis"),
    (5.9,  "the beam stretches far into the distance while we are still off to its side"),
    (7.9,  "ONE beam at the exact moment the arc lands dead on its axis: beam centred, running straight away"),
    (7.8,  "the camera breaks into a whoosh toward the source, ~16 m/s"),
    (10.1, "through the source's glow, skimming just over it"),
    (10.5, "braking to a cruise, flying just above the beam into the distance"),
  ],
}

# ------------------------------------------------------------- particles ----
# a swirling cloud round the source: dense near it, thinning out to ~30 m.
# p(t) = Rz(w t) . p0  scaled outward by (1 + vr t / r0): slow swirl + slow
# outward drift. The Blender build evaluates the SAME formula.
N_MOTES, MOTE_LIT_R, MOTE_CAM_CLEAR = 2500, 1.2, 0.6

def mote_pos(m, t):
    x, y, z = m["p0"]; a = m["w"] * t
    c, s_ = math.cos(a), math.sin(a)
    k = 1.0 + m["vr"] * t / max(m["r0"], 1e-6)
    return [HUB[0] + k * (c * x - s_ * y), HUB[1] + k * (s_ * x + c * y), HUB[2] + k * z]

def motes():
    import numpy as np
    rnd = random.Random(11)
    cams = np.array([cam_pos(f / FPS) for f in range(NF)])
    T = np.arange(NF) / FPS
    hub = np.array(HUB)
    RD = np.array([[ray_dir(i, t) for t in T] for i in range(len(RAYS))])
    RL = np.array([[ray_len(i, t) for t in T] for i in range(len(RAYS))])
    out = []
    while len(out) < N_MOTES:
        r0 = 1.0 + 29.0 * rnd.random() ** 1.8
        u, v = rnd.uniform(-1, 1), rnd.uniform(0, 2 * math.pi)
        q = math.sqrt(1 - u * u)
        p0 = [r0 * q * math.cos(v), r0 * q * math.sin(v), r0 * u * 0.7]
        m = {"p0": [round(x, 3) for x in p0], "r0": round(r0, 3),
             "w": round(rnd.uniform(0.04, 0.10) * (1 if rnd.random() < 0.8 else -1), 4),
             "vr": round(rnd.uniform(0.05, 0.25), 3)}
        P = np.array([mote_pos(m, t) for t in T])
        if (np.linalg.norm(P - cams, axis=1) < MOTE_CAM_CLEAR).any(): continue
        V = P - hub
        U = np.einsum("rfk,fk->rf", RD, V)
        D = np.linalg.norm(V[None] - U[..., None] * RD, axis=2)
        D[(U < 0) | (U > RL)] = 99.0
        x = np.clip(D.min(axis=0) / MOTE_LIT_R, 0, 1)
        g = 1.0 - x * x * x * (x * (6 * x - 15) + 10)
        m["r"] = round(rnd.uniform(0.03, 0.045), 4)
        m["glow"] = [round(float(z), 3) for z in g]
        out.append(m)
    return out

if __name__ == "__main__":
    out = {"fps": FPS, "frames": NF, "hub": HUB, "length": RAY_LEN, "mote_motion": "swirl",
           "rays": [{"name": r["name"], "color": r["color"],
                     # TAPERED to a point so a ray fades out instead of ending in a
                     # cut face; all one width so the hero never reads as "stronger"
                     "taper": True,
                     "width": 0.10 if r["name"] == "C" else 0.09,
                     "length": RAY_LEN,
                     "az": [round(ray_angles(i, f / FPS)[0], 5) for f in range(NF)],
                     "el": [round(ray_angles(i, f / FPS)[1], 5) for f in range(NF)],
                     "len": [round(ray_len(i, f / FPS), 3) for f in range(NF)]}
                    for i, r in enumerate(RAYS)],
           "motes": motes()}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rays.json")
    json.dump(out, open(p, "w")); print("rays ->", p)
