# The Answer: WebGL scene

The intro animation, written in code instead of Blender. It renders in seconds per frame, even
without a GPU, so motion changes can be checked quickly. It can also run live in the browser.

**What happens (about 21 s, one continuous shot):**
1. We are right at the root of the light: the hub ignites close in front of us, and 5 rays shoot out
   of it, past the camera and off frame. Their ends are never seen.
2. The camera floats around the hub at arm's length as the rays sweep. Now and then a ray falls on
   a dot in the background, and the dot catches the light and glints for a moment.
3. The rays swing together and merge into one, pointing at an ordinary dot that has been in the
   field from the first frame. The camera slips in behind the hub.
4. POV: the ray runs straight ahead of us and lands on the dot, which ignites.
5. We travel along the ray, then drift out to the side and ease onto the hero frame: the dot at
   72% across and 33% down, its ray trailing left and fading. The shot holds.

## Files

- `choreo.js`: the choreography, pure math with no rendering. It covers the camera route, the
  speed, the aim, the depth of field, and the rays' sweeps, merge and stretch. The glinting dots
  (`CATCHES`) are placed exactly on a ray's path at a moment it is in frame.
- `light-scan.js`: the WebGL renderer, built on three.js. It draws tiny dots on dotted orbital arcs,
  screen-space rays with crisp cores and glow, a ray-marched blue-violet haze, star glints, bloom
  and grain.
- `index.html`: plays the scene live. Space pauses, ←/→ steps a frame.
- `render.mjs`: renders frames and an MP4 in headless Chromium.
- `vendor/three`: three.js r170 (MIT), so nothing loads from the network.
- `previews/the-answer.mp4`: the latest render, 1280×720.

## Run

```sh
npx serve scene                      # then open http://localhost:3000 (any static server works)
node scene/render.mjs                # -> scene/out/the-answer.mp4 (needs Playwright + ffmpeg)
node scene/render.mjs --times 3,12   # single stills -> scene/out/stills
```

## Tweaking

- **Look:** the `LOOK` block at the top of `light-scan.js` sets the haze colour and strength, the
  bloom, the dot brightness and the grain.
- **Rays:** `RAYS` in `choreo.js` sets each ray's sweep speed, wobble, strength and line widths.
- **Camera:** `ROUTE` in `choreo.js` lists the waypoints, each with a speed. Each stretch lasts
  exactly as long as a straight speed ramp needs, so speed never bulges. The story moments
  (visits, merge, stretch, landing) are timed off the camera, so they stay in sync when the
  route changes.
- **Final frame:** `aim()` solves the camera direction that puts the dot exactly at 72% / 33%.
