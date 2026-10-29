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
SCAN_LEN = 20.0                       # rays reach this far while searching
# rays are DIFFUSE CONES of scattered light, like the reference: narrow at the
# source, opening ~6 deg each side. The cone's far width is fixed, so when the
# hero stretches 20 -> 150 m it narrows on its own into a focused beam.
CONE_HALF = math.radians(6)
CONE_END_HW = SCAN_LEN * math.tan(CONE_HALF)

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
    # six more, filling the gaps above and below so light leaves the source in
    # every direction, as in the reference
    dict(name="G", az=  0, color="blue",   w=(0.77, 1.02, 0.61, 0.93), p=(0.9, 2.7, 4.1, 1.6),  el=-40),
    dict(name="H", az= 60, color="purple", w=(0.95, 0.71, 0.84, 0.58), p=(3.3, 0.2, 2.4, 5.1),  el=45),
    dict(name="I", az=120, color="yellow", w=(0.62, 1.15, 0.72, 1.01), p=(5.6, 4.4, 0.7, 2.9),  el=-10),
    dict(name="J", az=180, color="blue",   w=(1.04, 0.66, 0.97, 0.79), p=(2.1, 1.1, 3.6, 4.4),  el=35),
    dict(name="K", az=240, color="purple", w=(0.69, 0.88, 1.12, 0.67), p=(4.7, 5.9, 1.3, 0.3),  el=20),
    dict(name="L", az=300, color="yellow", w=(0.86, 1.08, 0.55, 0.91), p=(1.4, 3.2, 5.5, 3.8),  el=-35),
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

# SCANNING motion, like a searchlight: each ray eases out of a hold, sweeps to a
# new spot, eases to a stop, lingers briefly (still breathing a little), then
# sweeps on. Every ray keeps its own rhythm, so they never move in lock-step.
def _scan_keys(i):
    rnd = random.Random(100 + i); r = RAYS[i]
    az, el = math.radians(r["az"]), math.radians(r["el"])
    t = -rnd.uniform(0.0, 1.2)                     # stagger the rhythms
    keys = [(t, az, el)]
    while t < SECONDS + 3:
        dwell, sweep = rnd.uniform(0.25, 0.55), rnd.uniform(1.6, 2.6)
        keys.append((t + dwell, az, el))           # linger
        daz = math.radians(rnd.uniform(30, 60)) * rnd.choice((-1, 1))
        az_n = math.radians(r["az"]) + max(-1.1, min(1.1, az + daz - math.radians(r["az"])))
        el_n = math.radians(r["el"]) + math.radians(rnd.uniform(-22, 22))
        t += dwell + sweep
        keys.append((t, az_n, el_n))               # eased sweep to the next spot
        az, el = az_n, el_n
    return keys
_SCAN = [_scan_keys(i) for i in range(len(RAYS))]

def scan_angles(i, t):
    K = _SCAN[i]
    for a, b in zip(K, K[1:]):
        if a[0] <= t <= b[0]:
            u = sm((t - a[0]) / max(b[0] - a[0], 1e-6))
            az, el = a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u
            break
    else:
        az, el = K[-1][1], K[-1][2]
    # a breath on top, so a lingering ray is never dead still
    w = RAYS[i]["w"]; p = RAYS[i]["p"]
    return (az + math.radians(2.0) * math.sin(w[0] * 2.2 * t + p[0]),
            el + math.radians(1.5) * math.sin(w[2] * 2.2 * t + p[2]))

def ray_angles(i, t):
    r = RAYS[i]
    az, el = scan_angles(i, t)
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
# One continuous move:
#  1) ARC 0 -> 6.1 s: 26 m out, always facing the source, arcing toward the
#     future beam's axis.
#  2) SPIRAL IN 6.1 -> 7.9 s: the moment the rays start to fold, the camera keeps
#     arcing AND dives in. The spiral lands on the beam's axis right at the source
#     at 7.9 s -- the same frame the last ray folds in. One ray, and we are on it.
#  3) RIDE 7.9 s -> end: out along the beam, braking to a glide ~1 m above it.
T_DIVE, T_ON = MERGE_T0, MERGE_T1                   # the fold IS the dive
ORB_R, ORB_RAMP = 26.0, 2.2
ORB_H0, ORB_H1 = 5.0, 2.0
_ORB = _integrate(lambda t: sm((t + 0.8) / ORB_RAMP) * (1 - sm((t - (T_ON - ORB_RAMP)) / ORB_RAMP)))
def orbit_angle(t): return ORB_A0 + ORB_SWEEP * _ORB(min(t, T_ON)) / _ORB(T_ON)

