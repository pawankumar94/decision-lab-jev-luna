"""Synthesize the film soundtrack from the timeline's cue list. No samples, no downloads, no licences.

Usage: python3 src/film_audio.py renders/film-cues.json renders/film-audio.wav [chiptune|pad]
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
    n = int(.05 * SR); return level * .15 * (sine(2600, .05) * env(n, .001, .012, 6) + .3 * band_noise(.05, 3000, 9000) * env(n, .0005, .006, 6))


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


# ---------- original chiptune score (default) ----------
# Retro 8-bit style written for this film: pulse lead, pulse arpeggio, triangle bass, noise drums.
# Original melody over a I-V-vi-IV progression in A major, matching the effects' key.
BEAT = 0.425          # 141.2 BPM: each robot move (0.85 s) lands on every second beat
GRID0 = 0.07          # beat grid phase so beats coincide with the move ticks
A_MAJOR = {'I': (57, [57, 61, 64]), 'V': (52, [52, 56, 59]), 'vi': (54, [54, 57, 61]), 'IV': (50, [50, 54, 57])}
PROG = ['I', 'V', 'vi', 'IV', 'I', 'V', 'vi', 'IV']
# (start beat, length in beats, MIDI note) per bar; composed in C and transposed down 3 semitones to A.
LEAD = [
    [(0, 1, 76), (1, 1, 79), (2, .5, 84), (2.5, .5, 83), (3, 1, 79)],
    [(0, 1, 74), (1, 1, 79), (2, 2, 83)],
    [(0, 1, 84), (1, .5, 83), (1.5, .5, 81), (2, 1, 76), (3, 1, 81)],
    [(0, 1, 77), (1, 1, 81), (2, 2, 84)],
    [(0, .5, 79), (.5, .5, 76), (1, 1, 72), (2, 1, 76), (3, 1, 79)],
    [(0, 1, 71), (1, 1, 74), (2, .5, 79), (2.5, .5, 77), (3, 1, 74)],
    [(0, 1, 76), (1, 1, 72), (2, 2, 69)],
    [(0, 1, 77), (1, 1, 76), (2, 1, 74), (3, 1, 79)],
]
ENDING = [(0, 1, 76), (1, 1, 74), (2, 2, 72)]  # resolves to the tonic over the last bar


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def lowpass(x, cutoff):
    spec = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    spec *= 1 / np.sqrt(1 + (f / cutoff) ** 4)
    return np.fft.irfft(spec, len(x))


def note_env(n, release=.03):
    t = np.arange(n) / SR; e = np.minimum(1, t / .004) * (.65 + .35 * np.exp(-t / .08))
    r = int(release * SR); e[-r:] *= np.linspace(1, 0, r) if n > r else 1
    return e


def pulse(f, dur, duty):
    t = np.arange(int(dur * SR)) / SR
    return np.where((t * f) % 1 < duty, 1.0, -1.0)


def tri(f, dur):
    t = np.arange(int(dur * SR)) / SR
    return 2 * np.abs(2 * ((t * f) % 1) - 1) - 1


def place(track, t, clip, gain):
    i = int(t * SR)
    if i >= len(track) or i < 0: return
    j = min(len(track), i + len(clip)); track[i:j] += gain * clip[:j - i]


def section_at(t, schedule):
    for name, (a, b) in schedule.items():
        if a <= t < b: return name
    return 'end'


def chiptune(seconds, schedule):
    n = int(seconds * SR)
    lead, arp, bass, drums = (np.zeros(n) for _ in range(4))
    bar_len = 4 * BEAT
    end_start = schedule.get('end', [seconds - 14, seconds])[0]
    last_bar = int((seconds - 2.2 - GRID0) // bar_len) - 1
    b = 0
    while GRID0 + b * bar_len < seconds - 1.5:
        t0 = GRID0 + b * bar_len
        sec = section_at(t0 + .01, schedule)
        root, chord = A_MAJOR[PROG[b % 8]]
        final = b >= last_bar
        if final: root, chord = A_MAJOR['I']
        # Triangle bass: root and octave in eighths (quiet half-time in the reading scene).
        step = BEAT if sec == 'hybrid' else BEAT / 2
        for k in range(int(round(bar_len / step))):
            m = root - 12 + (12 if k % 4 == 2 else 0)
            place(bass, t0 + k * step, tri(midi_hz(m), step * .9) * note_env(int(step * .9 * SR)), .55)
        # Pulse arpeggio in sixteenths, thin 12.5% duty.
        if sec != 'title' or b % 2 == 0:
            for k in range(16):
                m = chord[k % 3] + 12 * (1 + (k // 3) % 2)
                d = BEAT / 4 * .8
                place(arp, t0 + k * BEAT / 4, pulse(midi_hz(m), d, .125) * note_env(int(d * SR), .01), .16)
        # Lead melody: full during driving, results and the ending; resting while viewers read notes.
        if sec in ('nav', 'navres', 'results', 'end'):
            notes = ENDING if final else LEAD[b % 8]
            for sb, lb, m in notes:
                d = lb * BEAT * .92
                place(lead, t0 + sb * BEAT, pulse(midi_hz(m - 3), d, .25) * note_env(int(d * SR), .04), .32)
        # Noise-channel drums.
        if sec != 'title':
            for k in range(8):
                tt = t0 + k * BEAT / 2
                hat = rng.standard_normal(int(.03 * SR)) * np.exp(-np.arange(int(.03 * SR)) / (.006 * SR))
                place(drums, tt, hat, .10 if k % 2 else .05)
            if sec != 'hybrid':
                for k in (0, 2):
                    kn = int(.18 * SR); kick = np.sin(2 * np.pi * np.cumsum(np.linspace(140, 45, kn)) / SR) * np.exp(-np.arange(kn) / (.05 * SR))
                    place(drums, t0 + k * BEAT, kick, .9)
                for k in (1, 3):
                    sn = int(.12 * SR); snare = rng.standard_normal(sn) * np.exp(-np.arange(sn) / (.03 * SR))
                    place(drums, t0 + k * BEAT, snare, .28)
        b += 1
        if final: break
    # Final sustained tonic chord under the end card.
    t_end = GRID0 + b * bar_len
    hold = max(.5, seconds - t_end)
    for m in A_MAJOR['I'][1]:
        place(lead, t_end, pulse(midi_hz(m + 12), hold, .5) * np.exp(-np.arange(int(hold * SR)) / (1.2 * SR)), .10)
    mix = lowpass(lead, 5200) + lowpass(arp, 4200) + lowpass(bass, 2500) + lowpass(drums, 9000)
    # Scene dynamics: the reading scene sits lower so the incident notes stay in focus.
    level = np.ones(n)
    for name, (a, b2) in schedule.items():
        if name == 'hybrid':
            i, j = int(a * SR), min(n, int(b2 * SR)); level[i:j] = .7
    level = np.convolve(level, np.ones(int(.4 * SR)) / int(.4 * SR), mode='same')
    fade = np.ones(n); fi, fo = int(1.2 * SR), int(2.5 * SR); fade[:fi] = np.linspace(0, 1, fi); fade[-fo:] = np.linspace(1, 0, fo)
    mono = mix * level * fade * .07
    return np.vstack([mono * .96 + np.roll(arp, int(.012 * SR)) * level * fade * .004, mono * .96])


def main(cue_path, out_path):
    data = json.loads(open(cue_path).read())
    seconds = data['duration'] + 0.5
    music = (sys.argv[3] if len(sys.argv) > 3 else 'chiptune')
    mix = chiptune(seconds, data.get('schedule', {})) if music == 'chiptune' else bed(seconds)
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
