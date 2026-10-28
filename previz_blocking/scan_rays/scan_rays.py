"""scan_rays -- six searching light rays from one hub. The camera flies in and
settles level with the hub, orbits it in a slow half circle -- always facing it --
and ends opposite ray C, then glides past the hub and rides out along C.

    python3 scan_rays.py          -> writes rays.json (ray angles per frame)
    python3 solve_shot.py scan_rays.py  -> solves + gates the camera, bake.json

The solver's "subject" is the camera's ATTENTION target: the hub, then a point
running out along ray C. It is hidden in the build.
"""
import math, json, os

FPS, SECONDS = 24, 19.0
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
    dict(name="C", az=250, color="red",    w=(0.64, 1.21, 0.77, 0.49), p=(2.9, 1.3, 0.2, 3.3)),
    dict(name="D", az=150, color="yellow", w=(0.92, 0.67, 0.58, 1.17), p=(0.8, 3.7, 1.9, 2.2)),
    dict(name="E", az=190, color="yellow", w=(0.57, 1.03, 0.89, 0.73), p=(3.4, 0.6, 2.8, 1.4)),
    dict(name="F", az= 90, color="yellow", w=(1.09, 0.79, 0.66, 0.84), p=(2.2, 2.9, 3.9, 0.1)),
]
AZ_AMP, EL_MID, EL_AMP = math.radians(38), math.radians(9), math.radians(13)

C_SETTLE = (10.5, 13.0)            # ray C stops searching and holds a heading
C_HOLD_AZ, C_HOLD_EL = math.radians(250), math.radians(5)

def ray_angles(i, t):
    r = RAYS[i]; w, p = r["w"], r["p"]
    az = math.radians(r["az"]) + AZ_AMP * (0.6 * math.sin(w[0] * t + p[0]) + 0.4 * math.sin(w[1] * t + p[1]))
    el = EL_MID + EL_AMP * (0.55 * math.sin(w[2] * t + p[2]) + 0.45 * math.sin(w[3] * t + p[3]))
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

IC = 2
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
ORB_A0, ORB_SWEEP = math.radians(-110), math.radians(180)
ORB_T0, ORB_T1, ORB_RAMP = 3.0, 13.6, 2.4
def _orb_v(t):
    return sm((t - ORB_T0) / ORB_RAMP) * (1.0 - sm((t - (ORB_T1 - ORB_RAMP)) / ORB_RAMP))
_ORB = _integrate(_orb_v)
def orbit_angle(t): return ORB_A0 + ORB_SWEEP * _ORB(t) / _ORB(SECONDS)

# ---------------------------------------------------------------- ride ----
# from the far side of the hub, glide past it and out along C. Ease up to a
# cruise and keep going -- never lands, the beam pulls the camera on.
RIDE_T0, RIDE_RAMP, RIDE_V = 11.6, 2.8, 2.0
_RIDE = _integrate(lambda t: RIDE_V * sm((t - RIDE_T0) / RIDE_RAMP))
def ride_s(t): return -ORB_R + _RIDE(t)

def w_ride(t): return sm((t - 11.8) / 3.2)

def _frame(az, u, v, h):
    return [HUB[0] + u * math.cos(az) - v * math.sin(az),
            HUB[1] + u * math.sin(az) + v * math.cos(az), HUB[2] + h]

def cam_pos(t):
    wc = w_ride(t)
    ap = (1.0 - min(t / OPEN_T, 1.0)) ** 2
    orb = _frame(orbit_angle(t), ORB_R + OPEN_DIST * ap, 0.0, OPEN_H1 + (OPEN_H0 - OPEN_H1) * ap)
    azC, elC = ray_angles(IC, t)
    s = ride_s(t); side = sm((t - 12.2) / 2.4)
    ride = _frame(azC, s, -1.6 * side, OPEN_H1 + 0.7 * side + max(s, 0) * math.tan(elC))
    return [lerp(orb[k], ride[k], wc) for k in range(3)]

def attention(t):
    wc = w_ride(t)
    p = on_ray(IC, t, max(ride_s(t), 0) + 6.0)
    return [lerp(HUB[k], p[k], wc) for k in range(3)]

ATT = 1.0                          # attention box edge (m); pos is its BASE
def subj_wp(t):
    a = attention(t); return (t, a[0], a[1], a[2] - ATT / 2)

STEP = 0.25
TS = [round(k * STEP, 3) for k in range(int(SECONDS / STEP) + 1)]
def LENS(t):                       # wide on the fly-in, a touch tighter round the hub, wide ride
    return lerp(lerp(24, 28, sm((t - 3.0) / 4.0)), lerp(28, 20, sm((t - 14.0) / 4.0)), w_ride(t))

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
    (3.0,  "arrives level with the hub and starts a slow half-circle to the right, facing it"),
    (8.0,  "mid-orbit: the rays sweep past the lens, the hub stays centre frame"),
    (12.5, "orbit ends opposite ray C (red), which has stopped searching and points away"),
    (14.5, "camera glides past the hub and rides out along ray C into the distance"),
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
