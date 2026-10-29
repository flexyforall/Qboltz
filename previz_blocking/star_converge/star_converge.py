"""star_converge -- an EXACT rebuild of the user's 7 s reference clip.

Every number below was MEASURED from the reference frame by frame (24 fps,
170 frames): source position in frame, the angle of every line through the
source, when the last line forms, how fast each half retracts, the star's glow
radius, the wide cone's edge angle and fade. The picture is flat, like the
reference: every line lies in the plane facing the camera.

Screen angles are CCW from screen-right (0 = right, 90 = up), in degrees.
Lengths are metres in the source plane (12 m from the lens, 35 mm:
1 px of the 1334 px wide reference = 0.00925 m).

    python3 star_converge.py            -> writes rays.json
    python3 solve_shot.py star_converge.py  -> bake.json
"""
import math, json, os, random

FPS = 24
NF = 170
SECONDS = NF / FPS
HUB = (0.0, 0.0, 0.0)
FAR = 60.0                          # a "full" half-line, well past the frame edge

def sm(x):
    x = max(0.0, min(1.0, x)); return x * x * x * (x * (6 * x - 15) + 10)
def lerp(a, b, u): return a + (b - a) * u

def track(keys, f):
    """piecewise interpolation through measured (frame, value) keys, eased
    between keys so motion never kinks"""
    if f <= keys[0][0]: return keys[0][1]
    for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
        if f0 <= f <= f1:
            return v0 + (v1 - v0) * sm((f - f0) / (f1 - f0))
    return keys[-1][1]

def track_smooth(keys, f):
    """monotone cubic (PCHIP) through dense measured keys: passes every key
    without stopping at it and without overshoot"""
    if f <= keys[0][0]: return keys[0][1]
    if f >= keys[-1][0]: return keys[-1][1]
    xs = [k[0] for k in keys]; ys = [k[1] for k in keys]; n = len(keys)
    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
    m = [d[0]] + [0.0 if d[i - 1] * d[i] <= 0 else
                  2 / (1 / d[i - 1] + 1 / d[i]) for i in range(1, n - 1)] + [d[-1]]
    for i in range(n - 1):
        if xs[i] <= f <= xs[i + 1]:
            h = xs[i + 1] - xs[i]; t = (f - xs[i]) / h
            return (ys[i] * (2*t**3 - 3*t**2 + 1) + m[i] * h * (t**3 - 2*t**2 + t)
                    + ys[i + 1] * (-2*t**3 + 3*t**2) + m[i + 1] * h * (t**3 - t**2))

def track_lin(keys, f):
    if f <= keys[0][0]: return keys[0][1]
    for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
        if f0 <= f <= f1:
            return v0 + (v1 - v0) * (f - f0) / (f1 - f0)
    return keys[-1][1]

# ---------------------------------------------------------------- camera ----
# measured: source at x = 962/1334 (72.1%), y from 224 to 248 of 742 px over
# frames 0..130 -> a slow tilt. Camera 12 m in front, 35 mm, aim set so the
# source lands exactly there.
CAM = (0.0, -12.0, 0.0)
HALF_W = 12.0 * 18.0 / 35.0          # 6.171 m
HALF_H = 12.0 * 10.125 / 35.0        # 3.471 m
AIM_X = -((962 / 1334) - 0.5) * 2 * HALF_W
# source height in the frame, tracked per frame (px of 742): it holds near the
# top third, then sinks steadily from ~frame 50 and settles at 247 by ~126
SRC_Y = [(0, 214), (40, 219), (60, 224), (90, 233), (114, 245), (126, 247), (169, 247)]
def aim_z(f): return -(0.5 - track_smooth(SRC_Y, f) / 742) * 2 * HALF_H

# ----------------------------------------------------------------- lines ----
# each LINE passes through the source: two half-rays, at a and a+180.
# keys are (frame, angle of the half that ends on the LEFT/lower-left side).
LINES = [
    # L1: rotates CCW onto the final line
    dict(name="L1", color="red",
         keys=[(0, 138), (44, 148), (65, 157), (80, 168), (88, 171), (96, 173.5), (104, 175.5),
               (112, 178.5), (120, 181.5), (128, 183.5), (136, 186), (140, 187.5), (144, 189.5),
               (148, 190), (169, 190)],
         alpha=[(0, 1.0)]),
    # L2: its upper-right half sweeps clockwise 63 -> 10; lower-left 243 -> 190
    dict(name="L2", color="yellow",
         keys=[(0, 243), (24, 232), (48, 217), (72, 210.5), (80, 212), (88, 209), (96, 205),
               (104, 200), (112, 196.5), (116, 194), (120, 192.5), (124, 191.5), (128, 190.5),
               (136, 190), (144, 190), (169, 190)],
         alpha=[(0, 1.0), (146, 1.0), (152, 0.0)]),
    # L3: stays near 126/306 and fades out
    dict(name="L3", color="cyan",
         keys=[(0, 126), (33, 116), (50, 112), (95, 115), (112, 117), (169, 117)],
         alpha=[(0, 1.0), (100, 1.0), (122, 0.0)]),
    # L4: near-horizontal, drifts and joins the final line
    dict(name="L4", color="green",
         keys=[(0, 174), (17, 186), (27, 180), (41, 178), (60, 181), (84, 185), (100, 188), (118, 190), (169, 190)],
         alpha=[(0, 1.0), (88, 1.0), (96, 0.0)]),
    # L5: a short-lived line that sweeps 93 -> 45 early on
    dict(name="L5", color="purple",
         keys=[(0, 100), (12, 93), (37, 55), (52, 45), (169, 45)],
         alpha=[(0, 0.0), (10, 0.0), (16, 1.0), (40, 1.0), (56, 0.0)]),
]

