// "The Answer": choreography. Pure math, no rendering, so it can be checked in Node too.
//
// Story (seconds):
//   0   - 2.6   the hub (dead centre) ignites, 5 rays of different strength grow out of it
//   2.6 - 8.5   the camera visits the rays one by one, following each as it sweeps;
//               the others stay in frame, softer, in the background
//   8.5 - 10    the rays swing together and merge into one, pointing at an ordinary dot
//               (there from the first frame); the camera moves in behind the hub
//   10  - 11.4  POV: the ray runs straight ahead of us and stretches into the distance
//               until it lands on the dot, which ignites
//   11.4 - 13   we travel along the ray
//   13  - 16.6  we drift out to the side, easing onto the hero frame: the dot at 72% / 33%,
//               its ray trailing left. Hold until 19 s.
//
// World: Z up, units are arbitrary. The hub sits at the origin.

import { Vector3, Quaternion } from 'three';

export const FPS = 24;
// ?ai renders a version made for video-to-video AI restyling: 1080p, bolder shapes, and a POV
// that sees the ray at an angle instead of dead-on (models misread a beam aimed at the lens)
export const AI_MODE = typeof location !== 'undefined' && new URLSearchParams(location.search).has('ai');
export const WIDTH = AI_MODE ? 1920 : 1280;
export const HEIGHT = AI_MODE ? 1080 : 720;
export const HFOV = 2 * Math.atan(18 / 35);                  // a 35 mm lens on a 36 mm sensor
export const TAN_H = Math.tan(HFOV / 2);
export const TAN_V = TAN_H * HEIGHT / WIDTH;
export const VFOV_DEG = 2 * Math.atan(TAN_V) * 180 / Math.PI;

const UP = new Vector3(0, 0, 1);
const v3 = (x, y, z) => new Vector3(x, y, z);

// easing ---------------------------------------------------------------------------
const clamp01 = (x) => Math.min(Math.max(x, 0), 1);
export const smooth = (x) => { x = clamp01(x); return x * x * (3 - 2 * x); };
export const smoother = (x) => { x = clamp01(x); return x * x * x * (x * (6 * x - 15) + 10); };
export const ramp = (t, t0, t1, a, b, ease = smooth) => a + (b - a) * ease((t - t0) / (t1 - t0));

function slerpVec(a, b, k) {
  const d = Math.min(Math.max(a.dot(b), -1), 1);
  const th = Math.acos(d);
  if (th < 1e-5) return a.clone().lerp(b, k).normalize();
  const s = Math.sin(th);
  return a.clone().multiplyScalar(Math.sin((1 - k) * th) / s)
    .add(b.clone().multiplyScalar(Math.sin(k * th) / s)).normalize();
}

// Smooth curve through (time, Vector3) keys: cubic Hermite with Catmull-Rom tangents.
// A key equal to its neighbour is a hold (zero tangent), so holds never overshoot.
class Track {
  constructor(keys) { this.k = keys; }
  tangent(i) {
    const k = this.k;
    if (i === 0 || i === k.length - 1) return v3(0, 0, 0);
    if (k[i - 1][1].distanceTo(k[i][1]) < 1e-9 || k[i + 1][1].distanceTo(k[i][1]) < 1e-9) return v3(0, 0, 0);
    return k[i + 1][1].clone().sub(k[i - 1][1]).divideScalar(k[i + 1][0] - k[i - 1][0]);
  }
  at(t) {
    const k = this.k;
    if (t <= k[0][0]) return k[0][1].clone();
    if (t >= k[k.length - 1][0]) return k[k.length - 1][1].clone();
    let i = 0;
    while (k[i + 1][0] <= t) i++;
    const [t0, p0] = k[i], [t1, p1] = k[i + 1];
    const h = t1 - t0, s = (t - t0) / h;
    const h00 = 2 * s ** 3 - 3 * s ** 2 + 1, h10 = s ** 3 - 2 * s ** 2 + s;
    const h01 = -2 * s ** 3 + 3 * s ** 2, h11 = s ** 3 - s ** 2;
    return p0.clone().multiplyScalar(h00)
      .add(this.tangent(i).multiplyScalar(h10 * h))
      .add(p1.clone().multiplyScalar(h01))
      .add(this.tangent(i + 1).multiplyScalar(h11 * h));
  }
}

