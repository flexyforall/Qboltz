# Light Scan scenes (Blender)

A floating light scans a field of round, drifting particles, finds the right spot,
becomes one light and floats away. `qboltz_light_scan.py` builds the whole scene:
geometry, materials, animation, camera, compositor and render settings.

| Variant | Length | What happens |
| --- | --- | --- |
| `lighthouse` (option 1) | 12 s, 289 frames | The light appears among the orbiting dots. 3 beams sweep slowly like a lighthouse, and the blue scan haze lights the particles it passes. The sweep eases onto one cluster, the light flies there, the beams open into an X-flare and fold into one line, then one star floats off to the upper right with a trail. |
| `search` (option 2) | 15 s, 361 frames | The camera dollies through the field. A fan of 4 beams snaps from one candidate cluster to the next. Each candidate pulses, gets rejected, dims and drifts off. The light locks on the right one: all beams merge into one line, the cluster tightens and flares, the light glides into it, absorbs it and leaves on an arc. |

Previews (low-res Cycles test renders, 480×270): `previews/lighthouse.mp4`, `previews/search.mp4`.

## Run

**In Blender (4.2 LTS or newer, tested on 5.2):**

1. Open the **Scripting** workspace and click **Open**, then pick `qboltz_light_scan.py`.
2. Set `VARIANT = "lighthouse"` or `"search"` at the top of the file.
3. Click **Run Script**. A new scene `QB_Lighthouse` / `QB_Search` is created and opened.
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

## How it is built

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