# the final line's two halves (measured reach, metres from the source)
# measured as the VISIBLE reach (line vs background), so the faint far end counts
LEFT_LEN = [(0, FAR), (128, FAR), (130, 10.0), (132, 8.6), (136, 7.2), (140, 5.2), (148, 4.4),
            (152, 2.4), (156, 2.1), (160, 2.3), (169, 3.0)]
RIGHT_LEN = [(0, FAR), (128, FAR), (130, 4.0), (132, 3.3), (136, 1.8), (140, 0.9), (144, 0.45),
             (156, 0.4), (160, 0.35), (169, 0.8)]

# the star's glow (measured halo radius, m)
CORE_R = [(0, 0.25), (140, 0.25), (144, 0.32), (152, 0.42), (160, 0.52), (169, 0.52)]

# the wide soft cone: its sharp upper edge turns 170 -> 192 deg and it fades
WIDE_EDGE = [(0, 170), (40, 180), (80, 185), (120, 190), (169, 192)]
WIDE_HALF = 15.0
WIDE_ALPHA = [(0, 0.32), (120, 0.30), (150, 0.14), (169, 0.11)]

def line_angle(L, f): return track_smooth(L["keys"], f)

# --------------------------------------------------------------- particles --
# faint dotted elliptical rings round the source, turning slowly
RING_AXIS = (0.18, -0.55, 1.0)
RINGS = [(3.0, 110), (5.0, 160), (7.0, 210), (9.5, 260), (12.0, 300)]

def _unit(v):
    L = math.sqrt(sum(x * x for x in v)); return [x / L for x in v]

def motes():
    rnd = random.Random(9)
    n = _unit(RING_AXIS)
    a = _unit([n[1], -n[0], 0.0]); b = [n[1]*a[2]-n[2]*a[1], n[2]*a[0]-n[0]*a[2], n[0]*a[1]-n[1]*a[0]]
    out = []
    for R, cnt in RINGS:
        w = rnd.uniform(0.04, 0.07) * rnd.choice((-1, 1))
        for _ in range(cnt):
            q = rnd.uniform(0, 2 * math.pi); rr = R + rnd.gauss(0, 0.08)
            p0 = [rr * (math.cos(q) * a[j] + math.sin(q) * b[j]) + rnd.gauss(0, 0.05) * n[j] for j in range(3)]
            out.append({"p0": [round(x, 3) for x in p0], "axis": [round(x, 4) for x in n], "w": round(w, 4),
                        "r": round(rnd.uniform(0.012, 0.02), 4), "glow": [0.0] * NF})
    return out

# ----------------------------------------------------------------- SHOT ----
ATT = 0.4
SHOT = {
  "name": "star_converge", "fps": FPS, "seconds": SECONDS,
  "rig": "tripod",
  "subject": {"mode": "waypoints", "size": [ATT, ATT, ATT],
              "waypoints": [(0.0, 0.0, 0.0, -ATT / 2), (SECONDS, 0.0, 0.0, -ATT / 2)]},
  "shots": [{"t0": 0.0, "t1": SECONDS, "name": "locked", "camera": {
      "fit": 0.99, "aim_distance": 12.0, "subject_smooth": 0, "lens_smooth": 0,
      "waypoints": [{"t": f / FPS, "pos": list(CAM), "lens": 35, "aim": [AIM_X, 0.0, aim_z(f)]}
                    for f in range(0, NF + 1, 10)]}}],
  "beats": [
    (0.0, "source upper-right; five lines cross it and turn; a wide soft cone opens left; dotted rings orbit"),
    (0.5, "a short line sweeps through and fades (to 2.3 s)"),
    (3.8, "one line fades out (by 4.7 s)"),
    (5.2, "the lines meet: ONE line through the source, edge to edge"),
    (5.3, "the right half retracts into the source (to 6.0 s)"),
    (5.3, "the left half pulls back to a short comet tail (to 6.5 s)"),
    (5.8, "the source blooms into a star (to 6.7 s); the cone fades"),
  ],
}

if __name__ == "__main__":
    rays = []
    for L in LINES:
        for half, off in (("a", 0.0), ("b", 180.0)):
            th = [math.radians(line_angle(L, f) + off) for f in range(NF)]
            ray = {"name": L["name"] + half, "color": L["color"], "width": 0.06, "length": FAR,
                   # in-plane rotation: local +Z onto (cos th, 0, sin th)
                   "roty": [round(math.pi / 2 - t, 5) for t in th],
                   "alpha": [round(track_lin(L["alpha"], f), 3) for f in range(NF)]}
            if L["name"] == "L1":
                ray["len"] = [round(track_lin(LEFT_LEN if half == "a" else RIGHT_LEN, f), 3) for f in range(NF)]
                ray["taper"] = True              # the final line thins out to its tip, like the ref
                ray["width"] = 0.09
            rays.append(ray)
    th_w = [math.radians(track(WIDE_EDGE, f) + WIDE_HALF) for f in range(NF)]
    rays.append({"name": "WIDE", "color": "blue", "length": 40.0,
                 "cone": round(40.0 * math.tan(math.radians(WIDE_HALF)), 3),
                 "roty": [round(math.pi / 2 - t, 5) for t in th_w],
                 "alpha": [round(track_lin(WIDE_ALPHA, f), 3) for f in range(NF)]})
    out = {"fps": FPS, "frames": NF, "hub": HUB, "length": FAR, "mote_motion": "rings",
           "rays": rays, "motes": motes(),
           "core": {"r": [round(track(CORE_R, f), 3) for f in range(NF)]}}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rays.json")
    json.dump(out, open(p, "w")); print("rays ->", p)
