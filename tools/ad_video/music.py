"""Background music composed in code (free to use in ads)."""
import wave


def make_music(seconds, path, rate=48000):
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
