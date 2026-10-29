"""dust_ref -- a slow 'dust in waves' reference clip on black, for Higgsfield.

A dense field of fine silver grains in three depth layers (far: tiny and sharp,
mid, near: larger and soft as if out of focus). Slow travelling compression
waves with curved fronts slide the grains back and forth, so the dust bunches
into flowing bands with sparse gaps between them -- the background motion of
the drone reference, slowed down.

    python3 make_dust.py OUT.mp4 [seconds] [width] [height]
Needs numpy + ffmpeg.
"""
import math, subprocess, sys
import numpy as np

OUT = sys.argv[1]
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
W = int(sys.argv[3]) if len(sys.argv) > 3 else 1920
H = int(sys.argv[4]) if len(sys.argv) > 4 else 1080
FPS = 24
AR = W / H
rng = np.random.default_rng(7)

# depth layers: count, gaussian sigma (px at 1080p), peak brightness, parallax
LAYERS = [dict(n=16000, sigma=0.7,  peak=0.35, par=0.85),
          dict(n=9000,  sigma=1.2,  peak=0.75, par=1.0),
          dict(n=1100,  sigma=2.8,  peak=0.28, par=1.25)]
# slow waves (units: frame heights). A wave with "a" moves the grains so their
# density follows 1 + a*cos(phase) exactly (solved per grain, Kepler-style):
# wide dense bands and soft sparse gaps instead of hairline caustics. A wave
# with "amp" is a plain small sway that bends and breaks the bands up.
# warp curves the fronts into flowing ribbons.
WAVES = [dict(dir=-38, lam=0.62, a=0.95,    c=0.050, warp=1.3),
         dict(dir=62,  lam=1.10, amp=0.045, c=0.030, warp=1.5),
         dict(dir=160, lam=1.30, amp=0.020, c=0.020, warp=1.0)]
COLOR = np.array([0.86, 0.89, 0.96])      # cool silver
DRIFT = np.array([0.006, -0.003])         # very slow overall drift (frame heights / s)

def warp(x, y, t, s):
    """bends the wave fronts into gentle curves, and lets the bends evolve"""
    return s * (0.9 * np.sin(1.7 * x + 0.6 + 0.05 * t) + 0.7 * np.sin(2.6 * y - 1.3 - 0.04 * t)
                + 0.4 * np.sin(1.1 * (x + y) + 2.0))

def sprite(sigma):
    r = max(1, int(math.ceil(3 * sigma)))
    ax = np.arange(-r, r + 1)
    g = np.exp(-(ax[:, None] ** 2 + ax[None, :] ** 2) / (2 * sigma * sigma))
    return r, g / g.max()

layers = []
for L in LAYERS:
    s = L["sigma"] * H / 1080
    r, spr = sprite(s)
    pad = 0.15
    p = np.stack([rng.uniform(-pad, AR + pad, L["n"]), rng.uniform(-pad, 1 + pad, L["n"])], 1)
    b = L["peak"] * rng.uniform(0.35, 1.0, L["n"]) ** 1.5
    layers.append((L, r, spr, p, b))

ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                       "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                       "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
                       "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
NF = int(round(SECONDS * FPS))
for fi in range(NF):
    t = fi / FPS
    acc = np.zeros(H * W)
    for L, r, spr, p, b in layers:
        x, y = p[:, 0].copy(), p[:, 1].copy()
        for wv in WAVES:
            a = math.radians(wv["dir"]); nx, ny = math.cos(a), math.sin(a)
            ph = 2 * math.pi * ((p[:, 0] * nx + p[:, 1] * ny - wv["c"] * t) / wv["lam"]) \
                 + warp(p[:, 0], p[:, 1], t, wv["warp"])
            if "a" in wv:                     # density-shaping wave: solve P + a sin P = ph
                P = ph.copy()
                for _ in range(8): P -= (P + wv["a"] * np.sin(P) - ph) / (1 + wv["a"] * np.cos(P))
                d = -wv["a"] * wv["lam"] / (2 * math.pi) * L["par"] * np.sin(P)
            else:
                d = wv["amp"] * L["par"] * np.sin(ph)
            x += nx * d; y += ny * d
        x += DRIFT[0] * t * L["par"]; y += DRIFT[1] * t * L["par"]
        px, py = x * H, y * H
        ix, iy = np.floor(px).astype(int), np.floor(py).astype(int)
        fx, fy = px - ix, py - iy
        # bilinear sub-pixel split, then stamp the sprite at each of the 4 corners
        for cx, cy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)),
                          (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            bx, by, bw = ix + cx, iy + cy, b * w
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    g = spr[dy + r, dx + r]
                    if g < 0.02: continue
                    X, Y = bx + dx, by + dy
                    m = (X >= 0) & (X < W) & (Y >= 0) & (Y < H)
                    acc += np.bincount(Y[m] * W + X[m], bw[m] * g, minlength=H * W)
    v = 1.0 - np.exp(-acc.reshape(H, W) * 1.6)          # soft clip where grains overlap
    img = (np.clip(v[..., None] * COLOR, 0, 1) * 255 + 0.5).astype(np.uint8)
    ff.stdin.write(img.tobytes())
    if fi % 24 == 0: print("frame", fi, "/", NF, flush=True)
ff.stdin.close(); ff.wait()
print("->", OUT)
