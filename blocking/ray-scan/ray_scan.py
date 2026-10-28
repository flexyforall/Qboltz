"""Shot spec: ray-scan. Solve with  python3 <skill>/scripts/solve_shot.py ray_scan.py

The "subject" is an attention proxy, not a prop: a 0.6 m box riding wherever the
camera should be looking. It sits on the hub, slides out onto YELLOW, crosses to
MAGENTA, then runs ahead along MAGENTA for the follow. build.py hides it, so it never
reaches the viewport or the render. The rays themselves come from rays.py.

YELLOW and MAGENTA settle either side of the camera, so the camera never crosses a ray.
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rays as R

HALF = 0.3                                    # proxy half-size: waypoints are the box BASE
UP = (0.0, 0.0, 1.0)

# the numbers that shape the move (times in s, distances in m, azimuths in degrees).
# Hand-placed first, then refined by random search against the solver's gates.
P = {
    "c0_az": -5.0, "c0_r": 3.6, "c0_dz": 1.3,           # start: slightly in front of and above the hub
    "c1_t": 2.57, "c1_az": 2.33, "c1_r": 5.27, "c1_dz": 2.04,
    "a_t": 4.55, "a_d": 6.3, "a_off": 3.07, "a_up": 2.07, "a_back": -1.02,          # beside YELLOW
    "m_t": 7.08, "m_az": 13.73, "m_r": 7.84, "m_dz": 4.01,                    # ease back, pan across
    "b_t": 9.92, "b_d": 5.0, "b_off": 3.54, "b_up": 1.99, "b_back": 2.65,          # beside MAGENTA
    "l_t": 12.4, "l_d": 5.85, "e_d": 11.46,                                  # onto MAGENTA's line, follow
    "s_a0": 4.46, "s_a1": 5.15, "s_m": 6.94, "s_b0": 8.54, "s_b1": 9.34, "s_l": 12.46,  # where the eye goes, when
}


def add(*vs):
    return tuple(sum(c) for c in zip(*vs))


def mul(v, s):
    return tuple(c * s for c in v)


def base(p):
    return (p[0], p[1], p[2] - HALF)


def beside(i, t, d, off, up, back, prev):
    """Camera beside ray i at distance d along it, on whichever side is nearer `prev`."""
    p, u, s = R.point(i, t, d), R.direction(i, t), R.side(i, t)
    cands = [add(p, mul(s, sg * off), mul(UP, up), mul(u, -back)) for sg in (1, -1)]
    return min(cands, key=lambda c: math.dist(c, prev))


def on_b(t, d):
    """Just above MAGENTA and a touch to the side, d metres out from the hub."""
    return add(R.point(R.B, t, d), mul(UP, 0.45), mul(R.side(R.B, t), 0.25))


def build_shot(P):
    pA = lambda t: R.point(R.A, t, 5.0)
    pB = lambda t: R.point(R.B, t, 5.0)
    subject = [
        (0.0,       *base(R.HUB)),
        (2.0,       *base(R.at_az(R.AZ_A, 1.4, 0.35))),
        (P["s_a0"], *base(pA(P["s_a0"]))),
        (P["s_a1"], *base(pA(P["s_a1"]))),
        (P["s_m"],  *base(R.at_az(-5.0, 3.6, 1.2))),
        (P["s_b0"], *base(pB(P["s_b0"]))),
        (P["s_b1"], *base(pB(P["s_b1"]))),
        (P["s_l"],  *base(R.point(R.B, P["s_l"], 10.0))),
        (15.0,      *base(R.point(R.B, 15.0, 17.0))),
    ]
    C0 = R.at_az(P["c0_az"], P["c0_r"], P["c0_dz"])
    C1 = R.at_az(P["c1_az"], P["c1_r"], P["c1_dz"])
    CA = beside(R.A, P["a_t"], P["a_d"], P["a_off"], P["a_up"], P["a_back"], C1)
    CM = R.at_az(P["m_az"], P["m_r"], P["m_dz"])
    CB = beside(R.B, P["b_t"], P["b_d"], P["b_off"], P["b_up"], P["b_back"], CM)
    wp = lambda t, pos, lens: {"t": t, "pos": list(pos), "lens": lens, "aim": [0, 0, HALF]}
    return {
        "name": "ray_scan", "fps": R.FPS, "seconds": R.SECONDS,
        "rig": "gimbal",
        "subject": {"mode": "waypoints", "size": [2 * HALF] * 3, "waypoints": subject},
        "shots": [{"t0": 0.0, "t1": 15.0, "name": "one take", "camera": {
            "fit": 0.80, "aim_distance": 5.0, "subject_smooth": 6, "lens_smooth": 10,
            "waypoints": [
                wp(0.0, C0, 22), wp(P["c1_t"], C1, 24), wp(P["a_t"], CA, 32),
                wp(P["m_t"], CM, 30), wp(P["b_t"], CB, 32),
                wp(P["l_t"], on_b(P["l_t"], P["l_d"]), 26), wp(15.0, on_b(15.0, P["e_d"]), 20),
            ]}}],
        "beats": [
            (0.0,       "wide, slightly in front of and above the hub; six rays thrash, scanning"),
            (P["c1_t"], "the camera drifts round; the rays sweep past"),
            (P["s_a0"], "close on YELLOW, which calms as the camera holds on it"),
            (P["s_a1"], "YELLOW swings away; the camera eases back and pans across to MAGENTA"),
            (P["s_b0"], "close on MAGENTA; it calms and locks"),
            (P["s_b1"], "slip onto MAGENTA's line, just above it"),
            (P["s_l"],  "follow MAGENTA as its tip stretches away into the distance"),
        ],
    }


SHOT = build_shot(P)
