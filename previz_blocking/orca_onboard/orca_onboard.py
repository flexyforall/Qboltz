"""orca_onboard -- hero film blocking, 30 s, 16:9, no sound. ONE continuous take.
Fast and smooth: nothing lingers.

  0-3     fly-in over the console tiers of the mission-control room and INTO the
          centre screen -> open space
  6       a signal beam rises from Earth to the satellite; card
          "Image the harbor at first light."
  9-14.5  close-up orbit round the satellite; card ORCA ONBOARD:
          Intent received -> Planning -> Guardrails cleared
  14.5-20 wide: satellite above Earth, hexagon imaging zone scans the harbor;
          status Executing
  20-30   pull back: out of space, back through the screen -- space is a picture
          on the wall again -- and we stand at the back of the same empty room

The centre screen is a real OPENING in the video wall; the space set sits behind
it, so going "into" and "out of" the screen is one physical camera move.
Rig: crane (big smooth arcs), speed ceiling raised for the space legs.

    python3 orca_onboard.py                      -> scene.json
    python3 solve_shot.py orca_onboard.py        -> bake.json
    python3 make_build.py                        -> build_orca_onboard.py + ../live.py
"""
import json, math, os

FPS, SECONDS = 24, 30
NF = FPS * SECONDS

# ------------------------------------------------------------------ room ----
# the video wall is the plane y = 0; the room is behind it (y < 0)
ROOM = dict(half_w=13.0, back=-18.0, ceil=7.6)
SCREEN = dict(w=10.0, h=4.6, z0=2.0)            # the centre screen = the opening
SCREEN_C = (0.0, 0.0, SCREEN["z0"] + SCREEN["h"] / 2)      # (0, 0, 4.3)
TIER = dict(front=-4.0, depth=2.4, rise=0.45, n=5)         # console tiers step up to the back

# ----------------------------------------------------------------- space ----
SAT = (0.0, 28.0, 5.5)                           # the satellite
SAT_YAW = 35.0                                   # turned so it reads side-on, like the ref
EARTH = dict(c=(0.0, 180.0, -505.0), r=500.0)    # Earth: its top sits at z=-5, y=180
def surface(x, y):
    cx, cy, cz = EARTH["c"]; r = EARTH["r"]
    return cz + math.sqrt(r * r - (x - cx) ** 2 - (y - cy) ** 2)
HARBOR = (5.0, 46.0, round(surface(5.0, 46.0), 3))         # the hexagon zone sits here
BEAM_FOOT = (1.0, 36.0, round(surface(1.0, 36.0), 3))       # the signal leaves Earth here
WIDE_M = tuple(round((SAT[k] * 0.55 + HARBOR[k] * 0.45), 3) for k in range(3))  # wide framing centre

# -------------------------------------------------------- events (seconds) --
EV = dict(beam_up=(6.0, 7.0), beam_off=(8.6, 9.2),
          card1=(7.2, 9.2),               # only once the beam has reached the satellite
          card2=(9.4, 14.4), st_intent=10.0, st_plan=11.3, st_guard=12.6,
          hex_on=15.8, scan=(16.4, 20.2), cone=(16.0, 20.6),
          card3=(16.4, 20.4))

# ------------------------------------------------------------------ shot ----
def orbit(az_deg, r=14.0, dz=2.0):
    a = math.radians(az_deg)
    return [round(SAT[0] + r * math.cos(a), 3), round(SAT[1] + r * math.sin(a), 3), SAT[2] + dz]

