"""dust_ref/make_rings -- dotted particle rings on black, waving up and down.

The background of the star_converge generation: loose dotted elliptical rings
round the light source (right of centre, upper third), each ring a string of
small dot clusters with gaps. Every dot stays a crisp round point (analytic
anti-aliased disc, constant size -- no blur, no stretching). A slow ripple runs
outward from the source and lifts the dots up and lets them down in turn, so
the rings rise and fall like a wave.

    python3 make_rings.py OUT.mp4 [seconds] [width] [height]
Needs numpy + ffmpeg.
"""
import math, subprocess, sys
import numpy as np

OUT = sys.argv[1]
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
W = int(sys.argv[3]) if len(sys.argv) > 3 else 1920
H = int(sys.argv[4]) if len(sys.argv) > 4 else 1080
FPS = 24
S = H / 1080.0                              # everything below is in 1080p pixels
rng = np.random.default_rng(5)

SRC = (0.725 * W, 0.37 * H)                  # the light source (rings centre on it)
TILT = math.radians(-14)                     # ellipses lean slightly
ASPECT = 0.82                                # vertical / horizontal semi-axis
RADII = [190, 330, 480, 650, 840, 1050, 1280, 1520]   # horizontal semi-axes, px
CLUMP_GAP = 15                               # px along the ring between dot clusters
DOT_R = (1.3, 2.3)                           # dot radius range, px
COLOR = np.array([0.80, 0.82, 0.86])         # light silver-grey, like the frame
# the wave: dots move ONLY up/down. A ripple runs outward from the source.
WAVE = dict(amp=17.0, wavelength=520.0, period=4.5)
WAVE2 = dict(amp=6.0, wavelength=300.0, period=7.0)   # a small second ripple, less mechanical

xs, ys, rs, bs = [], [], [], []
for R in RADII:
    R *= S
    # the ring wobbles a little (hand-made, not a perfect ellipse)
    wob = [(rng.uniform(0.02, 0.05), rng.integers(2, 6), rng.uniform(0, 6.3)) for _ in range(3)]
    circ = 2 * math.pi * R * (1 + ASPECT) / 2
    n = int(circ / (CLUMP_GAP * S))
    th = np.sort(rng.uniform(0, 2 * math.pi, n))
    # broken into dashed segments: drop clusters where a slow noise is low
    keep = (np.sin(th * rng.integers(3, 7) + rng.uniform(0, 6.3))
            + 0.6 * np.sin(th * rng.integers(9, 15) + rng.uniform(0, 6.3))) > -0.75
    th = th[keep]
    for t_ in th:
        k = 1 + sum(a * math.sin(m * t_ + p) for a, m, p in wob)
        ex, ey = R * k * math.cos(t_), ASPECT * R * k * math.sin(t_)
        cx = SRC[0] + ex * math.cos(TILT) - ey * math.sin(TILT)
        cy = SRC[1] + ex * math.sin(TILT) + ey * math.cos(TILT)
        for _ in range(rng.integers(1, 5)):              # a cluster of 1-4 dots
            xs.append(cx + rng.normal(0, 3.2 * S)); ys.append(cy + rng.normal(0, 3.2 * S))
            rs.append(rng.uniform(*DOT_R) * S); bs.append(rng.uniform(0.45, 1.0))
# a sparse veil of fainter, smaller specks between the rings
for _ in range(int(1400 * W * H / (1920 * 1080))):
    xs.append(rng.uniform(0, W)); ys.append(rng.uniform(0, H))
    rs.append(rng.uniform(0.8, 1.2) * S); bs.append(rng.uniform(0.15, 0.35))
X0, Y0, RAD, BR = map(np.array, (xs, ys, rs, bs))
m = (X0 > -40) & (X0 < W + 40) & (Y0 > -40) & (Y0 < H + 40)
X0, Y0, RAD, BR = X0[m], Y0[m], RAD[m], BR[m]
DIST = np.hypot(X0 - SRC[0], Y0 - SRC[1])
print("dots:", len(X0))

ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                       "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                       "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p",
                       "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
NF = int(round(SECONDS * FPS))
win = int(math.ceil(DOT_R[1] * S + 1.5))
for fi in range(NF):
    t = fi / FPS
    dy = WAVE["amp"] * S * np.sin(2 * math.pi * (DIST / (WAVE["wavelength"] * S) - t / WAVE["period"])) \
       + WAVE2["amp"] * S * np.sin(2 * math.pi * (X0 / (WAVE2["wavelength"] * S) + t / WAVE2["period"]))
    px, py = X0, Y0 + dy
    ix, iy = np.floor(px).astype(int), np.floor(py).astype(int)
    acc = np.zeros(H * W)
    for oy in range(-win, win + 1):
        for ox in range(-win, win + 1):
            Xp, Yp = ix + ox, iy + oy
            # exact disc coverage at this pixel: crisp edge, 1 px anti-aliasing
            d = np.hypot(Xp + 0.5 - px, Yp + 0.5 - py)
            c = np.clip(RAD + 0.5 - d, 0.0, 1.0) * BR
            ok = (c > 0) & (Xp >= 0) & (Xp < W) & (Yp >= 0) & (Yp < H)
            acc += np.bincount(Yp[ok] * W + Xp[ok], c[ok], minlength=H * W)
    v = np.clip(acc.reshape(H, W), 0, 1)
    img = (v[..., None] * COLOR * 255 + 0.5).astype(np.uint8)
    ff.stdin.write(img.tobytes())
    if fi % 48 == 0: print("frame", fi, "/", NF, flush=True)
ff.stdin.close(); ff.wait()
print("->", OUT)
