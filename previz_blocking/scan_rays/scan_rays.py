"""scan_rays -- six searching light rays from one hub; the camera orbits in,
closes on ray A, then ray B, then rides out along ray C.

    python3 scan_rays.py          -> writes rays.json (ray angles per frame)
    python3 solve_shot.py scan_rays.py  -> solves + gates the camera, bake.json

The solver's "subject" is the camera's ATTENTION target: the hub, then a chunk
of ray A, ray B, then a point running out along ray C. It is hidden in the build.
"""
import math, json, os

FPS, SECONDS = 24, 15.0
NF = int(round(FPS * SECONDS))
HUB = (0.0, 0.0, 1.2)
RAY_LEN = 150.0

def sm(x):
    x = max(0.0, min(1.0, x)); return x * x * x * (x * (6 * x - 15) + 10)
def win(t, a, b, c, d):            # 0 -> 1 over a..b, hold, 1 -> 0 over c..d
    return sm((t - a) / (b - a)) * (1.0 - sm((t - c) / (d - c)))

# base azimuth (deg), colour, and the chaos phases of each ray
RAYS = [
    dict(name="A", az=-30, color="cyan",   w=(0.71, 1.13, 0.53, 0.97), p=(0.3, 2.1, 1.0, 4.0)),
    dict(name="B", az= 30, color="green",  w=(0.83, 0.59, 1.07, 0.61), p=(1.7, 0.4, 2.6, 0.9)),
    dict(name="C", az= 90, color="red",    w=(0.64, 1.21, 0.77, 0.49), p=(2.9, 1.3, 0.2, 3.3)),
    dict(name="D", az=150, color="yellow", w=(0.92, 0.67, 0.58, 1.17), p=(0.8, 3.7, 1.9, 2.2)),
    dict(name="E", az=210, color="yellow", w=(0.57, 1.03, 0.89, 0.73), p=(3.4, 0.6, 2.8, 1.4)),
    dict(name="F", az=270, color="yellow", w=(1.09, 0.79, 0.66, 0.84), p=(2.2, 2.9, 3.9, 0.1)),
]
AZ_AMP, EL_MID, EL_AMP = math.radians(38), math.radians(9), math.radians(13)

# when each ray is the one the camera is on -> its chaos calms (it "lingers")
FEATURE = {"A": (2.0, 4.2, 7.8, 9.8), "B": (5.2, 7.4, 10.4, 12.0)}
CROSS = {"A": 21.0, "B": -21.0}
C_SETTLE = (8.5, 11.0)             # ray C stops searching and holds a heading
C_HOLD_AZ, C_HOLD_EL = math.radians(96), math.radians(5)

def ray_angles(i, t):
    r = RAYS[i]; w, p = r["w"], r["p"]
    k = 1.0
    if r["name"] in FEATURE: k -= 0.65 * win(t, *FEATURE[r["name"]])
    az = math.radians(r["az"]) + k * AZ_AMP * (0.6 * math.sin(w[0] * t + p[0]) + 0.4 * math.sin(w[1] * t + p[1]))
    el = EL_MID + k * EL_AMP * (0.55 * math.sin(w[2] * t + p[2]) + 0.45 * math.sin(w[3] * t + p[3]))
    # the hand-off beat: A and B swing toward each other and nearly cross, so the
    # camera switches allegiance where they meet instead of crossing 60 deg of orbit
    if r["name"] in CROSS: az += math.radians(CROSS[r["name"]]) * win(t, 4.8, 7.2, 8.4, 10.6)
    if r["name"] == "C":
        s = sm((t - C_SETTLE[0]) / (C_SETTLE[1] - C_SETTLE[0]))
        hold_az = C_HOLD_AZ + math.radians(3) * math.sin(0.4 * t)   # slow living drift
        az, el = (1 - s) * az + s * hold_az, (1 - s) * el + s * C_HOLD_EL
    return az, el

def ray_dir(i, t):
    az, el = ray_angles(i, t)
    return (math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))

def on_ray(i, t, r):
    d = ray_dir(i, t); return tuple(HUB[k] + d[k] * r for k in range(3))

# ------------------------------------------------ camera, in a ray frame ----
# Each beat places the camera in the FEATURED ray's own horizontal frame:
#   cam = HUB + u*along(az) + v*side(az) + z*h      (side = az + 90 deg)
# v < 0 keeps the camera on the clockwise side of every ray, so the orbit only
# ever advances one way round the hub: open (-130) -> A (~-95) -> B (~-35),
# then it slides in beside the hub and rides out along C.
IA, IB, IC = 0, 1, 2
def lerp(a, b, u): return a + (b - a) * u