S = SCREEN_C
SHOT = {
  "name": "orca_onboard", "fps": FPS, "seconds": SECONDS,
  "rig": "crane",
  # space legs cover tens of metres in a few seconds -- that is the point of them
  # the space set is scaled down, so its legs cover a lot of metres fast
  "limits": {"max_cam_speed": 14.0},
  "subject": {   # the ATTENTION point (invisible): screen -> satellite -> wide -> screen
    "mode": "waypoints", "size": [0.4, 0.4, 0.4],
    # hold keys either side of every stop: Catmull-Rom overshoots a lone key
    "waypoints": [(0.0, *S), (1.0, *S), (4.2, *SAT), (5.2, *SAT), (13.5, *SAT), (14.5, *SAT),
                  (17.5, *WIDE_M), (18.5, *WIDE_M), (19.3, *WIDE_M), (20.0, *WIDE_M),
                  (24.4, *SAT), (25.2, *SAT), (27.0, *S), (28.0, *S), (30.0, *S)]},
  "shots": [{"t0": 0.0, "t1": SECONDS, "name": "one_take", "camera": {
      "aim_distance": 6.0, "subject_smooth": 12, "lens_smooth": 10,
      "waypoints": [
        # fly-in: already moving, over the console tiers and through the screen at ~3 s
        {"t": 0.0,  "pos": [0.0, -16.6, 4.5], "lens": 30, "aim": [0, 0, 0]},
        {"t": 1.5,  "pos": [0.0, -7.3, 4.46], "lens": 30, "aim": [0, 0, 0]},
        # (no key on the wall: it would kink the speed)
        # float toward the satellite, then straight into the orbit (no stop)
        {"t": 5.5,  "pos": [0.0, 8.0, 5.4], "lens": 31, "aim": [0, 0, 0]},
        # close-up: orbit round the satellite, 75 deg in 5.5 s, starting dead ahead of it
        {"t": 9.0,  "pos": orbit(-90), "lens": 32, "aim": [0, 0, 0]},
        {"t": 10.83, "pos": orbit(-65), "lens": 32, "aim": [0, 0, 0]},
        {"t": 12.67, "pos": orbit(-40), "lens": 32, "aim": [0, 0, 0]},
        {"t": 14.5, "pos": orbit(-15), "lens": 32, "aim": [0, 0, 0]},
        # wide: on the side the orbit carries us to -- satellite above Earth, hexagon below
        {"t": 17.8, "pos": [44.0, 18.0, 2.5], "lens": 28, "aim": [0, 0, 0]},
        {"t": 20.0, "pos": [45.0, 22.0, 3.3], "lens": 28, "aim": [0, 0, 0]},
        # pull back: out of space, back through the screen (~25.5 s), into the room
        {"t": 22.3, "pos": [24.0, 12.0, 7.0], "lens": 29, "aim": [0, 0, 0]},
        {"t": 24.0, "pos": [7.0, 7.0, 6.0], "lens": 30, "aim": [0, 0, 0]},
        {"t": 25.0, "pos": [0.0, 2.5, 4.5], "lens": 30, "aim": [0, 0, 0]},
        {"t": 26.8, "pos": [0.0, -8.6, 4.45], "lens": 30, "aim": [0, 0, 0]},
        # back to the very back of the hall, settling where the film started
        {"t": 28.5, "pos": [0.0, -15.4, 4.48], "lens": 30, "aim": [0, 0, 0]},
        {"t": 30.0, "pos": [0.0, -16.6, 4.5], "lens": 30, "aim": [0, 0, 0]},
      ]}}],
  "beats": [
    (0.0,  "back of the empty mission-control room, already flying in; giant video wall ahead, satellite over Earth on the centre screen"),
    (1.5,  "the centre screen fills the frame"),
    (3.0,  "through the screen: open space, Earth below, satellite ahead"),
    (6.0,  "a signal beam rises from Earth to the satellite"),
    (7.2,  "the beam has arrived; card: Image the harbor at first light."),
    (9.0,  "close-up of the satellite, orbit; card ORCA ONBOARD"),
    (10.0, "status: Intent received"), (11.3, "status: Planning"), (12.6, "status: Guardrails cleared"),
    (14.5, "pull out to wide"),
    (15.8, "hexagon imaging zone appears on the harbor below and scans; status Executing"),
    (20.0, "pull back toward the screen"),
    (25.4, "back through the screen: space is a picture on the wall again"),
    (30.0, "standing at the very back of the empty room, where the film began"),
  ],
}

if __name__ == "__main__":
    H = os.path.dirname(os.path.abspath(__file__))
    out = dict(fps=FPS, frames=NF, room=ROOM, screen=SCREEN, tier=TIER, sat=SAT, sat_yaw=SAT_YAW, earth=EARTH,
               harbor=HARBOR, beam_foot=BEAM_FOOT, ev=EV)
    json.dump(out, open(os.path.join(H, "scene.json"), "w"), indent=1)
    print("scene ->", os.path.join(H, "scene.json"))
