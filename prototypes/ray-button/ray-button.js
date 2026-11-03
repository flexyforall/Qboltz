/* Ray button — a light ray flies through the button and flashes behind the text.
 *
 * Geometry comes from the three Figma frames of "Button - hover-animation"
 * (968:948 → 968:977 → 968:1005). The ray moves along s:
 *   s = 0   frame 1 (ray enters from the left)
 *   s = 0.5 frame 2 (flash behind the text, text turns dark)
 *   s = 1   frame 3 (ray leaves on the right)
 *
 * Usage: <a class="ray-btn" data-ray-button> … </a>  (markup in index.html)
 *   data-ray-mode="hover" (default) — one pass on every hover / focus
 *   data-ray-mode="loop"            — passes by itself every data-ray-interval ms
 *
 * Every button also exposes el.rayButton.play(), .seek(s, fade) and .renderAt(ms).
 */
(function () {
  "use strict";

  // Figma values for frame 1/3 (no flash) and frame 2 (flash)
  var F1 = { cx: 653.7165, cy: 363.264 };                 // ray centre, bg coordinates
  var F3 = { cx: 12.7365, cy: 458.424 };
  var FLASH_OFFSET = { x: 15.98, y: -1.29 };              // frame 2 sits slightly off the straight path
  var SHAPE = {
    w: [609.71, 1012.655],                                // blurred ellipse short axis (vertical)
    maskW: [1416.816, 1417.734],                          // flare image size
    maskH: [414.33, 691.252],
    opacity: [0.6, 1]
  };

  // the ray path is given in the rotated "bg" frame; this maps it onto the button
  var STAGE_C = { x: -861 + 1471.727 / 2, y: -380 + 795.076 / 2 };
  var BG_C = { x: 700, y: 300 };
  var BG_ROT = 171.73 * Math.PI / 180;
  var COS = Math.cos(BG_ROT), SIN = Math.sin(BG_ROT);

  var TRAVEL_MS = 1300;   // frame 1 → frame 3
  var RESET_MS = 500;     // fade back to frame 1

  function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function easeInOut(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
  function smooth(t) { return t * t * (3 - 2 * t); }

  // flash strength: 0 at frames 1/3, 1 at frame 2
  function flashAt(s) { return smooth(clamp01(1 - Math.abs(s - 0.5) / 0.5)); }

  function bgToButton(x, y) {
    var vx = x - BG_C.x, vy = -(y - BG_C.y); // scaleY(-1)
    return {
      x: STAGE_C.x + vx * COS - vy * SIN,
      y: STAGE_C.y + vx * SIN + vy * COS
    };
  }

  function RayButton(el) {
    this.el = el;
    this.ray = el.querySelector(".ray-btn__ray");
    this.ellipse = el.querySelector(".ray-btn__ellipse");
    this.dark = el.querySelector(".ray-btn__content--dark");
    this.mode = el.getAttribute("data-ray-mode") || "hover";
    this.interval = parseInt(el.getAttribute("data-ray-interval"), 10) || 3500;
    this.playing = false;
    this.raf = 0;

    this.reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    var self = this;
    if (this.mode === "loop") {
      this.timer = setInterval(function () { self.play(); }, this.interval);
    } else {
      el.addEventListener("mouseenter", function () { self.play(); });
      el.addEventListener("focus", function () { self.play(); });
    }
    this.seek(0, 1);
  }

  // s: position along the path, fade: overall ray opacity multiplier
  RayButton.prototype.seek = function (s, fade) {
    if (fade === undefined) fade = 1;
    var g = flashAt(s);

    // centre of the flare on the button (fitted to the frames: frame 3 sits at
    // 85% of the frame-1 → frame-3 offset Figma reports)
    var k = s <= 0.5 ? s : 0.5 + (s - 0.5) * 0.7;
    var p = bgToButton(
      lerp(F1.cx, F3.cx, k) + FLASH_OFFSET.x * g,
      lerp(F1.cy, F3.cy, k) + FLASH_OFFSET.y * g
    );
    var mw = lerp(SHAPE.maskW[0], SHAPE.maskW[1], g);
    var mh = lerp(SHAPE.maskH[0], SHAPE.maskH[1], g);

    var r = this.ray.style;
    r.width = mw.toFixed(2) + "px";
    r.height = mh.toFixed(2) + "px";
    r.transform = "translate(" + (p.x - mw / 2).toFixed(2) + "px," + (p.y - mh / 2).toFixed(2) + "px)";
    r.opacity = (lerp(SHAPE.opacity[0], SHAPE.opacity[1], g) * fade).toFixed(3);
    this.ellipse.style.height = lerp(SHAPE.w[0], SHAPE.w[1], g).toFixed(2) + "px";

    // dark text: only where the flash is, and only as strong as the flash
    var fx = p.x - 110; // into the content box (content starts at x 110)
    var d = this.dark.style;
    d.opacity = (g * fade).toFixed(3);
    var mask = "linear-gradient(90deg, transparent " + (fx - 230).toFixed(1) + "px, #000 " + (fx - 110).toFixed(1) +
      "px, #000 " + (fx + 110).toFixed(1) + "px, transparent " + (fx + 230).toFixed(1) + "px)";
    d.webkitMaskImage = d.maskImage = mask;
  };

  // Timeline of one pass, t in ms. Returns false when the pass is over.
  RayButton.prototype.renderAt = function (t) {
    if (t < TRAVEL_MS) {
      this.seek(easeInOut(t / TRAVEL_MS), 1);
    } else if (t < TRAVEL_MS + RESET_MS) {
      // fade out at frame 3, fade back in at frame 1
      var u = (t - TRAVEL_MS) / RESET_MS;
      if (u < 0.5) this.seek(1, 1 - smooth(u * 2));
      else this.seek(0, smooth(u * 2 - 1));
    } else {
      this.seek(0, 1);
      return false;
    }
    return true;
  };

  RayButton.prototype.play = function () {
    if (this.playing || this.reduced) return;
    this.playing = true;
    var self = this, start = performance.now();
    function tick(now) {
      if (self.renderAt(now - start)) self.raf = requestAnimationFrame(tick);
      else self.playing = false;
    }
    this.raf = requestAnimationFrame(tick);
  };

  function init(root) {
    (root || document).querySelectorAll("[data-ray-button]").forEach(function (el) {
      if (!el.rayButton) el.rayButton = new RayButton(el);
    });
  }

  window.RayButton = { init: init, DURATION: TRAVEL_MS + RESET_MS };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { init(); });
  else init();
})();
