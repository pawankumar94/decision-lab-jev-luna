// Render the film frame by frame from the seekable timeline, after failing on any text overflow.
// Usage: serve the repo root (python3 -m http.server 8790 --bind 127.0.0.1), then: node film/render.js [--check-only] [--audio-only] [--fps 30]
// Env: FILM_URL (default http://127.0.0.1:8790/film/), CHROME_PATH (optional; defaults to Playwright's Chromium).
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { chromium } = require('playwright');

const fps = Number(process.argv[process.argv.indexOf('--fps') + 1]) || 30;
const checkOnly = process.argv.includes('--check-only');
const audioOnly = process.argv.includes('--audio-only');
const [VW, VH] = [1920, 1080];
const out = path.join(__dirname, '..', 'renders');
const frames = path.join(out, 'film-frames');

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: VW, height: VH }, deviceScaleFactor: 1 });
  const errors = []; page.on('pageerror', e => errors.push(e.message)); page.on('console', m => m.type() === 'error' && errors.push(m.text()));
  await page.goto(process.env.FILM_URL || 'http://127.0.0.1:8790/film/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => window.film?.ready, null, { timeout: 30000 });
  const { duration, schedule } = await page.evaluate(() => ({ duration: window.film.duration, schedule: window.film.schedule }));
  console.log('Film duration', duration.toFixed(1), 's', JSON.stringify(schedule));
  const cues = await page.evaluate(() => window.film.cues);
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(path.join(out, 'film-cues.json'), JSON.stringify({ duration, cues, schedule }, null, 1));
  if (audioOnly) { await browser.close(); encode(duration); return; }

  // Overflow gate: sample each scene densely; any clipped text or element past the stage edge fails the render.
  const problems = new Set();
  for (const [id, [a, b]] of Object.entries(schedule)) {
    for (let t = a + 0.6; t < b - 0.5; t += 0.5) {
      const found = await page.evaluate(([t, id]) => {
        window.film.seek(t);
        const bad = [];
        for (const e of document.querySelectorAll(`#${id} .fit, #${id} .val, #${id} .num, #${id} .choice, #${id} .gate, #${id} .text, #${id} .foot, #${id} .q`)) {
          const cs = getComputedStyle(e); if (cs.visibility === 'hidden' || cs.display === 'none') continue;
          const r = e.getBoundingClientRect(); if (!r.width) continue;
          if (e.scrollWidth > e.clientWidth + 1) bad.push(`clipped: ${e.className} "${e.textContent.trim().slice(0, 50)}"`);
          if (r.right > innerWidth - 30 || r.bottom > innerHeight - 8 || r.left < 20) bad.push(`off-stage: ${e.className} "${e.textContent.trim().slice(0, 50)}" ${Math.round(r.left)},${Math.round(r.right)},${Math.round(r.bottom)}`);
          const panel = e.closest('.panel,.board,.verdict,.note');
          if (panel) { const p = panel.getBoundingClientRect(); if (r.right > p.right + 1 || r.bottom > p.bottom + 1) bad.push(`outside card: ${e.className} "${e.textContent.trim().slice(0, 50)}"`); }
        }
        // Text must not sit on top of a 3D canvas (the end card is a deliberate full-screen overlay).
        for (const cv of document.querySelectorAll(`#${id} > canvas`)) {
          const c = cv.getBoundingClientRect();
          for (const e of document.querySelectorAll(`#${id} .fit, #${id} .dek`)) {
            if (e.closest('#end-card') || getComputedStyle(e).visibility === 'hidden') continue;
            const range = document.createRange(); range.selectNodeContents(e);
            for (const r of range.getClientRects()) if (r.width && r.right > c.left + 4 && r.left < c.right && r.bottom > c.top && r.top < c.bottom) { bad.push(`text over canvas: "${e.textContent.trim().slice(0, 40)}"`); break; }
          }
        }
        for (const c of document.querySelectorAll(`#${id} .panel, #${id} .board, #${id} .note, #${id} .verdict, #${id} .read, #${id} .head`)) {
          if (getComputedStyle(c).visibility === 'hidden') continue;
          if (c.scrollHeight > c.clientHeight + 1 || c.scrollWidth > c.clientWidth + 1) bad.push(`card overflow: ${c.className} "${c.textContent.trim().slice(0, 50)}"`);
        }
        return bad;
      }, [t, id]);
      found.forEach(f => problems.add(`${id}: ${f}`));
    }
  }
  if (problems.size) { console.error([...problems].join('\n')); process.exit(2); }
  console.log('Overflow gate passed for all scenes.');

  fs.mkdirSync(out, { recursive: true });
  await page.reload({ waitUntil: 'networkidle' }); await page.waitForFunction(() => window.film?.ready);
  for (const [id, [a, b]] of Object.entries(schedule)) {
    await page.evaluate(t => window.film.seek(t), (a + b) / 2 + (id === 'hybrid' ? 2 : 0));
    await page.screenshot({ path: path.join(out, `film-still-${id}.png`) });
  }
  if (checkOnly) { await browser.close(); if (errors.length) throw Error(errors.join('; ')); console.log('Stills written.'); return; }

  fs.rmSync(frames, { recursive: true, force: true }); fs.mkdirSync(frames, { recursive: true });
  const total = Math.ceil(duration * fps);
  for (let i = 0; i < total; i++) {
    await page.evaluate(t => window.film.seek(t), i / fps);
    await page.screenshot({ path: path.join(frames, String(i).padStart(5, '0') + '.png') });
    if (i % (fps * 5) === 0) console.log('frame', i, 'of', total);
  }
  await browser.close();
  if (errors.length) throw Error(errors.join('; '));
  const silent = path.join(out, 'decision-lab-film-silent.mp4');
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(fps), '-i', path.join(frames, '%05d.png'),
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', silent]);
  encode(duration);
})().catch(e => { console.error(e.message); process.exit(1); });

// Synthesize the soundtrack from the cue list and mux it onto the silent master.
function encode(duration) {
  const silent = path.join(out, 'decision-lab-film-silent.mp4'), wav = path.join(out, 'film-audio.wav'), mp4 = path.join(out, 'decision-lab-film.mp4');
  execFileSync('python3', [path.join(__dirname, '..', 'src', 'film_audio.py'), path.join(out, 'film-cues.json'), wav], { stdio: 'inherit' });
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', silent, '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
    '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-t', String(duration), '-movflags', '+faststart', mp4]);
  // LinkedIn master: re-encode from the lossless frames at high quality; LinkedIn recompresses, so give it a clean source.
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', '30', '-i', path.join(frames, '%05d.png'), '-i', wav, '-map', '0:v', '-map', '1:a',
    '-c:v', 'libx264', '-preset', 'slow', '-tune', 'animation', '-crf', '14', '-maxrate', '16M', '-bufsize', '32M', '-profile:v', 'high', '-level', '4.2', '-pix_fmt', 'yuv420p', '-g', '60',
    '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11', '-t', String(duration), '-movflags', '+faststart', path.join(out, 'decision-lab-film-linkedin.mp4')]);
  console.log('Wrote', mp4);
}
