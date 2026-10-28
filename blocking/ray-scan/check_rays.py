"""Ray clearance: how close each ray comes to the lens. The solver gates the camera
against the proxy only; this covers the six rays, which it never sees.

    python3 check_rays.py            # report, from bake.json
    python3 check_rays.py --search   # also find chaos phases for the free rays (prints PHASE)

MAGENTA is skipped once the camera rides it (from FOLLOW_FROM), where riding close is the point.
"""
import json, math, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rays as R

FOLLOW_FROM = 10.4
MIN_CLEAR = 1.2           # metres from the lens to any ray
cam = [tuple(p) for p in json.load(open(os.path.join(HERE, "bake.json")))["shots"][0]["cam"]]


def clearance(i, step=1):
    worst = (1e9, 0.0)
    for f in range(0, len(cam), step):
        t = f / R.FPS
        if i == R.B and t >= FOLLOW_FROM:
            continue
        u, L = R.direction(i, t), R.length(i, t)
        d = [cam[f][k] - R.HUB[k] for k in range(3)]
        s = max(0.0, min(L, sum(d[k] * u[k] for k in range(3))))
        q = math.dist(d, [u[k] * s for k in range(3)])
        if q < worst[0]:
            worst = (q, t)
    return worst


if "--search" in sys.argv:
    random.seed(7)
    for i in range(len(R.NAMES)):
        if i in (R.A, R.B):
            continue
        best = (clearance(i, 2)[0], R.PHASE[i])
        for _ in range(300):
            R.PHASE[i] = random.uniform(-math.pi, math.pi)
            c = clearance(i, 2)[0]
            if c > best[0]:
                best = (c, R.PHASE[i])
            if c > 2.5:
                break
        R.PHASE[i] = best[1]
    print("PHASE =", [round(p, 3) for p in R.PHASE])

ok = True
for i, name in enumerate(R.NAMES):
    c, t = clearance(i)
    ok &= c >= MIN_CLEAR
    print(f"  [{'PASS' if c >= MIN_CLEAR else 'FAIL'}] {name:8s} closest {c:5.2f} m at {t:5.2f} s")
print("  ALL RAYS CLEAR" if ok else "  A RAY SWEEPS THROUGH THE LENS")
sys.exit(0 if ok else 1)
