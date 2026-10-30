"""orca_onboard -- hero film blocking, 36 s, 16:9, no sound. ONE continuous take.
Fast and smooth: nothing lingers.

  0-3     fly-in over the console tiers of the mission-control room and INTO the
          centre screen -> open space
  6       a signal beam rises from Earth to the satellite; card
          "Image the harbor at first light."
  10-17   close-up orbit round the satellite; card ORCA ONBOARD:
          Intent received -> Planning -> Guardrails cleared
  17-24.5 wide: satellite above Earth, hexagon imaging zone scans the harbor;
          status Executing
  24.5-36 pull back: out of space, back through the screen -- space is a picture
          on the wall again -- and we stand at the back of the same empty room

The centre screen is a real OPENING in the video wall; the space set sits behind
it, so going "into" and "out of" the screen is one physical camera move.
Rig: crane (big smooth arcs), speed ceiling raised for the space legs.

    python3 orca_onboard.py                      -> scene.json
    python3 solve_shot.py orca_onboard.py        -> bake.json
    python3 make_build.py                        -> build_orca_onboard.py + ../live.py
"""
import json, math, os

FPS, SECONDS = 24, 36
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
EV = dict(beam_up=(6.0, 7.0), beam_off=(9.8, 10.4),
          card1=(6.4, 10.0),
          card2=(10.4, 16.8), st_intent=11.0, st_plan=12.6, st_guard=14.2,
          hex_on=18.4, scan=(19.0, 24.0), cone=(18.6, 24.4),
          card3=(19.0, 24.2))

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
    "waypoints": [(0.0, *S), (1.0, *S), (4.2, *SAT), (5.2, *SAT), (16.0, *SAT), (17.0, *SAT),
                  (20.0, *WIDE_M), (21.0, *WIDE_M), (23.5, *WIDE_M), (24.5, *WIDE_M),
                  (29.0, *SAT), (30.5, *SAT), (32.8, *S), (33.8, *S), (36.0, *S)]},
  "shots": [{"t0": 0.0, "t1": SECONDS, "name": "one_take", "camera": {
      "aim_distance": 6.0, "subject_smooth": 12, "lens_smooth": 10,
      "waypoints": [
        # fly-in: already moving, over the console tiers and through the screen at ~3 s
        {"t": 0.0,  "pos": [0.0, -16.6, 4.5], "lens": 30, "aim": [0, 0, 0]},
        {"t": 1.5,  "pos": [0.0, -7.3, 4.46], "lens": 30, "aim": [0, 0, 0]},
        # (no key on the wall: it would kink the speed)
        # float toward the satellite, then straight into the orbit (no stop)
        {"t": 5.5,  "pos": [0.0, 8.0, 5.4], "lens": 31, "aim": [0, 0, 0]},
        # close-up: orbit round the satellite, 90 deg in 8 s, starting dead ahead of it
        {"t": 9.0,  "pos": orbit(-90), "lens": 32, "aim": [0, 0, 0]},
        {"t": 11.67, "pos": orbit(-60), "lens": 32, "aim": [0, 0, 0]},
        {"t": 14.33, "pos": orbit(-30), "lens": 32, "aim": [0, 0, 0]},
        {"t": 17.0, "pos": orbit(0), "lens": 32, "aim": [0, 0, 0]},
        # wide: on the side the orbit carries us to -- satellite above Earth, hexagon below
        {"t": 21.0, "pos": [46.0, 18.0, 2.5], "lens": 28, "aim": [0, 0, 0]},
        {"t": 24.5, "pos": [47.0, 23.0, 3.5], "lens": 28, "aim": [0, 0, 0]},
        # pull back: out of space, back through the screen (~30.5 s), into the room
        {"t": 27.0, "pos": [26.0, 12.0, 7.0], "lens": 29, "aim": [0, 0, 0]},
        {"t": 29.0, "pos": [8.0, 8.0, 6.0], "lens": 30, "aim": [0, 0, 0]},
        {"t": 30.3, "pos": [0.0, 3.0, 4.5], "lens": 30, "aim": [0, 0, 0]},
        {"t": 32.3, "pos": [0.0, -8.6, 4.45], "lens": 30, "aim": [0, 0, 0]},
        # back to the very back of the hall, settling where the film started
        {"t": 34.3, "pos": [0.0, -15.4, 4.48], "lens": 30, "aim": [0, 0, 0]},
        {"t": 36.0, "pos": [0.0, -16.6, 4.5], "lens": 30, "aim": [0, 0, 0]},
      ]}}],
  "beats": [
    (0.0,  "back of the empty mission-control room, already flying in; giant video wall ahead, satellite over Earth on the centre screen"),
    (1.5,  "the centre screen fills the frame"),
    (3.0,  "through the screen: open space, Earth below, satellite ahead"),
    (6.0,  "a signal beam rises from Earth to the satellite; card: Image the harbor at first light."),
    (10.0, "close-up of the satellite, orbit; card ORCA ONBOARD"),
    (11.0, "status: Intent received"), (12.6, "status: Planning"), (14.2, "status: Guardrails cleared"),
    (17.0, "pull out to wide"),
    (18.4, "hexagon imaging zone appears on the harbor below and scans; status Executing"),
    (24.5, "pull back toward the screen"),
    (30.5, "back through the screen: space is a picture on the wall again"),
    (36.0, "standing at the very back of the empty room, where the film began"),
  ],
}

if __name__ == "__main__":
    H = os.path.dirname(os.path.abspath(__file__))
    out = dict(fps=FPS, frames=NF, room=ROOM, screen=SCREEN, tier=TIER, sat=SAT, sat_yaw=SAT_YAW, earth=EARTH,
               harbor=HARBOR, beam_foot=BEAM_FOOT, ev=EV)
    json.dump(out, open(os.path.join(H, "scene.json"), "w"), indent=1)
    print("scene ->", os.path.join(H, "scene.json"))
