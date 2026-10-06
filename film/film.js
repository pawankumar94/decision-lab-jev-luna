// Deterministic film: one paused GSAP timeline owns time; every frame is a pure function of t.
// Robot moves in Test 1 replay saved API responses. Test 2 motion is illustrative; its decisions are saved responses.
import * as THREE from './vendor/three.module.js';

const D = await fetch('data.json').then(r => { if (!r.ok) throw Error('missing data.json'); return r.json(); });
const $ = id => document.getElementById(id);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html !== undefined) e.innerHTML = html; return e; };
const mat = c => new THREE.MeshStandardMaterial({ color: c, roughness: .72 });
function box(w, h, d, c, x = 0, y = 0, z = 0) { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(c)); m.position.set(x, y, z); m.castShadow = m.receiveShadow = true; return m; }
function clear(g) { while (g.children.length) { const c = g.children[0]; g.remove(c); c.traverse(o => { o.geometry?.dispose(); if (o.material) [].concat(o.material).forEach(m => m.dispose()); }); } }

// ---------- shared 3D world ----------
class World {
  constructor(canvas, cols, rows, { half = 3.9, cam = [10, 12, 12] } = {}) {
    this.cols = cols; this.rows = rows; this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(1); this.renderer.shadowMap.enabled = true; this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    const w = canvas.clientWidth, h = canvas.clientHeight; this.renderer.setSize(w, h, false);
    this.scene = new THREE.Scene();
    const r = w / h; this.camera = new THREE.OrthographicCamera(-half * r, half * r, half, -half, .1, 100);
    this.camBase = new THREE.Vector3(...cam); this.camera.position.copy(this.camBase); this.camera.lookAt(0, 0, 0);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xb5bcc5, 2.5));
    const sun = new THREE.DirectionalLight(0xffffff, 3); sun.position.set(-5, 10, 6); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -9, right: 9, top: 9, bottom: -9 }); sun.shadow.normalBias = .04; this.scene.add(sun);
    this.scene.add(box(cols + .55, .16, rows + .55, 0xd5d8d6, 0, -.19, 0));
    for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) this.scene.add(box(.94, .06, .94, (x + y) % 2 ? 0xf0efe8 : 0xe9eae5, ...this.at(x, y, -.07)));
    this.layer = new THREE.Group(); this.trail = new THREE.Group(); this.scene.add(this.layer, this.trail);
  }
  at(x, y, h = 0) { return [x - (this.cols - 1) / 2, h, y - (this.rows - 1) / 2]; }
  orbit(angle) { const p = this.camBase.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), angle); this.camera.position.copy(p); this.camera.lookAt(0, 0, 0); }
  shelf(x, y, closed) {
    const g = new THREE.Group(); g.position.set(...this.at(x, y));
    g.add(box(.86, .1, .82, 0x303c47, 0, .14, 0), box(.86, .1, .82, 0x303c47, 0, .75, 0));
    for (const a of [-.38, .38]) for (const b of [-.35, .35]) g.add(box(.055, 1, .055, 0x4b5660, a, .5, b));
    g.add(box(.30, .37, .50, 0x9eacb6, -.18, .4, 0), box(.30, .37, .50, 0x788895, .18, .4, 0), box(.66, .25, .63, 0xbcc5c9, 0, .92, 0));
    if (closed) g.add(box(.92, .06, .9, 0xef1760, 0, 1.1, 0), box(.87, .5, .06, 0xef1760, 0, .6, .43));
    return g;
  }
  rough(x, y) { const g = new THREE.Group(); g.add(box(.9, .065, .9, 0xf0c986, ...this.at(x, y))); return g; }
  goal(x, y) {
    const g = new THREE.Group(); const pad = new THREE.Mesh(new THREE.CylinderGeometry(.38, .38, .03, 40), mat(0xf5be4e)); pad.position.set(...this.at(x, y, .055));
    g.add(pad, box(.03, .7, .03, 0x9d6a18, ...this.at(x, y, .35)), box(.28, .17, .025, 0xffd269, ...this.at(x + .13, y, .62))); return g;
  }
  robot(color) {
    const r = new THREE.Group();
    r.add(box(.57, .27, .56, color, 0, .27, 0), box(.38, .2, .34, 0x19232c, 0, .5, 0), box(.28, .16, .27, 0xf5d187, 0, .67, 0));
    for (const x of [-.3, .3]) for (const z of [-.18, .18]) { const w = new THREE.Mesh(new THREE.CylinderGeometry(.115, .115, .08, 12), mat(0x202a33)); w.rotation.z = Math.PI / 2; w.position.set(x, .17, z); r.add(w); }
    for (const x of [-.09, .09]) { const e = new THREE.Mesh(new THREE.SphereGeometry(.055, 12, 8), mat(0xffffff)); e.position.set(x, .51, .18); r.add(e); }
    const ring = new THREE.Mesh(new THREE.RingGeometry(.36, .44, 40), new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, transparent: true, opacity: .28 }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = .02; r.add(ring); r.userData.ring = ring;
    this.scene.add(r); return r;
  }
  path(points, color) {
    clear(this.trail);
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i]; if (a[0] === b[0] && a[1] === b[1]) continue;
      const c = new THREE.LineCurve3(new THREE.Vector3(...this.at(a[0], a[1], .05)), new THREE.Vector3(...this.at(b[0], b[1], .05)));
      this.trail.add(new THREE.Mesh(new THREE.TubeGeometry(c, 1, .03, 6, false), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: .6 })));
    }
  }
  render() { this.renderer.render(this.scene, this.camera); }
}

