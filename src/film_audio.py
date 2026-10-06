"""Synthesize the film soundtrack from the timeline's cue list. No samples, no downloads, no licences.

Usage: python3 src/film_audio.py renders/film-cues.json renders/film-audio.wav
The cue file comes from window.film.cues (written by film/render.js); every sound sits on a real timeline event.
"""
import json
import sys
import wave

import numpy as np

SR = 48000
rng = np.random.default_rng(20261007)


def t_axis(seconds):
    return np.arange(int(seconds * SR)) / SR


def env(n, attack=.005, decay=.2, curve=6.0):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-curve * np.clip(t - attack, 0, None) / max(decay, 1e-4))


def sine(freq, seconds, phase=0.0):
    t = t_axis(seconds)
    f = np.broadcast_to(np.asarray(freq, dtype=float), t.shape) if np.ndim(freq) else np.full(t.shape, float(freq))
    return np.sin(2 * np.pi * np.cumsum(f) / SR + phase)


def band_noise(seconds, lo, hi):
    n = int(seconds * SR); x = rng.standard_normal(n)
    spec = np.fft.rfft(x); freqs = np.fft.rfftfreq(n, 1 / SR)
    spec[(freqs < lo) | (freqs > hi)] = 0
    y = np.fft.irfft(spec, n); return y / (np.abs(y).max() + 1e-9)


def note_hz(name):
    names = {'C': -9, 'C#': -8, 'D': -7, 'D#': -6, 'E': -5, 'F': -4, 'F#': -3, 'G': -2, 'G#': -1, 'A': 0, 'A#': 1, 'B': 2}
    return 440.0 * 2 ** ((names[name[:-1]] + 12 * (int(name[-1]) - 4)) / 12)


def pluck(freq, seconds=.7, bright=.35):
    n = int(seconds * SR)
    x = sine(freq, seconds) + bright * sine(2 * freq, seconds) + .12 * sine(3 * freq, seconds)
    return x * env(n, .003, seconds * .45, 5)


# ---------- effects ----------
def fx_tick(level=1.0):
    n = int(.05 * SR); return level * .22 * (sine(2600, .05) * env(n, .001, .012, 6) + .3 * band_noise(.05, 3000, 9000) * env(n, .0005, .006, 6))


def fx_thunk():
    s = .7; n = int(s * SR); drop = np.linspace(95, 42, n)
    body = sine(drop, s) * env(n, .002, .35, 5)
    metal = (.35 * sine(183, s) + .25 * sine(431, s) + .15 * sine(977, s)) * env(n, .001, .18, 6)
    return .55 * (body + metal + .4 * band_noise(s, 60, 900) * env(n, .001, .05, 6))


def fx_fail(level=1.0):
    out = []
    for f in (220, 174.6):
        s = .17; n = int(s * SR)
        x = sum(sine(f * k, s) / k for k in range(1, 7)) * env(n, .004, .14, 3)
        out.append(np.concatenate([x, np.zeros(int(.04 * SR))]))
    return level * .2 * np.concatenate(out)


def fx_success(level=1.0):
    a = pluck(note_hz('E5'), 1.0, .2); b = pluck(note_hz('B5'), 1.3, .2)
    y = np.zeros(int(1.5 * SR)); y[:len(a)] += a; off = int(.11 * SR); y[off:off + len(b)] += b
    return level * .22 * y


def fx_pop():
    s = .09; n = int(s * SR); return .25 * sine(np.linspace(520, 980, n), s) * env(n, .002, .05, 5)


def fx_blip():
    s = .08; n = int(s * SR); return .18 * (sine(1320, s) + .3 * sine(2640, s)) * env(n, .002, .04, 5)


def fx_type(duration):
    y = np.zeros(int((duration + .1) * SR)); t = 0.0
    while t < duration:
        click = band_noise(.012, 1800, 7000) * env(int(.012 * SR), .0005, .004, 6) * (.10 + .05 * rng.random())
        i = int(t * SR); y[i:i + len(click)] += click; t += .045 + .05 * rng.random()
    return y


def fx_alert():
    y = []
    for f in (880, 660, 880, 660):
        s = .13; n = int(s * SR); y.append((sine(f, s) + .2 * sine(2 * f, s)) * env(n, .005, .11, 3)); y.append(np.zeros(int(.03 * SR)))
    return .14 * np.concatenate(y)


def fx_go():
    s = .28; n = int(s * SR); return .14 * sine(np.geomspace(380, 820, n), s) * env(n, .01, .22, 3)


def fx_rise(amount=1.0):
    s = .55; n = int(s * SR); top = 300 + 600 * amount
    return .10 * (sine(np.geomspace(300, top, n), s) + .3 * sine(np.geomspace(600, 2 * top, n), s)) * np.sin(np.linspace(0, np.pi, n)) ** 1.5


