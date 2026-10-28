"""scan_rays (v2, 13 s) -- six searching light rays from one hub. The camera flies
in and settles level with the hub, arcs round it to the right -- always facing it --
and ends opposite ray C. Every ray folds into C, the camera passes over the hub
and flies on above the one beam. v1 (21 s, half orbit): ../scan_rays_v1_21s/

    python3 scan_rays.py          -> writes rays.json (ray angles per frame)
    python3 solve_shot.py scan_rays.py  -> solves + gates the camera, bake.json

The solver's "subject" is the camera's ATTENTION target: the hub, then a point
running out along ray C. It is hidden in the build.
"""
import math, json, os

FPS, SECONDS = 24, 13.0
NF = int(round(FPS * SECONDS))
HUB = (0.0, 0.0, 1.2)
RAY_LEN = 150.0

def sm(x):
    x = max(0.0, min(1.0, x)); return x * x * x * (x * (6 * x - 15) + 10)
def win(t, a, b, c, d):            # 0 -> 1 over a..b, hold, 1 -> 0 over c..d
    return sm((t - a) / (b - a)) * (1.0 - sm((t - c) / (d - c)))

# base azimuth (deg), colour, and the chaos phases of each ray
RAYS = [
    # phases are SEARCHED, not hand-set: every ray keeps moving on screen (its
    # slowest half-second >= 12 deg/s against the orbiting camera) and never
    # comes within 0.65 m of the lens. A is pitched up 10 deg to clear the arc.
    dict(name="A", az=-30, color="cyan",   w=(0.71, 1.13, 0.53, 0.97), p=(1.98, 1.44, 1.82, 0.44), el_bias=10),
    dict(name="B", az= 30, color="green",  w=(0.83, 0.59, 1.07, 0.61), p=(4.12, 3.52, 1.78, 4.5)),
    dict(name="C", az=180, color="red",    w=(0.64, 1.21, 0.77, 0.49), p=(0.07, 6.23, 5.02, 1.3)),
    dict(name="D", az=150, color="yellow", w=(0.92, 0.67, 0.58, 1.17), p=(1.75, 3.44, 1.17, 5.64)),
    dict(name="E", az=250, color="yellow", w=(0.57, 1.03, 0.89, 0.73), p=(5.2, 4.82, 6.19, 0.63)),
    dict(name="F", az= 90, color="yellow", w=(1.09, 0.79, 0.66, 0.84), p=(3.88, 5.67, 0.45, 6.21)),
]
AZ_AMP, EL_MID, EL_AMP = math.radians(38), math.radians(9), math.radians(13)

IC = 2                             # ray C, the one everything ends on
C_SETTLE = (7.2, 9.6)            # ray C searches through the whole arc, then locks during the fold
# every other ray folds INTO ray C: same heading, same pitch, one beam. Each
# swings the short way round, which here is always away from the camera.
MERGE_T0, MERGE_T1 = 8.0, 10.25    # frame 192 -> 246 (same 2.25 s fold)
# once they are one beam, light runs out along it
PULSE_T0, PULSE_V0, PULSE_V1 = 10.4, 6.0, 40.0
C_HOLD_AZ, C_HOLD_EL = math.radians(180), math.radians(5)
SWEEP = 1.6                        # sweep-speed multiplier: rays never look parked against the orbit

def c_hold(t):
    """ray C's final heading (with its slow living drift). The camera's ride is
    built on THIS, not on C's live angle, so C can keep searching late without
    dragging the camera around."""
    return C_HOLD_AZ + math.radians(3) * math.sin(0.4 * t), C_HOLD_EL

def c_hold_dir(t):
    az, el = c_hold(t)
    return (math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))

def ray_angles(i, t):
    r = RAYS[i]; w, p = [x * SWEEP for x in r["w"]], r["p"]
    az = math.radians(r["az"]) + AZ_AMP * (0.6 * math.sin(w[0] * t + p[0]) + 0.4 * math.sin(w[1] * t + p[1]))
    el = EL_MID + math.radians(r.get("el_bias", 0)) + EL_AMP * (0.55 * math.sin(w[2] * t + p[2]) + 0.45 * math.sin(w[3] * t + p[3]))
    if r["name"] == "C":
        s = sm((t - C_SETTLE[0]) / (C_SETTLE[1] - C_SETTLE[0]))
        hold_az, hold_el = c_hold(t)
        az, el = (1 - s) * az + s * hold_az, (1 - s) * el + s * hold_el
    else:
        m = sm((t - MERGE_T0) / (MERGE_T1 - MERGE_T0))
        if m > 0.0:
            caz, cel = ray_angles(IC, t)
            d = (caz - az + math.pi) % (2 * math.pi) - math.pi
            az, el = az + m * d, el + m * (cel - el)
    return az, el