// camera helpers ------------------------------------------------------------------------
// camera basis for a level camera looking along f: right, up (screen), forward
function basis(f) {
  const fw = f.clone().normalize();
  const r = fw.clone().cross(UP).normalize();
  const u = r.clone().cross(fw);
  return { r, u, f: fw };
}

export function toScreen(camPos, look, p) {
  const { r, u, f } = basis(look);
  const d = p.clone().sub(camPos);
  const z = d.dot(f);
  return { x: 0.5 + 0.5 * (d.dot(r) / z) / TAN_H, y: 0.5 - 0.5 * (d.dot(u) / z) / TAN_V, z };
}

// level camera direction that puts world direction `dir` at screen position (sx, sy)
function aim(dir, sx, sy) {
  let yaw = Math.atan2(dir.y, dir.x), pitch = Math.asin(dir.z);
  const fv = (y, p) => v3(Math.cos(p) * Math.cos(y), Math.cos(p) * Math.sin(y), Math.sin(p));
  const scr = (y, p) => { const s = toScreen(v3(0, 0, 0), fv(y, p), dir); return [s.x, s.y]; };
  for (let it = 0; it < 40; it++) {
    const [x0, y0] = scr(yaw, pitch);
    const ex = x0 - sx, ey = y0 - sy;
    if (Math.abs(ex) + Math.abs(ey) < 1e-7) break;
    const e = 1e-4;
    const [xa, ya] = scr(yaw + e, pitch), [xb, yb] = scr(yaw, pitch + e);
    const j = [(xa - x0) / e, (xb - x0) / e, (ya - y0) / e, (yb - y0) / e];
    const det = j[0] * j[3] - j[1] * j[2];
    yaw -= (j[3] * ex - j[1] * ey) / det;
    pitch -= (-j[2] * ex + j[0] * ey) / det;
  }
  return fv(yaw, pitch);
}

// the scene ---------------------------------------------------------------------------
export const HUB = v3(0, 0, 0);
export const U = v3(1, -0.25, 0.1).normalize();            // where the merged ray points
export const DOT = U.clone().multiplyScalar(14);           // the answer: an ordinary dot
const RIGHT = U.clone().cross(UP).normalize();             // camera-right while looking along U
export const SEARCH_LEN = 60;                              // long: their ends stay far out of frame

//            yaw/s  wobble wob-f pitch-amp p-f   phase  strength core px glow px
export const RAYS = [
  { ys: 0.14, wob: 0.35, wf: 0.21, pa: 0.30, pf: 0.17, ph: 0.0, str: 1.00, core: 2.4, glow: 16 },
  { ys: -0.11, wob: 0.40, wf: 0.16, pa: 0.35, pf: 0.23, ph: 1.3, str: 0.70, core: 2.0, glow: 13 },
  { ys: 0.12, wob: 0.30, wf: 0.27, pa: 0.28, pf: 0.14, ph: 2.1, str: 0.55, core: 1.7, glow: 11 },
  { ys: -0.13, wob: 0.35, wf: 0.19, pa: 0.32, pf: 0.21, ph: 0.7, str: 0.42, core: 1.4, glow: 9 },
  { ys: 0.10, wob: 0.30, wf: 0.24, pa: 0.26, pf: 0.28, ph: 2.8, str: 0.32, core: 1.2, glow: 8 },
];
const WIN = 0;                                             // the others merge into this one

function freeAngles(r, t) {
  return [r.y0 + r.ys * t + r.wob * Math.sin(r.wf * t + r.ph), r.p0 + r.pa * Math.sin(r.pf * t + r.ph)];
}
function fromAngles(yaw, pitch) {
  return v3(Math.cos(pitch) * Math.cos(yaw), Math.cos(pitch) * Math.sin(yaw), Math.sin(pitch));
}
RAYS.forEach((r, i) => { r.y0 = i * 2.4 + 0.6; r.p0 = 0.15 * Math.sin(i * 1.7); });  // spread around the hub