// ---------- Test 1: saved navigator traces ----------
class TraceBoard extends World {
  constructor(canvas, record, color, opts = {}) {
    super(canvas, 7, 7, { half: 4.1, ...opts }); this.record = record; this.color = color; this.lastMap = ''; this.bot = this.robot(color);
  }
  drawMap(state) {
    const key = state.map + state.door; if (key === this.lastMap) return; this.lastMap = key; clear(this.layer);
    const ev = this.record.episode.event?.close_cell;
    state.map.forEach((row, y) => [...row].forEach((m, x) => {
      if (m === '#') this.layer.add(this.shelf(x, y, state.door && ev && ev[0] === x && ev[1] === y));
      else if (m === '~') this.layer.add(this.rough(x, y));
    }));
    this.layer.add(this.goal(...this.record.episode.goal));
  }
  setTime(t) {
    const tr = this.record.trace, n = tr.length, i = Math.min(Math.floor(t), n - 1), s = tr[i], done = t >= n;
    this.drawMap(s.state);
    let f = done ? 1 : Math.min(1, (t - i) * 1.6); f = f * f * (3 - 2 * f);
    const a = s.state.position, b = s.after;
    this.bot.position.set(...this.at(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f));
    if (b[0] !== a[0] || b[1] !== a[1]) this.bot.rotation.y = Math.atan2(b[0] - a[0], b[1] - a[1]);
    this.path([this.record.episode.start, ...tr.slice(0, Math.floor(Math.min(t, n))).map(x => x.after)], this.color);
    this.render();
    return { step: s, index: i, n, done, door: s.state.door };
  }
}

// ---------- schedule ----------
const ACTION = 0.85;
const navLen = Math.max(...D.nav.boards.map(b => b.record.trace.length));
const S = {}; let cursor = 0;
for (const [id, len] of [['title', 5.5], ['nav', 3 + navLen * ACTION + 3.2], ['navres', 9], ['hybrid', 2.5 + D.hybrid.incidents.length * 8], ['results', 12], ['end', 14]]) { S[id] = [cursor, cursor + len]; cursor += len; }
const tl = gsap.timeline({ paused: true, defaults: { ease: 'power3.out' } });
// Scene visibility is a pure function of t (not tween history), so any seek order is safe.
function sceneAlpha(id, t) {
  const [a, b] = S[id], fade = .45;
  if (t < a || t > b) return 0;
  const fin = Math.min(1, (t - a) / fade), fout = id === 'end' ? 1 : Math.min(1, (b - t) / fade);
  return Math.max(0, Math.min(fin, fout));
}
const CUES = []; const cue = (t, type, extra = {}) => CUES.push({ t: +t.toFixed(3), type, ...extra });
const drive = (start, dur, fn) => { const p = { t: 0 }; tl.fromTo(p, { t: 0 }, { t: dur, duration: dur, ease: 'none', immediateRender: false, onUpdate: () => fn(p.t) }, start); };