def ray_dir(i, t):
    az, el = ray_angles(i, t)
    return (math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))

def on_ray(i, t, r):
    d = ray_dir(i, t); return tuple(HUB[k] + d[k] * r for k in range(3))

def lerp(a, b, u): return a + (b - a) * u

def _integrate(vel):
    """cumulative integral of vel(t) on a 4x-oversampled frame grid"""
    out, dt = [0.0], 1.0 / (FPS * 4)
    for k in range(1, NF * 4 + 8):
        out.append(out[-1] + vel(k * dt) * dt)
    return lambda t: out[min(int(round(t * FPS * 4)), len(out) - 1)]

# ---------------------------------------------------------------- open ----
# fly in from high and far, settle level with the hub. Ease-OUT only, so the
# camera arrives already moving -- it never starts from a dead stop.
OPEN_T, OPEN_DIST = 5.6, 6.6          # seconds, metres of approach
OPEN_H0, OPEN_H1 = 3.6, 0.25          # height above the hub: start -> arrival
ORB_R = 3.6                           # orbit radius once arrived

# --------------------------------------------------------------- orbit ----
# a half circle to the camera's RIGHT (CCW from above), always facing the hub.
# Trapezoid angular speed: ease in, cruise, ease out -- the cruise is what keeps
# it a slow turn instead of a swing. It ends exactly opposite ray C's heading.
ORB_A0, ORB_SWEEP = math.radians(-110), math.radians(110)
ORB_T0, ORB_T1, ORB_RAMP = 1.4, 8.8, 2.4   # same ~22 deg/s cruise, less arc
def _orb_v(t):
    return sm((t - ORB_T0) / ORB_RAMP) * (1.0 - sm((t - (ORB_T1 - ORB_RAMP)) / ORB_RAMP))
_ORB = _integrate(_orb_v)
def orbit_angle(t): return ORB_A0 + ORB_SWEEP * _ORB(t) / _ORB(SECONDS)

# ---------------------------------------------------------------- ride ----
# from the far side of the hub (frame 306), drift slowly straight at it, lift
# and pass right OVER it while the rays fold into C, then fly on above the one
# beam. Slow approach speed, then ease up to a cruise -- never lands.
def _ride_v(t): return 1.3 * sm((t - 6.8) / 2.0) + 1.1 * sm((t - 10.0) / 2.2)
_RIDE = _integrate(_ride_v)
def ride_s(t): return -ORB_R + _RIDE(t)

def w_ride(t): return sm((t - 7.0) / 3.2)

def _frame(az, u, v, h):
    return [HUB[0] + u * math.cos(az) - v * math.sin(az),
            HUB[1] + u * math.sin(az) + v * math.cos(az), HUB[2] + h]

def cam_pos(t):
    wc = w_ride(t)
    ap = (1.0 - min(t / OPEN_T, 1.0)) ** 2
    orb = _frame(orbit_angle(t), ORB_R + OPEN_DIST * ap, 0.0, OPEN_H1 + (OPEN_H0 - OPEN_H1) * ap)
    azC, elC = c_hold(t)
    s = ride_s(t)
    h = (OPEN_H1 + 1.05 * sm((s + 3.0) / 2.6)          # lift to clear the hub top by ~1 m
         - 0.35 * sm((s - 0.6) / 3.0)                  # then settle ~1 m above the beam
         + max(s, 0) * math.tan(elC))                  # and climb with it
    ride = _frame(azC, s, 0.0, h)                       # dead on the beam's line
    return [lerp(orb[k], ride[k], wc) for k in range(3)]

def attention(t):
    wc = w_ride(t)
    d = c_hold_dir(t); r = max(ride_s(t), 0) + 6.0
    p = [HUB[k] + d[k] * r for k in range(3)]
    return [lerp(HUB[k], p[k], wc) for k in range(3)]

ATT = 1.0                          # attention box edge (m); pos is its BASE
def subj_wp(t):
    a = attention(t); return (t, a[0], a[1], a[2] - ATT / 2)

STEP = 0.25
TS = [round(k * STEP, 3) for k in range(int(SECONDS / STEP) + 1)]
def LENS(t):                       # wide on the fly-in, a touch tighter round the hub, wide ride
    return lerp(lerp(24, 28, sm((t - 1.5) / 3.5)), lerp(28, 19, sm((t - 9.2) / 2.8)), w_ride(t))