// camera route ----------------------------------------------------------------------
// The path (where the camera goes) and the timing (how fast) are separate: positions come from a
// smooth curve through the waypoints, re-parameterised by arc length; each waypoint gets a speed
// and each stretch lasts exactly as long as a straight speed ramp needs, so speed never bulges.
function makeRoute(route) {
  const chord = [0];
  for (let i = 1; i < route.length; i++) chord.push(chord[i - 1] + route[i][0].distanceTo(route[i - 1][0]));
  const geo = new Track(route.map(([p], i) => [chord[i], p]));
  const N_ARC = 4000, total = chord[chord.length - 1];
  const arcC = [], arcS = [0];
  for (let k = 0; k <= N_ARC; k++) arcC.push(total * k / N_ARC);
  for (let k = 1; k <= N_ARC; k++) arcS.push(arcS[k - 1] + geo.at(arcC[k]).distanceTo(geo.at(arcC[k - 1])));
  const sOfC = (c) => {
    const x = c / total * N_ARC, k = Math.min(Math.floor(x), N_ARC - 1);
    return arcS[k] + (arcS[k + 1] - arcS[k]) * (x - k);
  };
  const cOfS = (s) => {
    let lo = 0, hi = N_ARC;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (arcS[m] <= s) lo = m; else hi = m; }
    const k = (s - arcS[lo]) / Math.max(arcS[hi] - arcS[lo], 1e-9);
    return arcC[lo] + k * (arcC[hi] - arcC[lo]);
  };
  const wpS = chord.map(sOfC);
  const wpT = [0];
  for (let i = 1; i < route.length; i++) {
    const v0 = route[i - 1][1], v1 = route[i][1];
    // the final stretch is a pure ease-out (v0 * (1 - x)^2 covers v0 * h / 3): no jolt at rest
    const h = v1 === 0 ? 3 * (wpS[i] - wpS[i - 1]) / v0 : 2 * (wpS[i] - wpS[i - 1]) / (v0 + v1);
    wpT.push(wpT[i - 1] + h);
  }
  const distAt = (t) => {
    if (t >= wpT[wpT.length - 1]) return wpS[wpS.length - 1];
    let i = 0;
    while (wpT[i + 1] <= t) i++;
    const h = wpT[i + 1] - wpT[i], x = (t - wpT[i]) / h, v0 = route[i][1], v1 = route[i + 1][1];
    return (2 * x ** 3 - 3 * x ** 2 + 1) * wpS[i] + (x ** 3 - 2 * x ** 2 + x) * h * v0
      + (-2 * x ** 3 + 3 * x ** 2) * wpS[i + 1] + (x ** 3 - x ** 2) * h * v1;
  };
  return { wpT, at: (t) => geo.at(cOfS(distAt(t))) };
}

const POV_SIDE = AI_MODE ? 1.1 : 0.5, POV_UP = AI_MODE ? 0.7 : 0.35;
const P0 = HUB.clone().addScaledVector(U, -2.4).addScaledVector(UP, POV_UP).addScaledVector(RIGHT, POV_SIDE);
const P0b = P0.clone().addScaledVector(U, 1.3);
const P1 = HUB.clone().addScaledVector(U, 2.8).addScaledVector(UP, AI_MODE ? 0.8 : 0.5).addScaledVector(RIGHT, AI_MODE ? 1.6 : 1.0);
const TO_DOT = U.clone().applyQuaternion(new Quaternion().setFromAxisAngle(UP, 25 * Math.PI / 180))
  .add(v3(0, 0, -0.04)).normalize();
const CF = DOT.clone().addScaledVector(TO_DOT, -11);      // final camera, beside the ray
const FINAL_LOOK = aim(TO_DOT, 0.72, 0.33);               // the dot lands exactly on the hero spot
const orbit = (deg, r, z) => v3(r * Math.cos(deg * Math.PI / 180), r * Math.sin(deg * Math.PI / 180), z);

// Right at the root of the light: the camera floats ~1.7 units from the hub and slowly circles
// it, the rays shooting out past us and off frame. Then it slips in behind the hub for the POV.
//                 waypoint                    speed (units/s)
const ROUTE = [[orbit(-50, 1.9, 0.35), 0.15],             // close on the hub as it ignites
  [orbit(-85, 1.6, 0.5), 0.4],
  [orbit(-125, 1.7, 0.25), 0.45],
  [orbit(-160, 1.8, 0.4), 0.45],
  [P0, 0.6],                                              // behind the hub, on the ray: POV
  [P0b, 0.6],
  [P1, 3.4],                                              // travelling along the ray
  [CF, 0.0]];                                             // eased to rest on the hero frame