def fx_whoosh(seconds=.75, level=.22):
    n = int(seconds * SR); chunks = 10; y = np.zeros(n); w = n // chunks
    for k in range(chunks):
        centre = 300 * (12 ** (k / (chunks - 1)))
        seg = band_noise(2 * w / SR, centre * .6, centre * 1.6)[:2 * w] * np.hanning(2 * w)
        start = max(0, k * w - w // 2); y[start:start + len(seg)] += seg[:n - start]
    return level * y * np.sin(np.linspace(0, np.pi, n)) ** 2


def fx_boom():
    s = 2.0; n = int(s * SR); return .5 * (sine(np.linspace(62, 38, n), s) * env(n, .004, 1.1, 4) + .25 * band_noise(s, 30, 400) * env(n, .002, .3, 6))


def fx_note(step):
    return .2 * pluck(note_hz(['A4', 'C#5', 'E5'][step % 3]), 1.4, .3)


def fx_resolve():
    s = 4.5; n = int(s * SR); y = np.zeros(n)
    for name in ('A2', 'E3', 'A3', 'C#4', 'E4', 'A4'):
        f = note_hz(name); y += sine(f, s) + .4 * sine(f * 1.003, s) + .15 * sine(2 * f, s)
    shape = np.minimum(1, np.arange(n) / (.8 * SR)) * np.exp(-1.1 * np.arange(n) / SR)
    return .05 * y * shape


FX = {'tick': lambda c: fx_tick(c.get('level', 1)), 'thunk': lambda c: fx_thunk(), 'fail': lambda c: fx_fail(c.get('level', 1)),
    'success': lambda c: fx_success(c.get('level', 1)), 'pop': lambda c: fx_pop(), 'blip': lambda c: fx_blip(), 'type': lambda c: fx_type(c['duration']),
    'alert': lambda c: fx_alert(), 'go': lambda c: fx_go(), 'rise': lambda c: fx_rise(c.get('amount', 1)), 'whoosh': lambda c: fx_whoosh(),
    'swish': lambda c: fx_whoosh(.4, .12), 'boom': lambda c: fx_boom(), 'note': lambda c: fx_note(c['step']), 'resolve': lambda c: fx_resolve()}


# ---------- music bed ----------
def bed(seconds):
    """Soft A-major pad (A, F#m, D, E) with a quiet eighth-note pluck arpeggio. 96 BPM."""
    n = int(seconds * SR); out = np.zeros((2, n)); bar = 60 / 96 * 4 * 2  # two bars per chord
    chords = [('A2', 'C#4', 'E4', 'A4'), ('F#2', 'C#4', 'F#4', 'A4'), ('D2', 'D4', 'F#4', 'A4'), ('E2', 'B3', 'E4', 'G#4')]
    t = 0.0; k = 0
    while t < seconds:
        names = chords[k % 4]; seg = min(bar + 1.0, seconds - t + 1.0); m = int(seg * SR)
        shape = np.minimum(1, np.arange(m) / (.9 * SR)) * np.minimum(1, (m - np.arange(m)) / (1.0 * SR))
        for j, name in enumerate(names):
            f = note_hz(name)
            voice = sine(f, seg) + .5 * sine(f * 1.004, seg, 1.3) + .12 * sine(2 * f, seg)
            pan = .35 + .3 * (j / 3)
            i0 = int(t * SR); i1 = min(n, i0 + m)
            out[0, i0:i1] += (1 - pan) * (voice * shape)[:i1 - i0]; out[1, i0:i1] += pan * (voice * shape)[:i1 - i0]
        step = 60 / 96 / 2
        for e in range(int(bar / step)):
            ts = t + e * step
            if ts >= seconds: break
            name = names[1 + e % 3]; f = note_hz(name) * (2 if e % 4 == 3 else 1)
            p = .35 * pluck(f, .45, .25); i0 = int(ts * SR); i1 = min(n, i0 + len(p))
            side = .3 if e % 2 else .7
            out[0, i0:i1] += (1 - side) * p[:i1 - i0]; out[1, i0:i1] += side * p[:i1 - i0]
        t += bar; k += 1
    out *= .045
    fade = np.ones(n); fi, fo = int(1.5 * SR), int(3.0 * SR); fade[:fi] = np.linspace(0, 1, fi); fade[-fo:] = np.linspace(1, 0, fo)
    return out * fade


def main(cue_path, out_path):
    data = json.loads(open(cue_path).read())
    seconds = data['duration'] + 0.5
    mix = bed(seconds)
    fx = np.zeros(mix.shape[1])
    for c in data['cues']:
        clip = FX[c['type']](c); i = int(c['t'] * SR); j = min(len(fx), i + len(clip)); fx[i:j] += clip[:j - i]
    # Duck the bed slightly under dense effects so ticks and chimes stay readable.
    energy = np.convolve(np.abs(fx), np.ones(int(.08 * SR)) / int(.08 * SR), mode='same')
    duck = 1 - .45 * np.clip(energy / (energy.max() + 1e-9) * 3, 0, 1)
    stereo = mix * duck + np.vstack([fx, fx])
    stereo = np.tanh(stereo * 1.4) / np.tanh(1.4)
    stereo *= .89 / (np.abs(stereo).max() + 1e-9)
    pcm = (stereo.T * 32767).astype('<i2')
    with wave.open(out_path, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    print(f'wrote {out_path}: {seconds:.1f}s, {len(data["cues"])} cues')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