SHOT = {
  "name": "scan_rays", "fps": FPS, "seconds": SECONDS,
  "rig": "gimbal",
  "subject": {"mode": "waypoints", "size": [ATT, ATT, ATT],
              "waypoints": [subj_wp(t) for t in TS]},
  "shots": [{"t0": 0.0, "t1": SECONDS, "name": "scan", "camera": {
      "fit": 0.70, "aim_distance": 5.0, "subject_smooth": 6, "lens_smooth": 10,
      "waypoints": [{"t": t, "pos": cam_pos(t), "lens": LENS(t), "aim": [0, 0, ATT / 2]}
                    for t in TS]}}],
  "beats": [
    (0.0,  "high and far; flying in and down toward the hub as six rays search the floor"),
    (1.4,  "still descending, the camera starts a slow arc to the right, always facing the hub"),
    (5.0,  "ray C (red) stops searching and swings to point away behind the hub"),
    (8.0,  "arc ends opposite ray C; all rays start folding into it"),
    (10.25, "one single beam; camera passes slowly right over the hub"),
    (10.4, "a pulse of light runs out along the beam into the distance"),
    (11.0, "camera flies straight ahead just above the beam"),
  ],
}

_PULSE = _integrate(lambda t: (PULSE_V0 + (PULSE_V1 - PULSE_V0) * sm((t - PULSE_T0) / 2.0))
                    if t >= PULSE_T0 else 0.0)

# ---------------------------------------------------------------- motes ----
# deep space: no floor, a field of small round glowing motes drifting slowly.
# A mote LIGHTS UP while a beam passes through it -- that is the "scanning".
# They are also the only parallax the camera has now that the floor is gone.
import random
N_MOTES, MOTE_LIT_R, MOTE_CAM_CLEAR = 2400, 1.0, 0.9

def _ray_dist(p, i, t):
    d = ray_dir(i, t); v = [p[k] - HUB[k] for k in range(3)]
    u = sum(v[k] * d[k] for k in range(3))
    if u < 0.0 or u > RAY_LEN: return 99.0
    return math.dist(p, [HUB[k] + d[k] * u for k in range(3)])

def motes():
    rnd = random.Random(7)
    cams = [cam_pos(f / FPS) for f in range(0, NF, 2)]
    out = []
    while len(out) < N_MOTES:
        r = 1.2 + 30.0 * rnd.random() ** 1.6            # denser near the source
        a = rnd.uniform(0, 2 * math.pi)
        p0 = [HUB[0] + r * math.cos(a), HUB[1] + r * math.sin(a),
              HUB[2] + rnd.uniform(-7.0, 9.0) * min(1.0, 0.35 + r / 12.0)]
        sp = rnd.uniform(0.03, 0.14)                      # slow drift, m/s
        th, ph = rnd.uniform(0, 2 * math.pi), rnd.uniform(-0.5, 0.5)
        v = [sp * math.cos(ph) * math.cos(th), sp * math.cos(ph) * math.sin(th), sp * math.sin(ph)]
        pos = lambda f: [p0[k] + v[k] * f / FPS for k in range(3)]
        # never let a mote cross the lens
        if any(math.dist(pos(2 * j), c) < MOTE_CAM_CLEAR for j, c in enumerate(cams)): continue
        glow = []
        for f in range(NF):
            dmin = min(_ray_dist(pos(f), i, f / FPS) for i in range(len(RAYS)))
            glow.append(round(1.0 - sm(dmin / MOTE_LIT_R), 3))
        out.append({"p0": [round(x, 3) for x in p0], "v": [round(x, 4) for x in v],
                    "r": round(rnd.uniform(0.010, 0.025), 4), "glow": glow})
    return out

if __name__ == "__main__":
    pulse_d = [round(_PULSE(f / FPS), 3) if f / FPS >= PULSE_T0 and _PULSE(f / FPS) < RAY_LEN
               else -1.0 for f in range(NF)]
    out = {"fps": FPS, "frames": NF, "hub": HUB, "length": RAY_LEN,
           "pulse": {"ray": "C", "d": pulse_d},
           "motes": motes(),
           "rays": [{"name": r["name"], "color": r["color"],
                     # C is fatter and longer so the folded rays hide INSIDE it
                     # instead of z-fighting on shared faces
                     "width": 0.12 if r["name"] == "C" else 0.09,
                     "length": RAY_LEN if r["name"] == "C" else RAY_LEN - 0.6,
                     "az": [round(ray_angles(i, f / FPS)[0], 5) for f in range(NF)],
                     "el": [round(ray_angles(i, f / FPS)[1], 5) for f in range(NF)]}
                    for i, r in enumerate(RAYS)]}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rays.json")
    json.dump(out, open(p, "w")); print("rays ->", p)