export const I_POV = 4;
const R = makeRoute(ROUTE);
const wpT = R.wpT;
const camTrack = { at: R.at };

// key moments follow the camera, so retiming the route keeps the story in sync
export const T_POV = wpT[I_POV];                          // camera is behind the hub
const T_REST = wpT[wpT.length - 1];
export const DURATION = T_REST + 1.8;
const T_MERGE0 = T_POV - 0.6, T_MERGE1 = T_MERGE0 + 1.6;
const T_STRETCH = T_MERGE1;

// Background dots that a ray sweeps across while we watch: placed exactly on a ray's path at a
// moment it is in frame, so each one catches the light and glints for a moment.
const freeDir = (i, t) => fromAngles(...freeAngles(RAYS[i], t));
export const CATCHES = (() => {
  const out = [];
  let seed = 7;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  RAYS.forEach((_, i) => {
    let last = -9;
    for (let t = 2.4 + 0.37 * i; t < T_MERGE0 - 0.5; t += 0.2) {
      if (t - last < 1.8) continue;
      const p = HUB.clone().addScaledVector(freeDir(i, t), 1.3 + rnd() * 6);
      const cam = camTrack.at(t);
      const q = toScreen(cam, HUB.clone().sub(cam), p);
      if (q.z > 0.8 && q.x > 0.06 && q.x < 0.94 && q.y > 0.08 && q.y < 0.92) {
        out.push({ position: p, ray: i, t });
        last = t;
      }
    }
  });
  return out;
})();

// rays are one-sided (they leave the hub), and all swing round to point at the dot
export function rayDir(i, t) {
  const d = fromAngles(...freeAngles(RAYS[i], t));
  return slerpVec(d, U, smoother((t - T_MERGE0) / (T_MERGE1 - T_MERGE0)));
}

function rayState(i, t) {
  const r = RAYS[i];
  const start = 0.5 + 0.35 * i;                              // rays leave the hub one by one
  const grow = SEARCH_LEN * smooth((t - start) / 1.8) ** 1.2;
  const stretch = smoother((t - T_STRETCH) / 1.4);           // reaches out to the dot in POV
  const toDot = grow + (DOT.length() - grow) * stretch;
  const merge = smoother((t - T_MERGE0) / (T_MERGE1 - T_MERGE0));
  const crisp = 0.92 * smoother((t - T_STRETCH - 0.6) / 0.8); // the end turns sharp: it lands
  const flicker = r.str > 0.5 ? 1 : 0.85 + 0.15 * Math.sin(7.3 * t + r.ph) * Math.sin(3.1 * t);
  let k = r.str * flicker * ramp(t, start, start + 0.15, 0, 1);
  k *= i === WIN ? 1 + 0.2 * merge : 1 - 0.85 * merge;      // merged: one strong ray, not a blown-out sum
  return {
    dir: rayDir(i, t),
    lenPos: Math.max(toDot, 0.01), lenNeg: 0.01,           // after the merge they all stretch together
    crispPos: crisp, crispNeg: 0,
    intensity: k, core: r.core, glow: r.glow,
    haze: k * (i === WIN ? 1 : 1 - merge),                   // merged: one haze fan, not five stacked
    taper: 0.85 * smoother((t - wpT[I_POV + 2]) / 2.5),      // leaving the ray: its tail fades towards the hub
  };
}

// camera aim: the hub, floating a little off centre so the rays sweep through the frame; then
// the dot; finally it eases onto the hero framing. Smoothed over time afterwards.
function aimTargets(t, cam) {
  const view = HUB.clone().sub(cam).normalize();
  const side = view.clone().cross(UP).normalize();
  const up = side.clone().cross(view);
  const drift = side.multiplyScalar(0.28 * Math.sin(0.31 * t + 0.4)).addScaledVector(up, 0.18 * Math.sin(0.23 * t + 1.1));
  const toDot = smooth((t - (T_MERGE0 - 0.4)) / 0.8);
  return [{ w: 1 - toDot, p: HUB.clone().add(drift) }, { w: toDot, p: DOT.clone() }];
}

