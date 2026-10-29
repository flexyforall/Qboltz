"""star_converge -- a rebuild of the user's 7 s reference clip.

A locked-off camera. A bright source sits in the upper-right third of frame;
ten long, thin rays of light cross it and scan around it; a wide, soft cone of
light opens from it to the left; rings of particles orbit it slowly. The rays
fold into ONE line through the source, edge to edge; the right half fades, the
left half pulls back into the source like a comet's tail, and the source blooms
into a star.

    python3 star_converge.py            -> writes rays.json
    python3 solve_shot.py star_converge.py  -> bake.json
"""
import math, json, os, random

FPS, SECONDS = 24, 7.0
NF = int(round(FPS * SECONDS))
HUB = (0.0, 0.0, 0.0)
RAY_LEN = 60.0                         # well past every frame edge

def sm(x):
    x = max(0.0, min(1.0, x)); return x * x * x * (x * (6 * x - 15) + 10)
def lerp(a, b, u): return a + (b - a) * u

# ---------------------------------------------------------------- camera ----
# locked off, 12 m in front of the source, framed so the source sits at ~73%
# across and ~33% down, like the reference (35 mm, 16:9).
CAM = (0.0, -12.0, 0.0)
AIM = (-2.84, 0.0, -1.18)              # aim left-down of the source

# ------------------------------------------------------------------ rays ----
# a ray is a direction in the picture plane (theta, from screen-right, CCW)
# plus a small depth tilt (phi, + = away from camera).
def _dir(theta, phi):
    return (math.cos(phi) * math.cos(theta), math.sin(phi), math.cos(phi) * math.sin(theta))

THETA_F, PHI_F = math.radians(188), math.radians(-10)     # the final line, to the left...
THETA_R, PHI_R = THETA_F - math.pi, -PHI_F                # ...and its other half, to the right

N_RAYS = 10
RAYS = []
_rnd = random.Random(5)
for k in range(N_RAYS):
    th0 = math.radians(k * 36 + _rnd.uniform(-10, 10))
    side = "L" if math.cos(th0 - THETA_F) > 0 else "R"    # which half of the line it folds into
    RAYS.append(dict(name="R%02d" % k, th0=th0, ph0=math.radians(_rnd.uniform(-20, 20)), side=side,
                     color=("red" if k == 5 else ("yellow" if side == "L" else "cyan"))))

SCAN_END, MERGE_T0, MERGE_T1 = 2.8, 2.6, 4.4
R_FADE = (4.8, 5.3)                    # right half of the line retracts into the source
L_PULL = (5.0, 5.9)                    # left half pulls back to a comet tail...
TAIL0, TAIL1 = 2.5, 1.2                # ...then the tail shrinks further
CORE = (5.4, 6.2)                      # the source blooms into a star

def _scan_keys(i):
    rnd = random.Random(200 + i); r = RAYS[i]
    th, ph = r["th0"], r["ph0"]
    t = -rnd.uniform(0.0, 0.8)
    keys = [(t, th, ph)]
    while t < SECONDS + 2:
        dwell, sweep = rnd.uniform(0.2, 0.4), rnd.uniform(1.2, 1.9)
        keys.append((t + dwell, th, ph))
        th_n = th + math.radians(rnd.uniform(18, 40)) * rnd.choice((-1, 1))
        ph_n = max(-0.4, min(0.4, ph + math.radians(rnd.uniform(-12, 12))))
        t += dwell + sweep
        keys.append((t, th_n, ph_n)); th, ph = th_n, ph_n
    return keys
_SCAN = [_scan_keys(i) for i in range(N_RAYS)]

def _scan(i, t):
    K = _SCAN[i]
    for a, b in zip(K, K[1:]):
        if a[0] <= t <= b[0]:
            u = sm((t - a[0]) / max(b[0] - a[0], 1e-6))
            return a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u
    return K[-1][1], K[-1][2]

def ray_angles(i, t):
    r = RAYS[i]; th, ph = _scan(i, t)
    tf, pf = (THETA_F, PHI_F) if r["side"] == "L" else (THETA_R, PHI_R)
    m = sm((t - MERGE_T0) / (MERGE_T1 - MERGE_T0))
    d = (tf - th + math.pi) % (2 * math.pi) - math.pi
    return th + m * d, ph + m * (pf - ph)

def ray_dir(i, t): return _dir(*ray_angles(i, t))

def ray_len(i, t):
    if RAYS[i]["side"] == "R":
        return lerp(RAY_LEN, 0.01, sm((t - R_FADE[0]) / (R_FADE[1] - R_FADE[0])))
    L = lerp(RAY_LEN, TAIL0, sm((t - L_PULL[0]) / (L_PULL[1] - L_PULL[0])))
    return lerp(L, TAIL1, sm((t - L_PULL[1]) / (SECONDS - L_PULL[1])))

def core_r(t):                          # the star's glow marker
    return 0.12 + 0.45 * sm((t - CORE[0]) / (CORE[1] - CORE[0])) + 0.05 * sm((t - 6.2) / 0.4) * math.sin(9 * t)

# the wide soft cone of light opening to the left, along the final line
WIDE = dict(theta=THETA_F, phi=PHI_F, length=40.0, half=math.radians(22))
def wide_alpha(t): return lerp(0.30, 0.12, sm((t - 5.0) / 1.5))

# ------------------------------------------------------------- particles ----
# dotted rings orbiting the source on tilted planes, turning slowly
RING_AXIS = (0.25, -0.35, 1.0)
RINGS = [(3.5, 140), (6.0, 200), (9.0, 260), (12.5, 300), (17.0, 340)]
MOTE_LIT_R = 0.6

