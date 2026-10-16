"""Background music composed in code (free to use in ads).

    make_music(seconds, path, style='pop' | 'funk' | 'tropical' | 'cinematic' | 'lofi')

Each style has its own tempo, key, chords, instruments and drum feel, so reels don't all sound the same.
"""
import wave

import numpy as np

RATE = 48000
NOTE = {n: 440 * 2 ** ((i - 9) / 12) for i, n in enumerate(['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'])}


def hz(name):
    """'A4' → 440.0, 'C#3' → …"""
    pitch, octave = name[:-1], int(name[-1])
    return NOTE[pitch] * 2 ** (octave - 4)


def make_music(seconds, path, style='pop', rate=RATE):
    makers = {'pop': make_pop, 'funk': _funk, 'tropical': _tropical, 'cinematic': _cinematic, 'lofi': _lofi}
    return makers[style](seconds, path, rate)


# ── building blocks ──

class _Track:
    def __init__(self, seconds, rate, seed):
        self.rate, self.n = rate, int(seconds * rate)
        self.out = np.zeros(self.n)
        self.rng = np.random.default_rng(seed)
        self.seconds = seconds

    def add(self, at, sig, gain):
        i0 = int(at * self.rate)
        if i0 >= self.n or i0 < 0:
            return
        m = min(len(sig), self.n - i0)
        self.out[i0:i0 + m] += gain * sig[:m]

    def t(self, dur):
        return np.arange(int(dur * self.rate)) / self.rate

    # instruments
    def kick(self, punch=0.03, body=0.16, low=45):
        t = self.t(0.35)
        return np.sin(2 * np.pi * np.cumsum(low + 75 * np.exp(-t / punch)) / self.rate) * np.exp(-t / body)

    def snare(self, tone=190, decay=0.12):
        t = self.t(0.3)
        noise = _hp(self.rng.standard_normal(len(t)), 5) * np.exp(-t / decay)
        return 0.7 * noise + 0.5 * np.sin(2 * np.pi * tone * t) * np.exp(-t / 0.05)

    def hat(self, decay=0.018):
        t = self.t(0.08)
        return _hp(self.rng.standard_normal(len(t)), 2) * np.exp(-t / decay)

    def shaker(self):
        t = self.t(0.12)
        env = np.minimum(1, t / 0.02) * np.exp(-t / 0.04)
        return _hp(self.rng.standard_normal(len(t)), 3) * env

    def clap(self):
        t = self.t(0.25)
        return _hp(self.rng.standard_normal(len(t)), 6) * np.exp(-t / 0.07)

    def tone(self, f, dur, decay, harmonics=((1, 1.0),), attack=0.004, vibrato=0.0):
        t = self.t(dur)
        ph = 2 * np.pi * f * t + (vibrato * np.sin(2 * np.pi * 5 * t) if vibrato else 0)
        sig = sum(a * np.sin(h * ph) for h, a in harmonics)
        return sig * np.exp(-t / decay) * np.minimum(1, t / attack)

    def marimba(self, f, dur=0.6):
        t = self.t(dur)
        return (np.sin(2 * np.pi * f * t) * np.exp(-t / 0.35) + 0.35 * np.sin(2 * np.pi * f * 3.93 * t) * np.exp(-t / 0.06)
                + 0.12 * np.sin(2 * np.pi * f * 9.2 * t) * np.exp(-t / 0.02)) * np.minimum(1, t / 0.002)

    def clav(self, f, dur=0.18):
        t = self.t(dur)
        pulse = np.sign(np.sin(2 * np.pi * f * t)) * 0.6 + np.sin(2 * np.pi * 2 * f * t) * 0.4
        return _lp(pulse, 4) * np.exp(-t / 0.07)

    def epiano(self, f, dur, decay=1.2):
        t = self.t(dur)
        sig = np.sin(2 * np.pi * f * t + 0.8 * np.sin(2 * np.pi * f * t) * np.exp(-t / 0.3))     # soft FM bell
        return sig * np.exp(-t / decay) * np.minimum(1, t / 0.01) * (1 + 0.15 * np.sin(2 * np.pi * 4.5 * t))

    def pad(self, freqs, dur, attack=0.8):
        t = self.t(dur)
        sig = np.zeros(len(t))
        for f in freqs:
            for det in (-0.004, 0.0, 0.004):                    # three slightly detuned saws per note
                ph = (f * (1 + det) * t) % 1.0
                sig += 2 * ph - 1
        sig = _lp(sig, 24) / (3 * len(freqs))
        env = np.minimum(1, t / attack) * np.minimum(1, (dur - t) / 0.6)
        return sig * env

    def finish(self, path, glue=1.6, level=0.7, fade_in=0.15, fade_out=1.2):
        t = np.arange(self.n) / self.rate
        y = _lp(self.out, 3)
        y *= np.minimum(1, t / fade_in) * np.minimum(1, (self.seconds - t) / fade_out)
        y = np.tanh(glue * y / (np.abs(y).max() + 1e-9)) / np.tanh(glue) * level
        with wave.open(path, 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(self.rate)
            w.writeframes((np.clip(y, -1, 1) * 32767).astype('<i2').tobytes())
        return path


def _hp(x, k):
    return x - np.convolve(x, np.ones(k) / k, mode='same')


def _lp(x, k):
    return np.convolve(x, np.ones(k) / k, mode='same')


# ── styles ──

def _funk(seconds, path, rate):
    """Playful funk groove, 104 bpm, E minor: syncopated bass, clavinet stabs on the 16ths, tight drums."""
    tr = _Track(seconds, rate, 21)
    beat = 60 / 104
    bar, s16 = 4 * beat, beat / 4
    kick, snare, hat = tr.kick(punch=0.02, body=0.12), tr.snare(), tr.hat(0.012)
    chords = [(['E3', 'G3', 'B3', 'D4'], 'E2'), (['A3', 'C#4', 'E4', 'G4'], 'A2'),
              (['E3', 'G3', 'B3', 'D4'], 'E2'), (['B3', 'D4', 'F#4', 'A4'], 'B2')]
    bass_rhythm = [0, 3, 6, 8, 10, 11, 14]            # in 16ths
    clav_rhythm = [2, 5, 7, 10, 13, 15]
    for b in range(int(seconds / bar) + 1):
        t0 = b * bar
        tones, root = chords[b % 4]
        for k in (0, 6, 10):                          # kick: 1, the "a" of 2, and 3
            tr.add(t0 + k * s16, kick, 0.85)
        for k in (4, 12):
            tr.add(t0 + k * s16, snare, 0.45)
        for k in range(16):
            tr.add(t0 + k * s16, hat, 0.10 if k % 2 else 0.16)
        for i, k in enumerate(bass_rhythm):
            f = hz(root) * (2 if i in (3, 5) else 1)
            tr.add(t0 + k * s16, tr.tone(f, 0.22, 0.12, ((1, 1), (2, 0.5), (3, 0.25))), 0.55)
        for k in clav_rhythm:
            for nme in tones[:3]:
                tr.add(t0 + k * s16, tr.clav(hz(nme)), 0.07)
        if b % 2 == 1:                                # a little lead lick every other bar
            for k, nme in ((0, 'B4'), (2, 'D5'), (3, 'E5'), (6, 'D5'), (8, 'B4')):
                tr.add(t0 + k * s16, tr.tone(hz(nme), 0.3, 0.15, ((1, 1), (2, 0.3)), vibrato=0.4), 0.12)
    return tr.finish(path, glue=1.8)


def _tropical(seconds, path, rate):
    """Light tropical house, 100 bpm, F major: marimba patterns, shaker, soft four-on-the-floor, warm bass."""
    tr = _Track(seconds, rate, 31)
    beat = 60 / 100
    bar, s16 = 4 * beat, beat / 4
    kick, clap, shaker = tr.kick(punch=0.025, body=0.14, low=50), tr.clap(), tr.shaker()
    prog = [(['F4', 'A4', 'C5'], 'F2'), (['C4', 'E4', 'G4'], 'C2'), (['D4', 'F4', 'A4'], 'D2'), (['A#3', 'D4', 'F4'], 'A#1')]
    pattern = [0, 3, 6, 8, 10, 12, 14]                # marimba arpeggio in 16ths
    for b in range(int(seconds / bar) + 1):
        t0 = b * bar
        tones, root = prog[b % 4]
        for k in range(4):
            tr.add(t0 + k * beat, kick, 0.7)
            if k in (1, 3):
                tr.add(t0 + k * beat, clap, 0.22)
        for k in range(16):
            tr.add(t0 + k * s16, shaker, 0.16 if k % 2 else 0.08)
        for i, k in enumerate(pattern):
            nme = tones[i % 3]
            f = hz(nme) * (2 if i in (3, 6) else 1)
            tr.add(t0 + k * s16, tr.marimba(f), 0.20)
        for k in (0, 1.5, 2.5, 3.5):                  # off-beat bass
            tr.add(t0 + k * beat, tr.tone(hz(root) * 2, 0.4, 0.2, ((1, 1), (2, 0.3))), 0.45)
        tr.add(t0, tr.pad([hz(n) for n in tones], bar, attack=0.3), 0.10)
    return tr.finish(path, glue=1.5, level=0.68)


def _cinematic(seconds, path, rate):
    """Cinematic build, 96 bpm, A minor: pulsing 8th-note bass, wide pads, toms that build to a hit near the end."""
    tr = _Track(seconds, rate, 41)
    beat = 60 / 96
    bar = 4 * beat
    prog = [(['A3', 'C4', 'E4'], 'A1'), (['F3', 'A3', 'C4'], 'F1'), (['C4', 'E4', 'G4'], 'C2'), (['G3', 'B3', 'D4'], 'G1')]
    tom = lambda f: tr.tone(f, 0.5, 0.18, ((1, 1), (1.5, 0.3)))
    kick = tr.kick(punch=0.04, body=0.3, low=40)
    bars = int(seconds / bar) + 1
    for b in range(bars):
        t0 = b * bar
        tones, root = prog[b % 4]
        build = min(1.0, b / max(1, bars - 2))          # 0 → 1 over the reel
        tr.add(t0, tr.pad([hz(n) for n in tones] + [hz(tones[0]) / 2], bar + 0.4, attack=1.0), 0.22)
        for k in range(8):                            # pulse bass
            tr.add(t0 + k * beat / 2, tr.tone(hz(root) * 2, 0.24, 0.12, ((1, 1), (2, 0.6), (3, 0.3))), 0.30 + 0.2 * build)
        tr.add(t0, kick, 0.6 + 0.3 * build)
        tr.add(t0 + 2 * beat, kick, 0.4 + 0.4 * build)
        if build > 0.4:                               # toms join halfway, then 16ths in the last bars
            step = beat / 2 if build < 0.85 else beat / 4
            k = 0.0
            while k < bar - 1e-6:
                tr.add(t0 + k, tom(110 if int(k / step) % 2 else 82), 0.18 * build)
                k += step
        if b % 2 == 1:                                # a slow, hopeful melody
            for k, nme in ((0, 'E5'), (1.5, 'D5'), (2, 'C5'), (3, 'E5')):
                tr.add(t0 + k * beat, tr.tone(hz(nme), 1.2, 0.8, ((1, 1), (2, 0.25), (3, 0.1)), attack=0.05), 0.11)
    hit_at = max(0.0, seconds - 4.6)                  # big hit as the end card lands
    tr.add(hit_at, tr.kick(punch=0.05, body=0.6, low=35), 1.0)
    tr.add(hit_at, tr.pad([hz('A2'), hz('E3'), hz('A3'), hz('C4')], 4.4, attack=0.05), 0.35)
    return tr.finish(path, glue=1.6, level=0.7, fade_out=1.6)


def _lofi(seconds, path, rate):
    """Warm lo-fi, 84 bpm with swing: soft electric piano 7th chords, dusty drums, vinyl crackle."""
    tr = _Track(seconds, rate, 51)
    beat = 60 / 84
    bar = 4 * beat
    swing = beat / 2 * 0.62
    kick, snare, hat = tr.kick(punch=0.03, body=0.2, low=48), tr.snare(tone=170, decay=0.09), tr.hat(0.02)
    prog = [(['D4', 'F4', 'A4', 'C5'], 'D2'), (['G3', 'B3', 'D4', 'F4'], 'G1'), (['C4', 'E4', 'G4', 'B4'], 'C2'),
            (['A3', 'C4', 'E4', 'G4'], 'A1')]
    for b in range(int(seconds / bar) + 1):
        t0 = b * bar
        tones, root = prog[b % 4]
        for i, nme in enumerate(tones):               # gently rolled chord
            tr.add(t0 + i * 0.03, tr.epiano(hz(nme), bar, decay=1.6), 0.10)
        tr.add(t0 + 2 * beat + swing, tr.epiano(hz(tones[2]) * 2, beat, decay=0.6), 0.06)
        tr.add(t0, tr.tone(hz(root), bar * 0.9, 1.2, ((1, 1), (2, 0.2))), 0.4)
        for k in (0, 2.5):
            tr.add(t0 + k * beat, kick, 0.55)
        for k in (1, 3):
            tr.add(t0 + k * beat, snare, 0.3)
        for k in range(4):
            tr.add(t0 + k * beat, hat, 0.07)
            tr.add(t0 + k * beat + swing, hat, 0.05)
    crackle = np.zeros(tr.n)
    idx = tr.rng.integers(0, tr.n, size=int(seconds * 12))
    crackle[idx] = tr.rng.uniform(-1, 1, size=len(idx))
    tr.out += 0.05 * _lp(crackle, 3) + 0.004 * tr.rng.standard_normal(tr.n)
    return tr.finish(path, glue=1.3, level=0.62)




def make_pop(seconds, path, rate=48000):
    """An upbeat, catchy bed composed here (free to use in ads): 112 bpm, C → G → Am → F,
    four-on-the-floor kick, claps, hi-hats, bassline, chord stabs and a short melody hook."""
    import numpy as np
    n = int(seconds * rate)
    out = np.zeros(n)
    rng = np.random.default_rng(11)
    beat = 60 / 112
    bar = 4 * beat

    def add(at, sig, gain):
        i0 = int(at * rate)
        if i0 >= n:
            return
        m = min(len(sig), n - i0)
        out[i0:i0 + m] += gain * sig[:m]

    def tone(f, dur, decay, harmonics=((1, 1.0),), attack=0.004):
        tt = np.arange(int(dur * rate)) / rate
        sig = sum(a * np.sin(2 * np.pi * f * h * tt) for h, a in harmonics)
        return sig * np.exp(-tt / decay) * np.minimum(1, tt / attack)

    def highpass(x, k=8):
        return x - np.convolve(x, np.ones(k) / k, mode='same')

    def lowpass(x, k=6):
        return np.convolve(x, np.ones(k) / k, mode='same')

    kt = np.arange(int(0.35 * rate)) / rate                      # kick: pitch drop 120 → 45 Hz
    kick = np.sin(2 * np.pi * np.cumsum(45 + 75 * np.exp(-kt / 0.03)) / rate) * np.exp(-kt / 0.16)
    ct = np.arange(int(0.25 * rate)) / rate
    clap = highpass(rng.standard_normal(len(ct)), 6) * np.exp(-ct / 0.07)
    ht = np.arange(int(0.08 * rate)) / rate
    hat = highpass(rng.standard_normal(len(ht)), 2) * np.exp(-ht / 0.018)

    C = {'C3': 130.81, 'D3': 146.83, 'E3': 164.81, 'F3': 174.61, 'G3': 196.0, 'A3': 220.0, 'B3': 246.94,
         'C4': 261.63, 'D4': 293.66, 'E4': 329.63, 'F4': 349.23, 'G4': 392.0, 'A4': 440.0, 'B4': 493.88,
         'C5': 523.25, 'D5': 587.33, 'E5': 659.25, 'G5': 783.99, 'A5': 880.0}
    prog = [  # (bass root, chord tones)
        (65.41, ['C4', 'E4', 'G4']), (98.0, ['B3', 'D4', 'G4']), (110.0, ['C4', 'E4', 'A4']), (87.31, ['C4', 'F4', 'A4'])]
    hook = [('E5', 0, 1), ('G5', 1, 1), ('A5', 2, 1.5), ('G5', 3.5, .5), ('E5', 4, 1), ('D5', 5, 1), ('C5', 6, 2),
            ('E5', 8, 1), ('G5', 9, 1), ('A5', 10, 1.5), ('G5', 11.5, .5), ('E5', 12, 1), ('G5', 13, 1), ('C5', 14, 2)]
    piano = ((1, 1.0), (2, 0.45), (3, 0.2), (4, 0.08))
    bars = int(seconds / bar) + 1
    for b in range(bars):
        t0 = b * bar
        root, tones = prog[b % 4]
        for k in range(4):                                       # drums
            add(t0 + k * beat, kick, 0.9)
            add(t0 + k * beat + beat / 2, hat, 0.16)
            if k in (1, 3):
                add(t0 + k * beat, clap, 0.32)
        for k, at in enumerate([0, 1.5, 2, 3, 3.5]):             # syncopated bassline
            add(t0 + at * beat, tone(root * (2 if k == 3 else 1), 0.5, 0.22, ((1, 1), (2, 0.35), (3, 0.12))), 0.55)
        for at in (0.5, 1.5, 2.5, 3.5):                          # off-beat chord stabs
            for nme in tones:
                add(t0 + at * beat, tone(C[nme], 0.45, 0.16, piano), 0.11)
        if b >= 1:                                               # melody hook from bar 2 (let the intro breathe)
            cyc = (b - 1) % 4
            for nme, st, ln in hook:
                if cyc * 4 <= st < cyc * 4 + 4:
                    add(t0 + (st - cyc * 4) * beat, tone(C[nme], ln * beat + 0.3, 0.35 + 0.2 * ln, piano), 0.16)
    y = lowpass(out, 3)
    t = np.arange(n) / rate
    y *= np.minimum(1, t / 0.15) * np.minimum(1, (seconds - t) / 1.2)
    y = np.tanh(1.6 * y / (np.abs(y).max() + 1e-9)) / np.tanh(1.6)          # gentle glue / saturation
    y *= 0.7
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((y * 32767).astype('<i2').tobytes())
    return path