V_ON = 14.0                                         # speed as we cross the source
def dive_r(t):
    """distance from the source during the spiral: cubic Hermite, leaves the arc
    at rest radially and reaches the source at V_ON."""
    if t <= T_DIVE: return ORB_R
    T = T_ON - T_DIVE; u = min((t - T_DIVE) / T, 1.0)
    return ORB_R * (2*u**3 - 3*u**2 + 1) - V_ON * T * (u**3 - u**2)

_RIDE = _integrate(lambda t: (3.0 + (V_ON - 3.0) * (1 - sm((t - T_ON) / 1.8))) if t >= T_ON else 0.0)
def ride_s(t): return _RIDE(t)

def cam_pos(t):
    az_b, el = c_hold(t)
    if t < T_ON:
        a = orbit_angle(t); r = dive_r(t)
        u = 0.0 if t <= T_DIVE else (t - T_DIVE) / (T_ON - T_DIVE)
        h = lerp(lerp(ORB_H0, ORB_H1, sm(t / T_DIVE)), 0.45, sm(u))   # drop to skim the source
        return [HUB[0] + r * math.cos(a), HUB[1] + r * math.sin(a), HUB[2] + h]
    s = ride_s(t)
    h = 0.45 + 0.55 * sm(s / 3.0) + s * math.tan(el)              # settle ~1 m above the beam
    return [HUB[0] + s * math.cos(az_b), HUB[1] + s * math.sin(az_b), HUB[2] + h]

def attention(t):
    # the source while we arc; then a point out along the beam, 8 m ahead of us
    d = c_hold_dir(t); r = (ride_s(t) if t >= T_ON else 0.0) + 8.0
    p = [HUB[k] + d[k] * r for k in range(3)]
    w = sm((t - T_DIVE) / (T_ON - T_DIVE))
    return [lerp(HUB[k], p[k], w) for k in range(3)]

ATT = 1.0
def subj_wp(t):
    a = attention(t); return (t, a[0], a[1], a[2] - ATT / 2)

STEP = 0.25
TS = [round(k * STEP, 3) for k in range(int(SECONDS / STEP) + 1)]
def LENS(t):          # distant source framed with its rays -> wide dive -> ride
    return lerp(30.0, lerp(18.0, 20.0, sm((t - 9.0) / 2.5)), sm((t - T_DIVE) / (T_ON - T_DIVE)))

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
        # inside a cone: allowed radius grows linearly from the source to the far end
        RAD = np.clip(U, 0, None) / RL * CONE_END_HW + 0.3
        x = np.clip((D / RAD).min(axis=0), 0, 1)
        g = 1.0 - x * x * x * (x * (6 * x - 15) + 10)
        m["r"] = round(rnd.uniform(0.03, 0.045), 4)
        m["glow"] = [round(float(z), 3) for z in g]
        out.append(m)
    return out

if __name__ == "__main__":
    out = {"fps": FPS, "frames": NF, "hub": HUB, "length": RAY_LEN, "mote_motion": "swirl",
           "rays": [{"name": r["name"], "color": r["color"],
                     # a cone of light: far half-width fixed, length animated
                     "cone": round(CONE_END_HW * (1.0 if r["name"] == "C" else 0.97), 3),
                     # once folded in, the other five vanish: only ONE cone remains
                     **({} if r["name"] == "C" else {"merged_at": int(round(MERGE_T1 * FPS)) - 2}),
                     "length": RAY_LEN,
                     "az": [round(ray_angles(i, f / FPS)[0], 5) for f in range(NF)],
                     "el": [round(ray_angles(i, f / FPS)[1], 5) for f in range(NF)],
                     "len": [round(ray_len(i, f / FPS), 3) for f in range(NF)]}
                    for i, r in enumerate(RAYS)],
           "motes": motes()}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rays.json")
    json.dump(out, open(p, "w")); print("rays ->", p)