def _unit(v):
    L = math.sqrt(sum(x * x for x in v)); return [x / L for x in v]
def rot(p, axis, a):                   # Rodrigues
    k = _unit(axis); c, s_ = math.cos(a), math.sin(a)
    kxp = [k[1]*p[2]-k[2]*p[1], k[2]*p[0]-k[0]*p[2], k[0]*p[1]-k[1]*p[0]]
    kp = sum(k[j]*p[j] for j in range(3))
    return [p[j]*c + kxp[j]*s_ + k[j]*kp*(1-c) for j in range(3)]

def mote_pos(m, t):
    return [HUB[j] + v for j, v in enumerate(rot(m["p0"], m["axis"], m["w"] * t))]

def motes():
    import numpy as np
    rnd = random.Random(9)
    T = np.arange(NF) / FPS
    RD = np.array([[ray_dir(i, t) for t in T] for i in range(N_RAYS)])
    RL = np.array([[ray_len(i, t) for t in T] for i in range(N_RAYS)])
    n = _unit(RING_AXIS)
    a = _unit([n[1], -n[0], 0.0]); b = [n[1]*a[2]-n[2]*a[1], n[2]*a[0]-n[0]*a[2], n[0]*a[1]-n[1]*a[0]]
    out = []
    for R, cnt in RINGS:
        w = rnd.uniform(0.05, 0.09) * rnd.choice((-1, 1))
        for _ in range(cnt):
            q = rnd.uniform(0, 2 * math.pi); rr = R + rnd.gauss(0, 0.15)
            z = rnd.gauss(0, 0.12)
            p0 = [rr * (math.cos(q) * a[j] + math.sin(q) * b[j]) + z * n[j] for j in range(3)]
            m = {"p0": [round(x, 3) for x in p0], "axis": [round(x, 4) for x in n], "w": round(w, 4)}
            P = np.array([mote_pos(m, t) for t in T])
            U = np.einsum("rfk,fk->rf", RD, P)
            D = np.linalg.norm(P[None] - U[..., None] * RD, axis=2)
            D[(U < 0) | (U > RL)] = 99.0
            x = np.clip(D.min(axis=0) / MOTE_LIT_R, 0, 1)
            g = 1.0 - x * x * x * (x * (6 * x - 15) + 10)
            m["r"] = round(rnd.uniform(0.022, 0.032), 4)
            m["glow"] = [round(float(v), 3) for v in g]
            out.append(m)
    return out

# ----------------------------------------------------------------- SHOT ----
ATT = 0.4
SHOT = {
  "name": "star_converge", "fps": FPS, "seconds": SECONDS,
  "rig": "tripod",
  "subject": {"mode": "waypoints", "size": [ATT, ATT, ATT],
              "waypoints": [(0.0, 0.0, 0.0, -ATT / 2), (SECONDS, 0.0, 0.0, -ATT / 2)]},
  "shots": [{"t0": 0.0, "t1": SECONDS, "name": "locked", "camera": {
      "fit": 0.98, "aim_distance": 12.0, "subject_smooth": 0, "lens_smooth": 0,
      "waypoints": [{"t": 0.0, "pos": list(CAM), "lens": 35, "aim": list(AIM)},
                    {"t": SECONDS, "pos": list(CAM), "lens": 35, "aim": list(AIM)}]}}],
  "beats": [
    (0.0, "bright source upper-right; ten long thin rays cross it and scan; a wide soft cone opens left; rings of particles orbit"),
    (2.6, "the rays fold together"),
    (4.4, "one line through the source, edge to edge"),
    (4.8, "the right half fades back into the source"),
    (5.0, "the left half pulls back into the source like a comet's tail"),
    (5.4, "the source blooms into a star; the tail thins out"),
  ],
}

if __name__ == "__main__":
    out = {"fps": FPS, "frames": NF, "hub": HUB, "length": RAY_LEN, "mote_motion": "rings",
           "rays": [], "motes": motes(),
           "core": {"r": [round(core_r(f / FPS), 3) for f in range(NF)]}}
    for i, r in enumerate(RAYS):
        ang = [ray_angles(i, f / FPS) for f in range(NF)]
        # store as the build expects: az/el of the direction vector
        az, el = [], []
        for th, ph in ang:
            d = _dir(th, ph); az.append(round(math.atan2(d[1], d[0]), 5)); el.append(round(math.asin(max(-1, min(1, d[2]))), 5))
        for k in range(1, NF):                       # unwrap az so the rotation never flips
            while az[k] - az[k-1] > math.pi: az[k] -= 2 * math.pi
            while az[k] - az[k-1] < -math.pi: az[k] += 2 * math.pi
        out["rays"].append({"name": r["name"], "color": r["color"], "width": 0.06, "length": RAY_LEN,
                            "az": az, "el": el, "len": [round(ray_len(i, f / FPS), 3) for f in range(NF)]})
    d = _dir(WIDE["theta"], WIDE["phi"])
    wa = round(math.atan2(d[1], d[0]), 5); we = round(math.asin(d[2]), 5)
    out["rays"].append({"name": "WIDE", "color": "blue", "length": WIDE["length"],
                        "cone": round(WIDE["length"] * math.tan(WIDE["half"]), 3),
                        "alpha": [round(wide_alpha(f / FPS), 3) for f in range(NF)],
                        "az": [wa] * NF, "el": [we] * NF})
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rays.json")
    json.dump(out, open(p, "w")); print("rays ->", p)
