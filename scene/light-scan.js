// "The Answer": WebGL renderer for the choreography in choreo.js.
// Everything glows additively into a float buffer, then bloom, tone mapping and grain.

import * as THREE from 'three';
import { EffectComposer } from './vendor/three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from './vendor/three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from './vendor/three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from './vendor/three/addons/postprocessing/OutputPass.js';
import { ShaderPass } from './vendor/three/addons/postprocessing/ShaderPass.js';
import * as C from './choreo.js';

// look -------------------------------------------------------------------------------
const LOOK = {
  rayColor: new THREE.Color(1.0, 1.0, 1.0),
  hazeColor: new THREE.Color(0.42, 0.46, 0.95),   // blue-violet
  hazeStrength: 0.05,
  hazeAngle: 10 * Math.PI / 180,
  dotBrightness: 0.55,
  bloom: { strength: 0.6, radius: 0.5, threshold: 0.15 },
  grain: 0.035,
};

function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// screen-space ribbon: a line of constant pixel width (crisp core + soft glow) whose width
// grows and dims with defocus.
const RIBBON_VERT_COMMON = /* glsl */`
  uniform vec2 uRes;
  uniform float uCocK, uFocus;
  varying float vAcross, vCore, vGlow, vEnergy, vFade;

  // places a vertex of a line (origin + dir * len) on screen, offset sideways by side * width
  void ribbon(vec3 origin, vec3 dir, float len, float minLen, float maxLen, float side,
              float core, float glow, float fade) {
    vec3 oV = (viewMatrix * vec4(origin, 1.0)).xyz;
    vec3 dV = (viewMatrix * vec4(dir, 0.0)).xyz;
    float zNear = -0.08;
    float ok = 1.0;
    // the part of the line behind the camera is clamped to the near plane (or dropped)
    if (oV.z + dV.z * len > zNear) {
      if (abs(dV.z) > 1e-5) {
        float x = (zNear - oV.z) / dV.z;
        if (x < minLen || x > maxLen) ok = 0.0;
        len = clamp(x, minLen, maxLen);
      } else ok = 0.0;
    }
    vec3 P = origin + dir * len;
    vec4 c = projectionMatrix * viewMatrix * vec4(P, 1.0);
    vec4 dc = projectionMatrix * viewMatrix * vec4(dir, 0.0);
    vec2 sdir = (dc.xy * c.w - c.xy * dc.w) * uRes;
    sdir = length(sdir) > 1e-6 ? normalize(sdir) : vec2(1.0, 0.0);
    vec2 n = vec2(-sdir.y, sdir.x);
    float z = max(c.w, 0.08);
    float coc = uCocK * abs(1.0 / z - 1.0 / uFocus);
    float hw = core + glow + coc;
    c.xy += n * side * hw / uRes * 2.0 * c.w;
    gl_Position = c;
    vAcross = side * hw;
    vCore = core + 0.5 * coc;
    vGlow = glow + coc;
    vEnergy = core / (core + coc);
    vFade = fade * ok * smoothstep(0.15, 0.6, z);   // never smear across the lens
  }
`;

const RIBBON_FRAG = /* glsl */`
  uniform vec3 uColor;
  uniform float uIntensity;
  varying float vAcross, vCore, vGlow, vEnergy, vFade;
  void main() {
    float d = abs(vAcross);
    float core = exp(-1.6 * (d / vCore) * (d / vCore));
    float glow = 0.22 * exp(-2.2 * (d / vGlow) * (d / vGlow));
    float a = (core * vEnergy * 2.2 + glow) * vFade * uIntensity;
    gl_FragColor = vec4(uColor * a, 1.0);
  }
`;

