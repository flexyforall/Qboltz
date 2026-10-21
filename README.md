# Qboltz — landing

Static page built from the Figma "Concept UI" storyboard
([Qboltz, node 769:217](https://www.figma.com/design/oJQYEBb5q5ecyGu5tN6wfW/Qboltz?node-id=769-217)).

Open `index.html` through any static server, for example `npx serve .` or `python3 -m http.server`.
Video seeking needs HTTP Range support. Every real host has it, but `python3 -m http.server` does not.

## How it works

- **Intro**: the background video (`assets/video/hero.*`) plays once and stops on its last frame,
  the flare. The logo and the "Where machines think with photons." headline then fade in.
  If the visitor scrolls before the video ends, it jumps ahead to the flare.
- **Scroll storyboard**: one sticky 1440×800 stage. Each Figma frame is a keyframe in
  `assets/js/main.js` (`P.f2 … P.f8`):
  1. f2: hero
  2. f3: header appears and the hero becomes a card
  3. f4: the card leaves and "We're building…" comes in
  4. f5–f7: purple gradient scenes, 01 → 03
  5. f8: white final scene with the CTA
- **Pixel accuracy**: all sizes are design pixels. The stage is scaled by `--k = min(vw/1440, vh/800)`,
  so a 1440×800 viewport renders 1:1 with Figma.

## Assets

```
assets/
  css/style.css         styles (gradients copied from Figma as SVG data URIs)
  js/main.js            intro + scroll timeline
  fonts/                Host Grotesk (variable, latin + latin-ext, from Google Fonts)
  icons/                SVGs exported from Figma (logos, menu brackets, button corners, frame brackets, plus)
  images/button-bg.png  "Talk to us" button fill (Figma)
  images/hero-poster.jpg first video frame (poster)
  images/noise.png      grain that reproduces Figma's Noise effect on the gradient frames
  video/hero.webm|mp4   intro video (WebM for Chrome/Firefox, MP4 fallback for Safari)
```
