/* Qboltz landing — intro video + scroll-driven storyboard
   Keyframes map 1:1 to the Figma frames of "Concept UI" (769:217):
   f2 hero (769:689) → f3 header + card (769:218) → f4 card leaves (769:275)
   → f5 (769:325) → f6 (769:376) → f7 (769:428) → f8 (769:480).
   Positions are in viewport heights of scroll. */
(function () {
  "use strict";

  var DESIGN_W = 1440;
  var DESIGN_H = 800;

  var P = {
    f2: 0,
    f3: 0.6,
    f4: 1.4,
    f5: 2.4,
    f5h: 3.4,
    f6: 4.2,
    f6h: 5.2,
    f7: 6.0,
    f7h: 7.0,
    f8: 7.8,
    f8h: 8.6,
    end: 9.0
  };
  var M56 = (P.f5h + P.f6) / 2;
  var M67 = (P.f6h + P.f7) / 2;
  var M78 = (P.f7h + P.f8) / 2;

  var root = document.documentElement;
  var body = document.body;
  var story = document.querySelector(".story");
  var hero = document.querySelector(".hero");
  var video = document.querySelector(".hero__video");
  var header = document.querySelector(".header-wrap");
  var loader = document.querySelector(".loader");
  var loaderNum = document.querySelector(".loader__num");
  var loaderLines = document.querySelectorAll(".loader__line");
  var brackets = document.querySelector(".frame-brackets");
  var grain = document.querySelector(".bg__grain");
  var bg5 = document.querySelector(".bg__layer--f5");
  var bg6 = document.querySelector(".bg__layer--f6");
  var bg7 = document.querySelector(".bg__layer--f7");
  var bg8 = document.querySelector(".bg__layer--f8");
  var s1 = document.querySelector(".scene--1");
  var s1flat = s1.querySelector(".scene__text--flat");
  var s1grad = s1.querySelector(".grad-text");
  var s2 = document.querySelector(".scene--2");
  var s3 = document.querySelector(".scene--3");
  var sFinal = document.querySelector(".scene--final");
  var sFinalTitle = sFinal.querySelector(".final__title");

  var k = 1;
  var vh = window.innerHeight;
  var ticking = false;
  var lastNum = "";
  var pausedByScroll = false;

  function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
  function ease(v) { return v * v * (3 - 2 * v); } // smoothstep
  function ramp(p, a, b) { return ease(clamp01((p - a) / (b - a))); }
  function lerp(a, b, t) { return a + (b - a) * t; }

  /* ---------- sizing ---------- */

  function measure() {
    var w = window.innerWidth;
    vh = window.innerHeight;
    k = Math.min(w / DESIGN_W, vh / DESIGN_H);
    root.style.setProperty("--k", k.toFixed(5));
    // gradient layers are 1894 wide — stretch them horizontally on ultra-wide screens
    root.style.setProperty("--bgx", Math.max(1, w / (1894 * k)).toFixed(5));
    story.style.height = Math.round((P.end + 1) * vh) + "px";
  }

  /* ---------- intro video ---------- */

  // Scrolling during the intro skips to the flare (the hero frame is designed on it)
  var FLARE_LEAD = 1.6;
  function skipIntro() {
    if (body.classList.contains("is-revealed")) return;
    if (isFinite(video.duration) && video.currentTime < video.duration - FLARE_LEAD) {
      video.currentTime = video.duration - FLARE_LEAD;
    }
    reveal();
  }

  function reveal() {
    if (body.classList.contains("is-revealed")) return;
    body.classList.remove("is-intro");
    body.classList.add("is-revealed");
  }

  function showLastFrame() {
    if (isFinite(video.duration) && video.duration > 0) {
      video.currentTime = Math.max(0, video.duration - 0.05);
    }
    reveal();
  }

  video.addEventListener("timeupdate", function () {
    if (isFinite(video.duration) && video.currentTime >= video.duration - 1.0) reveal();
  });
  video.addEventListener("ended", reveal);
  video.addEventListener("error", reveal);

  var playAttempt = video.play && video.play();
  if (playAttempt && typeof playAttempt.catch === "function") {
    playAttempt.catch(function () {
      // Autoplay blocked — jump to the final (flare) frame that the hero is designed on.
      if (video.readyState >= 1) showLastFrame();
      else video.addEventListener("loadedmetadata", showLastFrame, { once: true });
    });
  }

  /* ---------- text reveal on scroll (drone.riotters.com style) ----------
     Each glyph becomes its own span; it goes from a dim state to the full
     Figma gradient as the scroll front passes it. background-clip:text does
     not survive opacity on child spans, so every span gets the paragraph's
     gradient, sized to the paragraph and shifted by the span's offset. */

  var REVEAL_DIM = 0.16;
  var REVEAL_SPREAD = 10; // glyphs in the soft front

  function Reveal(el) {
    this.el = el;
    this.bg = getComputedStyle(el).backgroundImage;
    this.chars = [];
    this.last = -1;
    var self = this;
    var nodes = Array.prototype.slice.call(el.childNodes);
    el.textContent = "";
    nodes.forEach(function (node) {
      if (node.nodeType !== 3) { el.appendChild(node); return; }
      var text = node.nodeValue;
      for (var i = 0; i < text.length; i++) {
        var ch = text[i];
        if (ch === " ") { el.appendChild(document.createTextNode(" ")); continue; }
        var span = document.createElement("span");
        span.className = "rv";
        span.textContent = ch;
        span.style.backgroundImage = self.bg;
        el.appendChild(span);
        self.chars.push(span);
      }
    });
    el.classList.add("is-split");
    el.setAttribute("aria-label", el.textContent);
  }

  Reveal.prototype.layout = function () {
    var w = this.el.offsetWidth, h = this.el.offsetHeight;
    this.chars.forEach(function (span) {
      span.style.backgroundSize = w + "px " + h + "px";
      span.style.backgroundPosition = -span.offsetLeft + "px " + -span.offsetTop + "px";
    });
  };

  Reveal.prototype.set = function (r) {
    r = Math.round(r * 1000) / 1000;
    if (r === this.last) return;
    this.last = r;
    var front = r * (this.chars.length + REVEAL_SPREAD);
    for (var i = 0; i < this.chars.length; i++) {
      var v = clamp01((front - i) / REVEAL_SPREAD);
      this.chars[i].style.opacity = (REVEAL_DIM + (1 - REVEAL_DIM) * v).toFixed(3);
    }
  };

  var reveals = [
    { r: new Reveal(s1grad), from: P.f5 - 0.4, to: P.f5h - 0.15 },
    { r: new Reveal(s2.querySelector(".grad-text")), from: P.f6 - 0.3, to: P.f6h - 0.15 },
    { r: new Reveal(s3.querySelector(".grad-text")), from: P.f7 - 0.3, to: P.f7h - 0.15 },
    { r: new Reveal(sFinalTitle), from: P.f8 - 0.3, to: P.f8h }
  ];

  function layoutReveals() {
    reveals.forEach(function (x) { x.r.layout(); });
  }

  /* ---------- hover text roll (izum.study style) ----------
     Letters slide up one after another while their copies roll in from below. */

  document.querySelectorAll("[data-roll]").forEach(function (el) {
    var text = el.textContent;
    var roll = document.createElement("span");
    roll.className = "roll";
    roll.setAttribute("aria-hidden", "true");
    for (var i = 0; i < text.length; i++) {
      var ch = document.createElement("span");
      ch.className = "roll__ch";
      ch.textContent = text[i];
      ch.setAttribute("data-ch", text[i]);
      ch.style.setProperty("--i", i);
      roll.appendChild(ch);
    }
    el.textContent = "";
    el.appendChild(roll);
    var link = el.closest("a");
    if (link && !link.hasAttribute("aria-label")) link.setAttribute("aria-label", text.trim());
  });

  /* ---------- scroll timeline ---------- */

  function render() {
    ticking = false;
    var p = (window.scrollY - story.offsetTop) / vh;
    if (p < 0) p = 0;

    if (p > 0.02) skipIntro();

    // Hero card: f2 full-bleed → f3 scale .968 (radius) → f4 scale .9236, y −268 → out
    var a = ramp(p, P.f2, P.f3);
    var b = ramp(p, P.f3, P.f4);
    var c = ramp(p, P.f4, P.f5);
    var scale = p < P.f3 ? lerp(1, 1394 / 1440, a) : lerp(1394 / 1440, 1330 / 1440, b);
    var ty = p < P.f4 ? lerp(0, -268.222, b) : lerp(-268.222, -820, c);
    hero.style.transform = "translate3d(0," + (ty * k).toFixed(2) + "px,0) scale(" + scale.toFixed(5) + ")";
    hero.style.borderRadius = (36 * k * a).toFixed(2) + "px";
    hero.style.opacity = (p < P.f4 ? lerp(1, 0.8, b) : lerp(0.8, 0, c)).toFixed(3);
    hero.style.visibility = c >= 1 ? "hidden" : "visible";
    if (c >= 1 && !video.paused && !video.ended) { video.pause(); pausedByScroll = true; }
    else if (c < 1 && pausedByScroll) { pausedByScroll = false; video.play().catch(function () {}); }

    // Header appears with the card (f3), turns light on f8
    var h = ramp(p, P.f2 + 0.08, P.f3);
    header.style.opacity = h.toFixed(3);
    header.style.visibility = h <= 0 ? "hidden" : "visible";
    header.style.marginTop = (-16 * (1 - h) * k).toFixed(2) + "px";

    var t = ramp(p, P.f7h, P.f8);
    var fg = Math.round(255 * (1 - t));
    root.style.setProperty("--t", t.toFixed(3));
    root.style.setProperty("--fg", fg + ", " + fg + ", " + fg);

    // Backgrounds
    bg5.style.opacity = ramp(p, P.f4, P.f5).toFixed(3);
    bg6.style.opacity = ramp(p, P.f5h, P.f6).toFixed(3);
    bg7.style.opacity = ramp(p, P.f6h, P.f7).toFixed(3);
    bg8.style.opacity = t.toFixed(3);
    grain.style.opacity = (ramp(p, P.f4, P.f5) * (1 - t)).toFixed(3);

    // Frame brackets + loader
    var ui = ramp(p, P.f4 + 0.3, P.f5);
    brackets.style.opacity = (ui * (1 - 0.5 * t)).toFixed(3);
    brackets.style.filter = "invert(" + t.toFixed(3) + ")";
    loader.style.opacity = ui.toFixed(3);

    var num = p < M56 ? "01" : p < M67 ? "02" : p < M78 ? "03" : "04";
    if (num !== lastNum) { loaderNum.textContent = num; lastNum = num; }
    loaderLines[0].style.opacity = (0.4 * (1 - ramp(p, P.f5h, P.f6))).toFixed(3);
    loaderLines[1].style.opacity = (0.4 * (1 - ramp(p, P.f6h, P.f7))).toFixed(3);
    loaderLines[2].style.opacity = (0.4 * (1 - ramp(p, P.f7h, P.f8))).toFixed(3);

    // Scene 1: f4 (45.6px, flat .6 × .4, at y 765.5) → f5 (64px gradient, centered)
    var s1in = ramp(p, P.f3, P.f4);
    var s1out = ramp(p, P.f5h, M56);
    var s1y = p < P.f4 ? lerp(485, 365.5, s1in) : lerp(365.5, 0, c) - 24 * s1out;
    var s1s = p < P.f4 ? 0.7125 : lerp(0.7125, 1, c);
    s1.style.opacity = (1 - s1out).toFixed(3);
    s1.style.transform = "translate(-50%, -50%) translate3d(0," + s1y.toFixed(2) + "px,0) scale(" + s1s.toFixed(5) + ")";
    s1flat.style.opacity = (p < P.f4 ? 0.4 * s1in : 0.4 * (1 - c)).toFixed(3);
    s1grad.style.opacity = c.toFixed(3);

    // Scenes 2, 3
    sceneCross(s2, ramp(p, M56, P.f6), ramp(p, P.f6h, M67));
    sceneCross(s3, ramp(p, M67, P.f7), ramp(p, P.f7h, M78));

    // Final scene
    var fin = ramp(p, M78, P.f8);
    sceneCross(sFinal, fin, 0);
    sFinal.style.pointerEvents = fin > 0.5 ? "auto" : "none";

    reveals.forEach(function (x) { x.r.set(clamp01((p - x.from) / (x.to - x.from))); });
  }

  function sceneCross(el, inT, outT) {
    el.style.opacity = (inT * (1 - outT)).toFixed(3);
    el.style.transform = "translate(-50%, -50%) translate3d(0," + (24 * (1 - inT) - 24 * outT).toFixed(2) + "px,0)";
  }

  function onScroll() {
    if (!ticking) {
      ticking = true;
      window.requestAnimationFrame(render);
    }
  }

  /* ---------- nav ---------- */

  document.querySelectorAll("[data-goto]").forEach(function (link) {
    link.addEventListener("click", function (e) {
      var key = link.getAttribute("data-goto");
      if (!(key in P)) return;
      e.preventDefault();
      window.scrollTo({ top: story.offsetTop + P[key] * vh, behavior: "smooth" });
    });
  });
  document.querySelector(".header__logo").addEventListener("click", function (e) {
    e.preventDefault();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", function () { measure(); layoutReveals(); render(); });

  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  measure();
  layoutReveals();
  render();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(layoutReveals);
})();
