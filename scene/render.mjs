// Renders the scene to PNG frames (and an MP4 if ffmpeg is installed) in headless Chromium.
//
//   node scene/render.mjs                      # all frames -> scene/out/frames, scene/out/the-answer.mp4
//   node scene/render.mjs --times 0,5.5,12     # just these moments -> scene/out/stills
//   node scene/render.mjs --out /some/dir
//   node scene/render.mjs --ai                 # 1080p version made for video-to-video AI restyling
//
// Needs Playwright with Chromium (`npm i -D playwright && npx playwright install chromium`).

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const here = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(`--${name}`); return i >= 0 ? args[i + 1] : dflt; };
const outDir = path.resolve(opt('out', path.join(here, 'out')));
const times = opt('times', null)?.split(',').map(Number);
const ai = args.includes('--ai');                       // the 1080p version for AI restyling

// tiny static server, so the ES modules load
const types = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript' };
const server = http.createServer((req, res) => {
  const file = path.join(here, decodeURIComponent(new URL(req.url, 'http://x').pathname));
  if (!file.startsWith(here) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
}).listen(0);
const port = server.address().port;

const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: ai ? { width: 1920, height: 1080 } : { width: 1280, height: 720 } });
page.on('pageerror', (e) => console.error('page error:', e.message));
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.error('console:', m.text()); });
await page.goto(`http://127.0.0.1:${port}/index.html?capture${ai ? '&ai' : ''}`);
await page.waitForFunction(() => window.QB_READY === true, null, { timeout: 60000 });
const { duration, fps } = await page.evaluate(() => ({ duration: window.QB.duration, fps: window.QB.fps }));

const list = times ?? Array.from({ length: Math.round(duration * fps) + 1 }, (_, f) => f / fps);
const dir = path.join(outDir, times ? 'stills' : 'frames');
fs.mkdirSync(dir, { recursive: true });
const t0 = Date.now();
for (let n = 0; n < list.length; n++) {
  const t = list[n];
  const png = await page.evaluate((tt) => { window.QB.renderAt(tt); return document.getElementById('c').toDataURL('image/png'); }, t);
  const name = times ? `t${t.toFixed(2).padStart(6, '0')}.png` : `f_${String(n).padStart(4, '0')}.png`;
  fs.writeFileSync(path.join(dir, name), Buffer.from(png.split(',')[1], 'base64'));
  if (n % 24 === 0) console.log(`${n + 1}/${list.length}  ${((Date.now() - t0) / (n + 1) / 1000).toFixed(2)} s/frame`);
}
await browser.close();
server.close();

if (!times) {
  const mp4 = path.join(outDir, ai ? 'the-answer-ai.mp4' : 'the-answer.mp4');
  try {
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(fps), '-i', path.join(dir, 'f_%04d.png'),
      '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '16', '-preset', 'slow', '-movflags', '+faststart', mp4]);
    console.log('wrote', mp4);
  } catch (e) {
    console.log('frames are in', dir, '(ffmpeg not found, so no MP4)');
  }
}
