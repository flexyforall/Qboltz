"""Ray motion for the ray-scan blocking shot. Plain python, Z-up, metres.

Shared by the shot spec (to place the camera on the rays) and by build.py (to bake
the rays into Blender), so the camera and the rays can never disagree.

Six rays thrash out of one hub, each wandering in azimuth and elevation on two
incommensurate sines, which reads as chaotic scanning. On top of the chaos, STEER
eases a ray toward a set heading for a while: that is how YELLOW settles for its
close-up and then swings away out of the camera's path, and how MAGENTA settles,
locks and levels out for the follow. Azimuth is measured clockwise from +Y.
"""
import math

FPS, SECONDS = 24, 15
HUB = (0.0, 0.0, 1.6)
NAMES = ["yellow", "cyan", "green", "blue", "magenta", "orange"]
A, B = 0, 4                 # first close-up: YELLOW. Second close-up and the followed ray: MAGENTA.
RAY_LEN = 18.0
AZ_A, EL_A = 40.0, 16.0     # where YELLOW settles for its close-up (degrees)
AZ_B, EL_B = -50.0, 20.0    # where MAGENTA settles; it then levels to EL_FOLLOW
EL_FOLLOW = 4.5

# chaos phases; PHASE is tuned by check_rays.py --search so no ray sweeps through the lens
PHASE = [0.0, 0.56, 0.0, 0.0, 0.0, 2.004]
SPECS = [dict(az0=i * math.pi / 3 + 0.25,
              aa=(0.85, 0.45), fa=(0.62 + 0.09 * i, 1.27 - 0.08 * i), pa=(i * 1.7, i * 0.9 + 1),
              el0=0.3 + 0.18 * math.sin(i * 2.3),
              ae=(0.38, 0.2), fe=(0.81 + 0.06 * i, 1.63 - 0.11 * i), pe=(i * 2.2, i * 1.3 + 0.5))
         for i in range(len(NAMES))]

# ray: [(in0, in1, out0, out1, az_deg, el_deg, strength)], applied in order
STEER = {
    A: [(3.4, 4.6, 5.6, 6.6, AZ_A, EL_A, 0.88),           # settle for the close-up
        (5.6, 6.8, 8.6, 9.8, AZ_A + 35, 38.0, 0.9)],       # swing away, out of the camera's path
    B: [(7.2, 8.6, 99, 100, AZ_B, EL_B, 0.88),             # settle for the close-up
        (9.8, 11.4, 99, 100, AZ_B, EL_FOLLOW, 1.0)],       # lock and level out for the follow
    5: [(10.0, 11.6, 99, 100, -125.0, 30.0, 0.65)],        # ORANGE drifts wide of MAGENTA's line for the follow
}


def smooth(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * t * (t * (6 * t - 15) + 10)


def bump(t, a, b, c, d):
    return smooth(a, b, t) * (1 - smooth(c, d, t))


def speed(i, t):
    """How fast ray i's chaos runs (1 = full); a ray being steered calms down too."""
    s = 1.0
    for (a, b, c, d, *_rest) in STEER.get(i, []):
        s *= 1 - 0.7 * bump(t, a, b, c, d)
    return s


_DT = 1.0 / 240
_NT = int((SECONDS + 2) / _DT) + 2
_TAU = []


def _tabulate():
    _TAU.clear()
    for i in range(len(NAMES)):
        a = [0.0] * _NT
        for k in range(1, _NT):
            a[k] = a[k - 1] + 0.5 * (speed(i, (k - 1) * _DT) + speed(i, k * _DT)) * _DT
        _TAU.append(a)


_tabulate()


def _tau(i, t):
    x = min(max(t, 0.0), (_NT - 1) * _DT) / _DT
    k = min(_NT - 2, int(x))
    f = x - k
    return _TAU[i][k] * (1 - f) + _TAU[i][k + 1] * f


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def angles(i, t):
    """(azimuth, elevation) in radians."""
    s, tau, ph = SPECS[i], _tau(i, t), PHASE[i]
    az = s["az0"] + s["aa"][0] * math.sin(s["fa"][0] * tau + s["pa"][0] + ph) \
                  + s["aa"][1] * math.sin(s["fa"][1] * tau + s["pa"][1] + 1.7 * ph)
    el = s["el0"] + s["ae"][0] * math.sin(s["fe"][0] * tau + s["pe"][0] + 2.3 * ph) \
                  + s["ae"][1] * math.sin(s["fe"][1] * tau + s["pe"][1] + 0.6 * ph)
    el = 0.55 + 0.62 * math.tanh((el - 0.55) / 0.62)       # soft limits: never into the floor, never straight up
    for (a, b, c, d, taz, tel, k) in STEER.get(i, []):
        w = k * bump(t, a, b, c, d)
        az += w * _wrap(math.radians(taz) - az)
        el += w * (math.radians(tel) - el)
    return az, el


def direction(i, t):
    az, el = angles(i, t)
    return (math.cos(el) * math.sin(az), math.cos(el) * math.cos(az), math.sin(el))


def length(i, t):
    if i != B:
        return RAY_LEN
    x = min(1.0, max(0.0, (t - 11.4) / (SECONDS - 11.4)))
    return RAY_LEN + 190.0 * x ** 1.7                       # MAGENTA's tip races away into the distance


def point(i, t, d):
    u = direction(i, t)
    return (HUB[0] + u[0] * d, HUB[1] + u[1] * d, HUB[2] + u[2] * d)


def side(i, t):
    """Unit vector across ray i, horizontal."""
    u = direction(i, t)
    sx, sy = u[1], -u[0]
    n = math.hypot(sx, sy) or 1.0
    return (sx / n, sy / n, 0.0)


def at_az(az_deg, r, dz):
    """A point at azimuth az_deg, horizontal radius r from the hub, dz above it."""
    a = math.radians(az_deg)
    return (HUB[0] + r * math.sin(a), HUB[1] + r * math.cos(a), HUB[2] + dz)