function ribbonGeometry(segments, twoSided, extra = null) {
  const s = [], side = [], idx = [];
  for (let i = 0; i <= segments; i++) {
    const t = twoSided ? -1 + 2 * i / segments : i / segments;
    s.push(t, t); side.push(-1, 1);
    if (i < segments) { const a = 2 * i; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(new Array(s.length * 3).fill(0), 3));
  g.setAttribute('aS', new THREE.Float32BufferAttribute(s, 1));
  g.setAttribute('aSide', new THREE.Float32BufferAttribute(side, 1));
  g.setIndex(idx);
  return g;
}

function additive(params) {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, depthTest: false,
    blending: THREE.AdditiveBlending, side: THREE.DoubleSide, ...params,
  });
}

export function createLightScan(canvas) {
  const W = C.WIDTH, H = C.HEIGHT;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(W, H, false);
  renderer.toneMapping = THREE.AgXToneMapping;
  renderer.toneMappingExposure = 1.0;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0, 0, 0);
  const camera = new THREE.PerspectiveCamera(C.VFOV_DEG, W / H, 0.05, 500);
  camera.up.set(0, 0, 1);

  const common = {
    uRes: { value: new THREE.Vector2(W, H) },
    uCocK: { value: 50 },
    uFocus: { value: 10 },
  };

  // dots: tiny, dim, mostly on dotted orbital arcs around the hub, plus loose dust ----------
  const rand = mulberry32(11);
  const pos = [], axis = [], speed = [], size = [], bright = [];
  const pushDot = (p, ax, sp, sz, br) => { pos.push(p.x, p.y, p.z); axis.push(ax.x, ax.y, ax.z); speed.push(sp); size.push(sz); bright.push(br); };
  for (let r = 0; r < 16; r++) {
    const radius = 2.2 + r * 0.6 + rand() * 0.4;
    // orbits tilted towards where the camera starts, so they read as loops, not edge-on lines
    const n = new THREE.Vector3(-0.35 + (rand() - 0.5) * 1.2, -0.85 + (rand() - 0.5) * 0.8, 0.5 + (rand() - 0.5) * 0.8).normalize();
    const a = new THREE.Vector3().crossVectors(n, new THREE.Vector3(1, 0, 0)).normalize();
    const b = new THREE.Vector3().crossVectors(n, a);
    const wobA = 0.06 + rand() * 0.1, wobF = 2 + Math.floor(rand() * 4), wobP = rand() * 6.28;
    const count = Math.floor(radius * 95);
    const sp = (0.015 + rand() * 0.02) * (rand() < 0.5 ? -1 : 1);
    for (let i = 0; i < count; i++) {
      const th = rand() * Math.PI * 2;
      const rr = radius * (1 + wobA * Math.sin(wobF * th + wobP)) + (rand() - 0.5) * 0.12;
      const p = a.clone().multiplyScalar(Math.cos(th) * rr).addScaledVector(b, Math.sin(th) * rr)
        .addScaledVector(n, (rand() - 0.5) * 0.12 + 0.25 * Math.sin(3 * th + wobP));
      pushDot(p, n, sp, 1.1 + rand() * 0.9, 0.5 + rand() * 0.7);
    }
  }
  for (let i = 0; i < 5000; i++) {
    const p = new THREE.Vector3(rand() - 0.5, rand() - 0.5, rand() - 0.5).multiplyScalar(60);
    if (p.length() < 1.0 || p.distanceTo(C.DOT) < 0.8) continue;
    pushDot(p, new THREE.Vector3(0, 0, 1), 0.004 * (rand() - 0.5), 0.9 + rand() * 1.1, 0.3 + rand() * 0.9);
  }
  const dotGeo = new THREE.BufferGeometry();
  dotGeo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  dotGeo.setAttribute('aAxis', new THREE.Float32BufferAttribute(axis, 3));
  dotGeo.setAttribute('aSpeed', new THREE.Float32BufferAttribute(speed, 1));
  dotGeo.setAttribute('aSize', new THREE.Float32BufferAttribute(size, 1));
  dotGeo.setAttribute('aBright', new THREE.Float32BufferAttribute(bright, 1));
  const N_RAYS = C.RAYS.length;
  const dotUniforms = {
    ...common,
    uTime: { value: 0 },
    uBrightness: { value: LOOK.dotBrightness },
    uHub: { value: C.HUB.clone() },
    uRayDir: { value: Array.from({ length: N_RAYS }, () => new THREE.Vector3(1, 0, 0)) },
    uRayLenP: { value: new Array(N_RAYS).fill(0) },
    uRayLenN: { value: new Array(N_RAYS).fill(0) },
    uRayStr: { value: new Array(N_RAYS).fill(0) },
  };
  const dots = new THREE.Points(dotGeo, additive({
    uniforms: dotUniforms,
    vertexShader: /* glsl */`
      #define N ${N_RAYS}
      attribute vec3 aAxis; attribute float aSpeed, aSize, aBright;
      uniform float uTime, uCocK, uFocus, uBrightness;
      uniform vec3 uHub; uniform vec3 uRayDir[N]; uniform float uRayLenP[N], uRayLenN[N], uRayStr[N];
      varying float vB;
      vec3 rot(vec3 p, vec3 k, float a) { return p * cos(a) + cross(k, p) * sin(a) + k * dot(k, p) * (1.0 - cos(a)); }
      void main() {
        vec3 p = rot(position, aAxis, aSpeed * uTime);          // slow orbital drift
        vec4 mv = viewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mv;
        float z = -mv.z;
        float coc = uCocK * abs(1.0 / max(z, 0.05) - 1.0 / uFocus);
        float s = aSize + coc;
        float lit = 0.0;                                         // dots catch the rays' light
        for (int i = 0; i < N; i++) {
          vec3 v = p - uHub;
          float along = dot(v, uRayDir[i]);
          float lim = along >= 0.0 ? uRayLenP[i] : uRayLenN[i];
          float r = length(v - along * uRayDir[i]);
          lit += uRayStr[i] * exp(-r * r / 0.05) * clamp(1.0 - abs(along) / max(lim, 0.01), 0.0, 1.0);
        }
        vB = uBrightness * aBright * (1.0 + 7.0 * lit) * (aSize * aSize) / (s * s);
        gl_PointSize = z > 0.05 ? s : 0.0;
      }`,
    fragmentShader: /* glsl */`
      varying float vB;
      void main() {
        float d = length(gl_PointCoord - 0.5) * 2.0;
        gl_FragColor = vec4(vec3(0.85, 0.88, 1.0) * vB * smoothstep(1.0, 0.55, d), 1.0);
      }`,
  }));
  dots.frustumCulled = false;
  scene.add(dots);

  // rays --------------------------------------------------------------------------------
  const rayMeshes = C.RAYS.map(() => {
    const m = new THREE.Mesh(ribbonGeometry(240, true), additive({
      uniforms: {
        ...common,
        uOrigin: { value: C.HUB.clone() }, uDir: { value: new THREE.Vector3(1, 0, 0) },
        uLenPos: { value: 1 }, uLenNeg: { value: 1 }, uCrispPos: { value: 0 }, uCrispNeg: { value: 0 }, uTaper: { value: 0 },
        uCoreW: { value: 2 }, uGlowW: { value: 20 }, uColor: { value: LOOK.rayColor }, uIntensity: { value: 0 },
      },
      vertexShader: /* glsl */`
        attribute float aS; attribute float aSide;
        uniform vec3 uOrigin, uDir; uniform float uLenPos, uLenNeg, uCrispPos, uCrispNeg, uCoreW, uGlowW, uTaper;
        ${RIBBON_VERT_COMMON}
        void main() {
          float len = aS >= 0.0 ? aS * uLenPos : aS * uLenNeg;
          float u = aS >= 0.0 ? aS : -aS;
          float crisp = aS >= 0.0 ? uCrispPos : uCrispNeg;
          float fade = 1.0 - smoothstep(crisp, 1.0, u);          // crisp ~1: a sharp end (it lands)
          if (crisp > 0.0) fade *= 1.0 - uTaper * (1.0 - u);      // a tail that fades away from the dot
          ribbon(uOrigin, uDir, len, -uLenNeg, uLenPos, aSide, uCoreW, uGlowW, fade);
        }`,
      fragmentShader: RIBBON_FRAG,
    }));
    m.frustumCulled = false;
    scene.add(m);
    return m;
  });

  // star glints: the hub and, once found, the dot ------------------------------------------------
  const starMat = () => additive({
    uniforms: { uSize: { value: 0 }, uIntensity: { value: 0 } },
    vertexShader: /* glsl */`
      uniform float uSize;
      void main() {
        vec4 mv = viewMatrix * modelMatrix * vec4(0.0, 0.0, 0.0, 1.0);
        gl_Position = projectionMatrix * mv;
        gl_PointSize = -mv.z > 0.05 ? uSize : 0.0;
      }`,
    fragmentShader: /* glsl */`
      uniform float uSize, uIntensity;
      void main() {
        vec2 p = (gl_PointCoord - 0.5) * uSize;              // pixels from the centre
        float r = length(p);
        float a = 3.0 * exp(-r * r / 9.0) + 0.5 * exp(-r / (0.07 * uSize));
        for (int k = 0; k < 3; k++) {                        // six-point glint, two arms longer
          float th = 0.31 + float(k) * 1.0472;
          vec2 e = vec2(cos(th), sin(th));
          float along = abs(dot(p, e)), across = abs(dot(p, vec2(-e.y, e.x)));
          float L = (k == 0 ? 0.22 : 0.14) * uSize;
          a += exp(-across * across / 1.6) * exp(-along / L) * 1.1;
        }
        a *= smoothstep(0.5 * uSize, 0.3 * uSize, r);
        gl_FragColor = vec4(vec3(0.95, 0.96, 1.0) * a * uIntensity, 1.0);
      }`,
  });
  const makeStar = (p) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0], 3));
    const s = new THREE.Points(g, starMat());
    s.position.copy(p);
    s.frustumCulled = false;
    scene.add(s);
    return s;
  };
  const hubStar = makeStar(C.HUB);
  const dotStar = makeStar(C.DOT);

  // background dots that a ray sweeps across: a plain dot that glints while the light plays on it
  const catchGeo = new THREE.BufferGeometry();
  catchGeo.setAttribute('position', new THREE.Float32BufferAttribute(C.CATCHES.flatMap((c) => [c.position.x, c.position.y, c.position.z]), 3));
  const catchLit = new Float32Array(C.CATCHES.length);
  catchGeo.setAttribute('aLit', new THREE.BufferAttribute(catchLit, 1));
  const catches = new THREE.Points(catchGeo, additive({
    vertexShader: /* glsl */`
      attribute float aLit; varying float vLit; varying float vSize;
      void main() {
        vec4 mv = viewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mv;
        vLit = aLit;
        vSize = 6.0 + 90.0 * aLit;
        gl_PointSize = -mv.z > 0.05 ? vSize : 0.0;
      }`,
    fragmentShader: /* glsl */`
      varying float vLit; varying float vSize;
      void main() {
        vec2 p = (gl_PointCoord - 0.5) * vSize;
        float r = length(p);
        float a = (0.35 + 2.5 * vLit) * exp(-r * r / 2.5) + 0.4 * vLit * exp(-r / (0.08 * vSize));
        for (int k = 0; k < 2; k++) {                        // a small four-point glint
          float th = 0.5 + float(k) * 1.5708;
          vec2 e = vec2(cos(th), sin(th));
          a += vLit * exp(-pow(dot(p, vec2(-e.y, e.x)), 2.0) / 1.2) * exp(-abs(dot(p, e)) / (0.18 * vSize));
        }
        a *= smoothstep(0.5 * vSize, 0.3 * vSize, r);
        gl_FragColor = vec4(vec3(0.9, 0.93, 1.0) * a, 1.0);
      }`,
  }));
  catches.frustumCulled = false;
  scene.add(catches);

  // haze: a soft blue-violet volume fanning out along each ray, ray-marched at half size ------
  const hazeRT = new THREE.WebGLRenderTarget(W / 2, H / 2, { type: THREE.HalfFloatType });
  const quad = new THREE.PlaneGeometry(2, 2);
  const orthoCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const hazeUniforms = {
    uInvVP: { value: new THREE.Matrix4() }, uCam: { value: new THREE.Vector3() },
    uHub: { value: C.HUB.clone() },
    uRayDir: { value: Array.from({ length: N_RAYS }, () => new THREE.Vector3(1, 0, 0)) },
    uRayLen: { value: new Array(N_RAYS).fill(1) },
    uRayStr: { value: new Array(N_RAYS).fill(0) },
    uTan: { value: Math.tan(LOOK.hazeAngle) },
    uColor: { value: LOOK.hazeColor }, uStrength: { value: LOOK.hazeStrength },
  };
  const hazeScene = new THREE.Scene();
  const hazeQuad = new THREE.Mesh(quad, new THREE.ShaderMaterial({
    uniforms: hazeUniforms, depthTest: false, depthWrite: false,
    vertexShader: 'varying vec2 vNdc; void main() { vNdc = position.xy; gl_Position = vec4(position.xy, 0.0, 1.0); }',
    fragmentShader: /* glsl */`
      #define N ${N_RAYS}
      uniform mat4 uInvVP; uniform vec3 uCam, uHub, uColor;
      uniform vec3 uRayDir[N]; uniform float uRayLen[N], uRayStr[N], uTan, uStrength;
      varying vec2 vNdc;
      float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
      void main() {
        vec4 far = uInvVP * vec4(vNdc, 1.0, 1.0);
        vec3 rd = normalize(far.xyz / far.w - uCam);
        float acc = 0.0;
        float jit = hash(gl_FragCoord.xy);
        const int STEPS = 40;
        float prev = 0.15;
        for (int s = 1; s <= STEPS; s++) {
          float x = (float(s) - jit) / float(STEPS);
          float t = 0.15 + 34.0 * x * x;                        // denser close to the camera
          float dt = t - prev; prev = t;
          vec3 p = uCam + rd * t;
          float nearCam = smoothstep(0.6, 3.0, t);              // no fog right at the lens
          for (int i = 0; i < N; i++) {
            vec3 v = p - uHub;
            float z = dot(v, uRayDir[i]);
            if (z <= 0.0) continue;                             // fans out one way only
            float r = length(v - z * uRayDir[i]);
            float w = 0.06 + z * uTan;
            float L = uRayLen[i];
            // seen side-on the fan glows; looking straight down its axis it would pile up, so fade that
            float side = pow(length(cross(rd, uRayDir[i])), 1.5);
            acc += nearCam * uRayStr[i] * side * exp(-(r * r) / (w * w)) * smoothstep(0.0, 0.8, z)
                   * (1.0 - smoothstep(0.3 * L, L, z)) / (1.0 + 0.6 * w) * dt;
          }
        }
        gl_FragColor = vec4(uColor * min(acc * uStrength, 1.2), 1.0);
      }`,
  }));
  hazeScene.add(hazeQuad);
  const hazeComposite = new THREE.Mesh(quad, additive({
    uniforms: { tHaze: { value: hazeRT.texture } },
    vertexShader: 'varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
    fragmentShader: 'uniform sampler2D tHaze; varying vec2 vUv; void main() { gl_FragColor = vec4(texture2D(tHaze, vUv).rgb, 1.0); }',
  }));
  hazeComposite.frustumCulled = false;
  hazeComposite.renderOrder = -1;
  scene.add(hazeComposite);

  // post: bloom, tone mapping, grain + a touch of vignette ----------------------------------
  const composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType }));
  composer.setPixelRatio(1);
  composer.setSize(W, H);
  composer.addPass(new RenderPass(scene, camera));
  composer.addPass(new UnrealBloomPass(new THREE.Vector2(W, H), LOOK.bloom.strength, LOOK.bloom.radius, LOOK.bloom.threshold));
  composer.addPass(new OutputPass());
  const grain = new ShaderPass({
    uniforms: { tDiffuse: { value: null }, uTime: { value: 0 }, uAmount: { value: LOOK.grain } },
    vertexShader: 'varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: /* glsl */`
      uniform sampler2D tDiffuse; uniform float uTime, uAmount; varying vec2 vUv;
      float hash(vec3 p) { return fract(sin(dot(p, vec3(12.9898, 78.233, 37.719))) * 43758.5453); }
      void main() {
        vec3 c = texture2D(tDiffuse, vUv).rgb;
        float g = hash(vec3(gl_FragCoord.xy, floor(uTime * 24.0))) - 0.5;
        float vig = smoothstep(1.25, 0.35, length(vUv - 0.5) * 1.6);
        gl_FragColor = vec4(c * mix(0.75, 1.0, vig) + g * uAmount, 1.0);
      }`,
  });
  composer.addPass(grain);

  // per frame ---------------------------------------------------------------------------
  const vp = new THREE.Matrix4();
  function renderAt(t) {
    const st = C.stateAt(t);
    camera.position.copy(st.camera.position);
    camera.lookAt(st.camera.target);
    camera.updateMatrixWorld();
    common.uFocus.value = st.camera.focus;
    common.uCocK.value = st.camera.coc;

    st.rays.forEach((r, i) => {
      const u = rayMeshes[i].material.uniforms;
      u.uDir.value.copy(r.dir);
      u.uLenPos.value = r.lenPos; u.uLenNeg.value = r.lenNeg;
      u.uCrispPos.value = r.crispPos; u.uCrispNeg.value = r.crispNeg; u.uTaper.value = r.taper;
      u.uCoreW.value = r.core; u.uGlowW.value = r.glow; u.uIntensity.value = r.intensity;
      dotUniforms.uRayDir.value[i].copy(r.dir);
      dotUniforms.uRayLenP.value[i] = r.lenPos; dotUniforms.uRayLenN.value[i] = r.lenNeg;
      dotUniforms.uRayStr.value[i] = r.intensity;
      // the haze fans out along each ray's longer half (towards the dot once merged)
      const fwd = r.lenPos >= r.lenNeg;
      hazeUniforms.uRayDir.value[i].copy(r.dir).multiplyScalar(fwd ? 1 : -1);
      hazeUniforms.uRayLen.value[i] = fwd ? r.lenPos : r.lenNeg;
      hazeUniforms.uRayStr.value[i] = r.haze;
    });
    dotUniforms.uTime.value = t;
    hubStar.material.uniforms.uSize.value = st.hub.size;
    hubStar.material.uniforms.uIntensity.value = st.hub.intensity;
    dotStar.material.uniforms.uSize.value = st.dot.size;
    dotStar.material.uniforms.uIntensity.value = st.dot.intensity;
    st.catches.forEach((c, i) => { catchLit[i] = c.intensity; });
    catchGeo.attributes.aLit.needsUpdate = true;
    grain.uniforms.uTime.value = t;

    vp.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    hazeUniforms.uInvVP.value.copy(vp).invert();
    hazeUniforms.uCam.value.copy(camera.position);
    renderer.setRenderTarget(hazeRT);
    renderer.render(hazeScene, orthoCam);
    renderer.setRenderTarget(null);
    composer.render();
  }

  return { renderAt, duration: C.DURATION, fps: C.FPS, width: W, height: H };
}