// ---------- title ----------
$('title-dek').innerHTML = D.title.dek; $('title-fine').innerHTML = D.title.fine;
const titleWorld = new TraceBoard($('title-canvas'), D.nav.boards.find(b => b.key === 'bfs').record, 0x137f79, { half: 5.2, cam: D.nav.cam });
{ const [a, b] = S.title; drive(a, b - a + 1, t => { titleWorld.orbit(-.35 + t * .07); titleWorld.setTime(Math.min(t * 2.6, titleWorld.record.trace.length)); }); }
tl.from('#title .h1 span', { y: 60, autoAlpha: 0, duration: .8, stagger: .14, immediateRender: false }, S.title[0] + .25);
cue(S.title[0] + .2, 'boom'); [0, 1, 2].forEach(k => cue(S.title[0] + .25 + k * .14, 'tick', { level: .5 }));
tl.from('#title-dek', { y: 24, autoAlpha: 0, duration: .7, immediateRender: false }, S.title[0] + .9);

// ---------- Test 1 boards ----------
$('nav-fine').innerHTML = D.nav.fine;
const boards = D.nav.boards.map(b => {
  const card = el('div', 'board');
  card.innerHTML = `<div class="head"><div class="name fit" style="color:${b.color}">${b.name}</div><div class="sub fit">${b.sub}</div></div>
    <canvas></canvas><div class="read"><div><div class="lab">Chosen action</div><div class="act fit">—</div></div><div><div class="lab" style="text-align:right">${b.signal}</div><div class="conf">—</div></div></div>
    <div class="stamp ${b.record.completed ? 'good' : 'bad'}">${b.record.completed ? 'DELIVERED' : b.record.outcome === 'loop_limit' ? 'LOOPED' : b.record.outcome.toUpperCase()}</div>`;
  $('nav-boards').append(card);
  return { b, card, world: new TraceBoard(card.querySelector('canvas'), b.record, new THREE.Color(b.color).getHex(), { half: 4.4, cam: D.nav.cam }) };
});
{
  const [a] = S.nav, start = a + 2.2;
  tl.from('#nav-boards .board', { y: 50, autoAlpha: 0, duration: .7, stagger: .12, immediateRender: false }, a + .3);
  drive(start, navLen * ACTION + 1, t => boards.forEach(({ b, card, world }) => {
    const r = world.setTime(t / ACTION), s = r.step;
    card.querySelector('.act').textContent = r.done ? (b.record.completed ? 'finish ✓' : 'stopped') : s.action;
    card.querySelector('.conf').textContent = s.confidence == null ? 'n/a' : s.confidence.toFixed(2);
  }));
  for (let k = 0; k < navLen; k++) cue(start + k * ACTION + .02, 'tick');
  cue(start + 2 * ACTION, 'thunk');
  for (const { b, card } of boards) {
    const at = start + b.record.trace.length * ACTION + .2;
    cue(at, b.record.completed ? 'success' : 'fail');
    tl.fromTo(card.querySelector('.stamp'), { autoAlpha: 0, scale: 1.3 }, { autoAlpha: 1, scale: 1, duration: .45, ease: 'back.out(2)', immediateRender: true }, at);
  }
}

// ---------- Test 1 results ----------
$('navres-title').innerHTML = D.navres.title; $('navres-fine').innerHTML = D.navres.fine;
for (const r of D.navres.rows) {
  const row = el('div', 'bar');
  row.innerHTML = `<div class="who fit" style="color:${r.color}">${r.name}</div><div class="track"><div class="fill" style="background:${r.color};width:${100 * r.completed / r.n}%"></div></div><div class="val fit">${r.completed} / ${r.n}<small>${r.detail}</small></div>`;
  $('navres-bars').append(row);
}
tl.from('#navres-bars .fill', { scaleX: 0, duration: 1.1, stagger: .18, ease: 'power2.out', immediateRender: false }, S.navres[0] + .6);
D.navres.rows.forEach((r, k) => cue(S.navres[0] + .6 + k * .18, 'rise', { amount: r.completed / r.n }));
tl.from('#navres-bars .val', { autoAlpha: 0, x: -20, duration: .5, stagger: .18, immediateRender: false }, S.navres[0] + 1.2);

