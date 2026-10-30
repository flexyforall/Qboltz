"""orca_onboard -- hero film blocking, 48 s, 16:9, no sound. ONE continuous take.

  0-9.5   mission-control room: glide from the back over the console tiers to the
          giant video wall and INTO the centre screen -> open space
  ~9.7    a signal beam rises from Earth to the satellite; card
          "Image the harbor at first light."
  16-25   close-up of the satellite, slow orbit; card ORCA ONBOARD:
          Intent received -> Planning -> Guardrails cleared
  25-34   wide: satellite above Earth, hexagon imaging zone scans the harbor;
          status Executing
  34-48   pull back: out of space, back through the screen -- space is a picture
          on the wall again -- and we stand at the back of the same empty room

The centre screen is a real OPENING in the video wall; the space set sits behind
it, so going "into" and "out of" the screen is one physical camera move.
Rig: crane (big smooth arcs), speed ceiling raised for the space legs.

    python3 orca_onboard.py                      -> scene.json
    python3 solve_shot.py orca_onboard.py        -> bake.json
    python3 make_build.py                        -> build_orca_onboard.py + ../live.py
"""
import json, math, os

FPS, SECONDS = 24, 48
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
WIDE_M = tuple(round((SAT[k] * 0.58 + HARBOR[k] * 0.42), 3) for k in range(3))  # wide framing centre

# -------------------------------------------------------- events (seconds) --
EV = dict(beam_up=(9.7, 11.0), beam_off=(15.4, 16.2),
          card1=(10.3, 15.8),
          card2=(16.6, 24.8), st_intent=17.2, st_plan=19.4, st_guard=21.8,
          hex_on=25.6, scan=(26.2, 33.6), cone=(25.8, 34.0),
          card3=(26.2, 33.8))

# ------------------------------------------------------------------ shot ----
def orbit(az_deg, r=14.0, dz=2.0):
    a = math.radians(az_deg)
    return [round(SAT[0] + r * math.cos(a), 3), round(SAT[1] + r * math.sin(a), 3), SAT[2] + dz]

S = SCREEN_C
SHOT = {
  "name": "orca_onboard", "fps": FPS, "seconds": SECONDS,
  "rig": "crane",
  # space legs cover tens of metres in a few seconds -- that is the point of them
  "limits": {"max_cam_speed": 10.5},
  "subject": {   # the ATTENTION point (invisible): screen -> satellite -> wide -> screen
    "mode": "waypoints", "size": [0.4, 0.4, 0.4],
    # hold keys either side of every stop: Catmull-Rom overshoots a lone key
    "waypoints": [(0.0, *S), (6.5, *S), (11.0, *SAT), (12.0, *SAT), (24.0, *SAT), (25.0, *SAT),
                  (28.0, *WIDE_M), (29.0, *WIDE_M), (32.5, *WIDE_M), (33.5, *WIDE_M),
                  (37.5, *SAT), (38.5, *SAT), (40.5, *SAT), (44.0, *S), (45.0, *S), (48.0, *S)]},
  "shots": [{"t0": 0.0, "t1": SECONDS, "name": "one_take", "camera": {
      "aim_distance": 6.0, "subject_smooth": 12, "lens_smooth": 10,
      "waypoints": [
        # the room: glide over the console tiers, eye a little above the desks
        {"t": 0.0,  "pos": [0.0, -16.6, 4.5], "lens": 30, "aim": [0, 0, 0]},
        {"t": 3.5,  "pos": [0.0, -13.6, 4.45], "lens": 30, "aim": [0, 0, 0]},
        {"t": 6.5,  "pos": [0.0, -8.8, 4.4], "lens": 30, "aim": [0, 0, 0]},
        {"t": 8.5,  "pos": [0.0, -3.4, 4.35], "lens": 30, "aim": [0, 0, 0]},
        # through the screen at ~9.5 s
        {"t": 9.5,  "pos": [0.0, 0.8, 4.35], "lens": 30, "aim": [0, 0, 0]},
        {"t": 12.0, "pos": [-0.8, 9.0, 5.0], "lens": 30, "aim": [0, 0, 0]},
        # close-up: slow orbit round the satellite, 90 deg in 9 s
        {"t": 16.0, "pos": orbit(-125), "lens": 32, "aim": [0, 0, 0]},
        {"t": 19.0, "pos": orbit(-95), "lens": 32, "aim": [0, 0, 0]},
        {"t": 22.0, "pos": orbit(-65), "lens": 32, "aim": [0, 0, 0]},
        {"t": 25.0, "pos": orbit(-35), "lens": 32, "aim": [0, 0, 0]},
        # wide: satellite above Earth, the hexagon below
        {"t": 30.0, "pos": [44.0, 6.0, 2.0], "lens": 28, "aim": [0, 0, 0]},
        {"t": 33.5, "pos": [45.5, 11.0, 3.0], "lens": 28, "aim": [0, 0, 0]},
        # pull back: out of space, back through the screen, into the room
        {"t": 38.0, "pos": [7.0, 11.0, 7.0], "lens": 30, "aim": [0, 0, 0]},
        {"t": 40.0, "pos": [0.0, 5.0, 4.5], "lens": 30, "aim": [0, 0, 0]},
        {"t": 42.0, "pos": [0.0, 0.2, 4.4], "lens": 30, "aim": [0, 0, 0]},
        {"t": 44.5, "pos": [0.0, -7.0, 4.45], "lens": 30, "aim": [0, 0, 0]},
        {"t": 48.0, "pos": [0.0, -16.0, 4.5], "lens": 30, "aim": [0, 0, 0]},
      ]}}],
  "beats": [
    (0.0,  "back of the empty mission-control room; giant video wall ahead, satellite over Earth on the centre screen"),
    (8.5,  "the centre screen fills the frame"),
    (9.5,  "through the screen: open space, Earth below, satellite ahead"),
    (9.7,  "a signal beam rises from Earth to the satellite; card: Image the harbor at first light."),
    (16.0, "close-up of the satellite, slow orbit; card ORCA ONBOARD"),
    (17.2, "status: Intent received"), (19.4, "status: Planning"), (21.8, "status: Guardrails cleared"),
    (25.0, "pull out to wide"),
    (25.6, "hexagon imaging zone appears on the harbor below and scans; status Executing"),
    (34.0, "pull back toward the screen"),
    (42.0, "back through the screen: space is a picture on the wall again"),
    (48.0, "standing at the back of the empty room"),
  ],
}

if __name__ == "__main__":
    H = os.path.dirname(os.path.abspath(__file__))
    out = dict(fps=FPS, frames=NF, room=ROOM, screen=SCREEN, tier=TIER, sat=SAT, sat_yaw=SAT_YAW, earth=EARTH,
               harbor=HARBOR, beam_foot=BEAM_FOOT, ev=EV)
    json.dump(out, open(os.path.join(H, "scene.json"), "w"), indent=1)
    print("scene ->", os.path.join(H, "scene.json"))
