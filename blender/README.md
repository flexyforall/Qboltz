# Light Scan scenes (Blender)

A floating light scans a field of round, drifting particles, finds the right spot,
becomes one light and floats away. `qboltz_light_scan.py` builds the whole scene:
geometry, materials, animation, camera, compositor and render settings.

| Variant | Length | What happens |
| --- | --- | --- |
| `answer` (final, default) | 18 s, 432 frames, 1280×720 | **Placeholder movement reference** for video-to-video restyling (e.g. Higgsfield): one continuous shot with glow, star glints, blue-violet haze and depth of field, and nothing pops in or out. The hub, dead centre, ignites and 5 rays of different strength grow out of it one after another, then scan the 3D dot field while the camera orbits. As a faint ray sweeps towards an ordinary dot (there from the first frame), the camera starts turning to it. The ray lands on the dot (the part beyond it pulls back) and the dot ignites. The camera follows alongside the ray, flies past the dot with it in frame the whole time, and eases onto the site's hero frame: the dot at 72% across, 33% down, its ray trailing left. The other rays keep scanning and only pull back into the hub once it is out of view. |
| `lighthouse` (option 1) | 12 s, 289 frames | The light appears among the orbiting dots. 3 beams sweep slowly like a lighthouse, and the blue scan haze lights the particles it passes. The sweep eases onto one cluster, the light flies there, the beams open into an X-flare and fold into one line, then one star floats off to the upper right with a trail. |
| `search` (option 2) | 15 s, 361 frames | The camera dollies through the field. A fan of 4 beams snaps from one candidate cluster to the next. Each candidate pulses, gets rejected, dims and drifts off. The light locks on the right one: all beams merge into one line, the cluster tightens and flares, the light glides into it, absorbs it and leaves on an arc. |

Previews (low-res Cycles test renders): `previews/answer.mp4` (1280×720), `previews/lighthouse.mp4`, `previews/search.mp4` (480×270).

## Run

**In Blender (4.2 LTS or newer, tested on 5.2):**

1. Open the **Scripting** workspace and click **Open**, then pick `qboltz_light_scan.py`.
2. Set `VARIANT = "answer"`, `"lighthouse"` or `"search"` at the top of the file.
3. Click **Run Script**. A new scene (`QB_Answer`, `QB_Lighthouse` or `QB_Search`) is created and opened.
   Running it again rebuilds that scene. Your other scenes are not touched.
4. Press `Numpad 0` for the camera view and play the timeline. Use **Rendered** viewport shading to see the glow.
5. Press **Render > Render Animation** (`Ctrl F12`). The default output is an H.264 MP4 in `//renders/`
   next to your .blend.

**From a terminal:**

```sh
blender --background --python qboltz_light_scan.py -- --variant search --render
blender --background --python qboltz_light_scan.py -- --variant lighthouse --save lighthouse.blend
blender --background --python qboltz_light_scan.py -- --variant lighthouse --still 210 --output frame.png
```

Options: `--variant`, `--engine eevee|cycles`, `--scale <percent>`, `--samples N`, `--render`,
`--still FRAME`, `--output PATH`, `--save PATH.blend`.

## How `answer` is built

- A placeholder look with enough mood for a restyle to latch on to: emission plus compositor glow, star glints,
  a soft blue-violet haze around the rays and depth of field. Restyle models keep big shapes and redraw
  fine detail, so the rays are thick and the dots big and sparse.
- **Camera**: the path is a smooth curve through waypoints, re-parameterised by arc length.
  The timing is a separate distance-over-time curve, so speed and direction never hitch. The last
  glide is timed as a pure ease-out, so the camera comes to rest without a jolt. To retime
  the shot, edit `timing` (time, waypoint, speed). To change the route, edit `waypoints`.
- **The final frame is solved, not eyeballed**: `aim()` finds the camera direction that puts the end light
  exactly at 72% / 33% of the frame.
- **Rays**: each one sweeps on its own yaw and pitch curve. The winner's sweep is phase-shifted
  so it crosses the answer at 5 s by itself, then eases in and holds.
- Nothing appears or disappears on screen: the found dot exists from the first frame, the followed ray
  never fades, and the other rays only retract into the hub after the camera has turned away from it
  (worked out from the camera, so it stays true if you retime the shot).

## How `lighthouse` / `search` are built

- **Particles**: real ico-spheres, so they stay perfectly round, instanced on points by a
  Geometry Nodes group (`QB_Drift`). Each point drifts on 4D noise driven by scene time.
  The points are laid out as dotted orbital arcs plus loose dust, like the references.
  Clusters are separate objects, so they can pulse, dim, drift off or be absorbed.
- **Scan reaction**: the particle shader reads its position in the scan rig's space, so any
  particle inside the scan cone, or near the light, glows brighter as the cone sweeps over it.
- **Light rig**: `QB_Source` (moves) carries the hot core, a soft halo, `QB_ScanRig` (where it
  looks) with the beams and the blue scan haze (an emission-only volume), and `QB_TrailRig`, which damped-tracks
  a lagging anchor so the trail always points back along the path.
- **Glow and star glint**: compositor Glare nodes, Fog Glow and then 6 Streaks. Only the very
  bright core gets the star.
- **Animation**: plain keyframes on objects and on the `Value` nodes inside the materials
  (`Master`, `Glow`, `ScanGain`, `Strength`). Open a material in the Shader Editor to retime or
  tweak an intensity.

## Tweaks

At the top of the script: `PARTICLE_COLOR`, `BEAM_HALO_COLOR`, `CONE_COLOR`, `CONE_HALF_ANGLE`,
`RES_X/RES_Y`, `FPS`, `SEED` (a different particle layout). The timings live in
`build_lighthouse()` / `build_search()` and are written in seconds.

EEVEE is the default because it renders fast. Cycles (`ENGINE = "cycles"`) gives smoother
volumetric haze and depth of field.