// ---------- Test 2 hybrid ----------
$('hybrid-fine').innerHTML = D.hybrid.fine;
const H = new World($('hybrid-canvas'), 11, 7, { half: 4.6, cam: [9, 13, 12] });
const SHELVES = []; for (const y of [1, 2, 4, 5]) for (const x of [2, 3, 4, 7, 8, 9]) SHELVES.push([x, y]);
SHELVES.forEach(([x, y]) => H.layer.add(H.shelf(x, y, false)));
H.layer.add(H.goal(10, 3));
const hb = H.robot(0x137f79);
const BLOCK = [8, 3];
const obstacles = {
  person: (() => { const g = new THREE.Group(); const body = new THREE.Mesh(new THREE.CylinderGeometry(.16, .2, .62, 16), mat(0xe39b1b)); body.position.y = .34; const head = new THREE.Mesh(new THREE.SphereGeometry(.14, 16, 12), mat(0xf2c9a0)); head.position.y = .78; g.add(body, head); return g; })(),
  crate: (() => { const g = new THREE.Group(); g.add(box(.5, .42, .5, 0x6e5a48, 0, .21, 0), box(.52, .05, .52, 0x403229, 0, .44, 0)); return g; })(),
  spill: (() => { const m = new THREE.Mesh(new THREE.CylinderGeometry(.42, .42, .02, 32), new THREE.MeshStandardMaterial({ color: 0x5aa7d6, transparent: true, opacity: .75, roughness: .1 })); m.position.y = .04; const g = new THREE.Group(); g.add(m); return g; })(),
  sensor: (() => { const g = new THREE.Group(); g.add(box(.08, .9, .08, 0x303c47, -.38, .45, 0), box(.08, .9, .08, 0x303c47, .38, .45, 0)); const beam = new THREE.Mesh(new THREE.BoxGeometry(.7, .04, .04), new THREE.MeshBasicMaterial({ color: 0xef1760 })); beam.position.y = .55; g.add(beam); return g; })(),
};
for (const o of Object.values(obstacles)) { o.position.set(...H.at(...BLOCK)); o.visible = false; H.scene.add(o); }
// Robot routes authored on the illustrative grid, played through Three.js keyframe clips.
const ROUTES = {
  approach: [[0, 3], [1, 3], [2, 3], [3, 3], [4, 3], [5, 3], [6, 3]],
  wait: [[6, 3], [6, 3], [7, 3], [8, 3], [9, 3], [10, 3]],
  reroute: [[6, 3], [6, 2], [6, 1], [6, 0], [7, 0], [8, 0], [9, 0], [10, 0], [10, 1], [10, 2], [10, 3]],
  escalate: [[6, 3], [6, 3]],
};
const mixer = new THREE.AnimationMixer(hb);
function clipFor(name, pts, dur) {
  const times = pts.map((_, i) => i * dur / (pts.length - 1)), values = pts.flatMap(p => H.at(p[0], p[1]));
  return mixer.clipAction(new THREE.AnimationClip(name, dur, [new THREE.VectorKeyframeTrack('.position', times, values)]));
}
const actions = { approach: clipFor('approach', ROUTES.approach, 1.6), wait: clipFor('wait', ROUTES.wait, 2.6), reroute: clipFor('reroute', ROUTES.reroute, 2.8), escalate: clipFor('escalate', ROUTES.escalate, 1) };
function pose(name, t) {
  for (const a of Object.values(actions)) { a.stop(); }
  const a = actions[name]; a.play(); a.paused = true; a.clampWhenFinished = true; a.setLoop(THREE.LoopOnce, 1); a.time = Math.min(t, a.getClip().duration - 1e-4); mixer.update(0);
  const pts = ROUTES[name], seg = Math.min(pts.length - 2, Math.floor(a.time / a.getClip().duration * (pts.length - 1)));
  const p = pts[seg], q = pts[seg + 1]; if (q && (q[0] !== p[0] || q[1] !== p[1])) hb.rotation.y = Math.atan2(q[0] - p[0], q[1] - p[1]);
}
const humanTag = $('human-tag');
function showIncident(inc, k) {
  $('note-lab').textContent = `Hand-written note ${k + 1} of ${D.hybrid.incidents.length} · held out`;
  $('note-text').textContent = inc.text;
  $('policy').innerHTML = `Policy answer: <b>${inc.gold}</b> · robot shown doing the policy action`;
  $('verdicts').innerHTML = inc.models.map(m => `<div class="verdict"><div class="who fit" style="color:${m.color}">${m.name}</div><div class="choice fit">${m.choice} <span style="color:var(--muted);font-size:20px">${m.confidence == null ? 'rule' : m.confidence.toFixed(2)}</span></div><div class="gate g-${m.gate}">${{ auto: 'AUTOMATE', human: 'TO HUMAN', wrong: 'WRONG AUTO' }[m.gate]}</div></div>`).join('');
}
function screenOf(cell, lift = 1.3) { const v = new THREE.Vector3(...H.at(cell[0], cell[1], lift)).project(H.camera); const r = H.canvas.getBoundingClientRect(); return [r.left + (v.x + 1) / 2 * r.width, r.top + (1 - v.y) / 2 * r.height]; }
{
  const [a] = S.hybrid; let at = a + 2.5;
  tl.from('#hybrid-canvas', { autoAlpha: 0, y: 30, duration: .8, immediateRender: false }, a + .3);
  D.hybrid.incidents.forEach((inc, k) => {
    const start = at, kind = inc.visual;
    drive(start, 8, t => {
      if (H.shown !== k) { H.shown = k; showIncident(inc, k); }
      Object.entries(obstacles).forEach(([key, o]) => { o.visible = key === kind && t > .9 && !(inc.behavior === 'wait' && t > 6.4); if (o.visible) o.scale.setScalar(Math.min(1, (t - .9) * 4)); });
      if (t < 1.6) pose('approach', t); else if (t < 5) pose('approach', 1.6); else pose(inc.behavior, t - 5);
      const ring = hb.userData.ring; ring.material.opacity = .28 + (t > 1.6 && t < 5.2 ? .35 * (0.5 + 0.5 * Math.sin(t * 9)) : 0);
      H.orbit(-.18 + (k * 8 + t) * .012);
      const done = t < 5 ? ROUTES.approach.slice(0, Math.floor(Math.min(t, 1.6) / 1.6 * 6) + 1) : ROUTES.approach.concat(ROUTES[inc.behavior].slice(0, Math.floor((t - 5) / (inc.behavior === 'reroute' ? 2.8 : 2.6) * (ROUTES[inc.behavior].length - 1)) + 1));
      H.path(done, 0x137f79); H.render();
      if (inc.behavior === 'escalate' && t > 4.6) { const [x, y] = screenOf([8, 3], 1.7); gsap.set(humanTag, { left: x - 90, top: y - 50, autoAlpha: Math.min(1, (t - 4.6) * 3) }); } else gsap.set(humanTag, { autoAlpha: 0 });
    });
    tl.fromTo('.note', { autoAlpha: 0, x: 40 }, { autoAlpha: 1, x: 0, duration: .5, immediateRender: false }, start + 1.1);
    tl.fromTo('#note-text', { clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0% 0 0)', duration: 1.2, ease: 'none', immediateRender: false }, start + 1.4);
    tl.fromTo('#verdicts', { autoAlpha: 0, y: 20 }, { autoAlpha: 1, y: 0, duration: .5, immediateRender: false }, start + 2.9);
    tl.fromTo('#policy', { autoAlpha: 0 }, { autoAlpha: 1, duration: .4, immediateRender: false }, start + 4.4);
    tl.to(['.note', '#verdicts', '#policy'], { autoAlpha: 0, duration: .35 }, start + 7.6);
    cue(start + .9, 'pop'); cue(start + 1.4, 'type', { duration: 1.2 }); cue(start + 2.9, 'blip');
    if (inc.models.some(m => m.gate === 'wrong')) cue(start + 3.3, 'fail', { level: .7 });
    cue(start + 5, inc.behavior === 'escalate' ? 'alert' : 'go');
    at += 8;
  });
}

// ---------- results ----------
$('results-title').innerHTML = D.results.title; $('results-fine').innerHTML = D.results.fine;
for (const p of D.results.panels) {
  const panel = el('div', 'panel');
  panel.innerHTML = `<h3 class="fit">${p.h}</h3><div class="q">${p.q}</div><div class="rows">${p.rows.map(r => `<div class="row"><div class="who fit" style="color:${r.color}">${r.name}</div><div class="track"><div class="fill" style="background:${r.color};width:${Math.max(0, 100 * r.value / p.max)}%"></div></div><div class="num fit">${r.label}</div></div>`).join('')}</div><div class="foot">${p.foot}</div>`;
  $('panels').append(panel);
}
tl.from('#panels .panel', { y: 50, autoAlpha: 0, duration: .7, stagger: .25, immediateRender: false }, S.results[0] + .4);
tl.from('#panels .fill', { scaleX: 0, duration: .9, stagger: .05, ease: 'power2.out', immediateRender: false }, S.results[0] + 1.1);
[0, 1, 2].forEach(k => cue(S.results[0] + .4 + k * .25, 'swish')); cue(S.results[0] + 1.1, 'rise', { amount: 1 });

// ---------- end ----------
$('end-lines').innerHTML = D.end.lines.map(l => `<div class="line fit">${l}</div>`).join(''); $('end-fine').innerHTML = D.end.fine;
$('end-stats').innerHTML = D.end.stats.map(x => `<div class="stat"><b>${x.value}</b><span>${x.label}</span></div>`).join('');
{
  // Closing scene: the planner-driven robot finishes the illustrative delivery while the takeaways land.
  const E = new World($('end-canvas'), 11, 7, { half: 6.1, cam: [9, 13, 12] });
  SHELVES.forEach(([x, y]) => E.layer.add(E.shelf(x, y, false)));
  const goal = E.goal(10, 3); E.layer.add(goal);
  const bot = E.robot(0x137f79);
  const route = ROUTES.approach.concat(ROUTES.reroute.slice(1));
  const [a] = S.end, travel = 6.2;
  drive(a, 9, t => {
    const u = Math.min(1, Math.max(0, (t - .4) / travel)) * (route.length - 1), k = Math.min(route.length - 2, Math.floor(u)), f = u - k;
    const p = route[k], q = route[k + 1];
    bot.position.set(...E.at(p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f));
    if (q[0] !== p[0] || q[1] !== p[1]) bot.rotation.y = Math.atan2(q[0] - p[0], q[1] - p[1]);
    E.path(route.slice(0, k + 2).map((c, j) => j === k + 1 ? [p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f] : c), 0x137f79);
    const arrived = t > .4 + travel; goal.scale.setScalar(arrived ? 1 + .12 * Math.sin((t - .4 - travel) * 8) * Math.exp(-(t - .4 - travel) * 1.5) : 1);
    E.orbit(-.3 + t * .05); E.render();
  });
  cue(a + .4 + travel, 'success', { level: .8 });
  tl.from('#end .line', { x: -60, autoAlpha: 0, duration: .8, stagger: .6, immediateRender: false }, a + .5);
  [0, 1, 2].forEach(k => cue(a + .5 + k * .6, 'note', { step: k }));
  tl.fromTo('#end-card', { autoAlpha: 0 }, { autoAlpha: 1, duration: .9, ease: 'power2.inOut', immediateRender: false }, a + 8.2);
  tl.from('#end-card .cardq', { y: 40, autoAlpha: 0, duration: .8, stagger: .15, immediateRender: false }, a + 8.5);
  tl.from('#end-card .stat', { y: 30, autoAlpha: 0, duration: .6, stagger: .15, immediateRender: false }, a + 9.3);
  tl.from(['#end-card .cta', '#end-card .by'], { autoAlpha: 0, duration: .6, stagger: .2, immediateRender: false }, a + 10.1);
  cue(a + 8.2, 'swish'); cue(a + 8.6, 'resolve');
}

tl.to({}, { duration: .01 }, cursor);
const duration = cursor;
function seek(t) {
  t = Math.max(0, Math.min(t, duration));
  tl.seek(t, false);
  for (const id in S) { const o = sceneAlpha(id, t); gsap.set('#' + id, { opacity: o, visibility: o > 0 ? 'visible' : 'hidden' }); }
}
seek(0);
for (const id in S) if (id !== 'title') cue(S[id][0], 'whoosh');
CUES.sort((x, y) => x.t - y.t);
window.film = { duration, schedule: S, seek, cues: CUES, ready: true };