function rawLook(t, cam) {
  const dir = v3(0, 0, 0);
  let focus = 0;
  for (const { w, p } of aimTargets(t, cam)) {
    if (w <= 1e-6) continue;
    dir.addScaledVector(p.clone().sub(cam).normalize(), w);
    focus += w * p.distanceTo(cam);
  }
  dir.normalize();
  const tLeave = wpT[I_POV + 2];                            // leaving the ray for the hero view
  const k = smoother((t - tLeave) / (T_REST - tLeave));
  return { look: slerpVec(dir, FINAL_LOOK, k), focus: focus * (1 - k) + DOT.distanceTo(CF) * k };
}

// precompute camera per frame, with the aim smoothed over ~0.45 s so nothing jerks
const N_FRAMES = Math.round(DURATION * FPS) + 1;
const camAt = [], focusAt = [], rawLooks = [];
for (let f = 0; f < N_FRAMES; f++) {
  const t = f / FPS;
  const c = camTrack.at(t);
  const { look, focus } = rawLook(t, c);
  camAt.push(c); rawLooks.push(look); focusAt.push(focus);
}
const SIGMA = 0.45 * FPS;
const looks = rawLooks.map((_, i) => {
  const acc = v3(0, 0, 0);
  for (let j = -Math.ceil(3 * SIGMA); j <= Math.ceil(3 * SIGMA); j++) {
    const w = Math.exp(-0.5 * (j / SIGMA) ** 2);
    acc.addScaledVector(rawLooks[Math.min(Math.max(i + j, 0), N_FRAMES - 1)], w);
  }
  return acc.normalize();
});

function sampleFrames(arr, t, lerpFn) {
  const x = Math.min(Math.max(t * FPS, 0), N_FRAMES - 1);
  const i = Math.floor(x), j = Math.min(i + 1, N_FRAMES - 1), k = x - i;
  return lerpFn(arr[i], arr[j], k);
}

// how strongly the rays light a point right now, with a short afterglow (the light plays on it)
function catchLight(p, t) {
  let best = 0;
  for (const tau of [0, 0.1, 0.2, 0.32, 0.45, 0.6]) {
    let lit = 0;
    RAYS.forEach((_, i) => {
      const r = rayState(i, t - tau);
      const v = p.clone().sub(HUB);
      const along = v.dot(r.dir);
      if (along <= 0 || along > r.lenPos) return;
      const d = v.addScaledVector(r.dir, -along).length();
      lit += r.intensity * Math.exp(-(d * d) / (0.06 * 0.06 + 0.0004 * along * along));
    });
    best = Math.max(best, lit * Math.exp(-tau / 0.3));
  }
  return Math.min(best, 1.5);
}

// everything the renderer needs at time t
export function stateAt(t) {
  const cam = sampleFrames(camAt, t, (a, b, k) => a.clone().lerp(b, k));
  const look = sampleFrames(looks, t, (a, b, k) => a.clone().lerp(b, k).normalize());
  const focus = sampleFrames(focusAt, t, (a, b, k) => a + (b - a) * k);
  return {
    t,
    camera: { position: cam, target: cam.clone().add(look), focus,
      // shallow depth of field while visiting rays (the others soften), deeper at the end
      coc: 18 + ramp(t, T_MERGE0, T_STRETCH + 1, 0, 7) },
    hub: {
      position: HUB,
      intensity: ramp(t, 0.0, 0.25, 0, 3.2) - ramp(t, 0.25, 1.2, 0, 1.8),
      size: ramp(t, 0.0, 0.25, 0, 260) - ramp(t, 0.25, 1.2, 0, 120),
    },
    rays: RAYS.map((_, i) => rayState(i, t)),
    catches: CATCHES.map((c) => ({ position: c.position, intensity: catchLight(c.position, t) })),
    dot: {     // an ordinary dot until the ray lands on it
      position: DOT,
      intensity: 0.25 + ramp(t, T_STRETCH + 1.2, T_STRETCH + 1.8, 0, 2.2),
      size: 6 + ramp(t, T_STRETCH + 1.2, T_STRETCH + 1.8, 0, 190),
    },
  };
}

// for checks
export const debug = { camAt, looks, focusAt, CF, FINAL_LOOK, DOT, HUB, N_FRAMES, wpT, CATCHES };