def blend_w(t):
    """weights of (hub, A, B, C) as the camera's subject"""
    a = sm((t - 2.0) / 3.4); b = sm((t - 5.6) / 4.0); c = sm((t - 9.4) / 3.0)
    return (1 - a, a * (1 - b), b * (1 - c), c)

# ride along C: ease UP to a cruise and keep going -- never lands, the beam
# keeps pulling the camera out into the distance
RIDE_T0, RIDE_RAMP, RIDE_V, RIDE_S0 = 10.2, 2.4, 1.5, -0.8
_RS = [0.0]
for _k in range(1, NF * 4 + 8):
    _t = _k / (FPS * 4)
    _RS.append(_RS[-1] + RIDE_V * sm((_t - RIDE_T0) / RIDE_RAMP) / (FPS * 4))
def ride_s(t):
    return RIDE_S0 + _RS[min(int(round(t * FPS * 4)), len(_RS) - 1)]

def _frame(az, u, v, h):
    return [HUB[0] + u * math.cos(az) - v * math.sin(az),
            HUB[1] + u * math.sin(az) + v * math.cos(az), HUB[2] + h]

def cam_pos(t):
    wh, wa, wb, wc = blend_w(t)
    azA, _ = ray_angles(IA, t); azB, _ = ray_angles(IB, t); azC, elC = ray_angles(IC, t)
    opn = math.radians(-130 + 4.0 * t)                     # slow CCW creep on the open
    # "breath": the camera eases back out between one ray and the next, which
    # is what keeps the hand-off a pan instead of a whip
    br = 4.0 * wa * wb + 3.0 * wh * wa
    P = [_frame(opn, 3.9 - 0.12 * t, 0.0, 2.5),             # high, before the hub
         _frame(azA, 1.6, -3.3 - 1.6 * br, 1.7 + 0.6 * br),  # beside ray A, looking out
         _frame(azB, 1.8, -3.1 - 1.6 * br, 1.4 + 0.6 * br),  # beside ray B
         _frame(azC, ride_s(t), -1.1,                       # riding along C
                0.75 + max(ride_s(t), 0) * math.tan(elC))]
    return [sum(w * p[k] for w, p in zip((wh, wa, wb, wc), P)) for k in range(3)]

def attention(t):
    wh, wa, wb, wc = blend_w(t)
    pts = [HUB, on_ray(IA, t, 5.0), on_ray(IB, t, 4.8),
           on_ray(IC, t, max(ride_s(t), 0) + 6.0)]
    return [sum(w * q[k] for w, q in zip((wh, wa, wb, wc), pts)) for k in range(3)]

ATT = 1.0                          # attention box edge (m); pos is its BASE
def subj_wp(t):
    a = attention(t); return (t, a[0], a[1], a[2] - ATT / 2)

STEP = 0.25
TS = [round(k * STEP, 3) for k in range(int(SECONDS / STEP) + 1)]
def LENS(t):                       # wide open, push on the close-ins, wide ride
    wh, wa, wb, wc = blend_w(t)
    return wh * 24 + (wa + wb) * 38 + wc * lerp(34, 20, sm((t - 10.4) / 4.0))

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
    (0.0,  "high three-quarter front of the hub; six rays fan out and search the floor"),
    (3.0,  "camera swings left-to-right round the hub and closes in on ray A (cyan)"),
    (6.5,  "hands off to the neighbouring ray B (green), still orbiting"),
    (10.0, "ray C (red) stops searching and holds a heading; camera slips in beside it"),
    (11.5, "camera rides out along ray C, the beam stretching ahead into the distance"),
  ],
}

if __name__ == "__main__":
    out = {"fps": FPS, "frames": NF, "hub": HUB, "length": RAY_LEN,
           "rays": [{"name": r["name"], "color": r["color"],
                     "az": [round(ray_angles(i, f / FPS)[0], 5) for f in range(NF)],
                     "el": [round(ray_angles(i, f / FPS)[1], 5) for f in range(NF)]}
                    for i, r in enumerate(RAYS)]}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rays.json")
    json.dump(out, open(p, "w")); print("rays ->", p)
