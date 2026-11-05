"""Deterministic audio features. Scores are heuristics, not probabilities."""
import math
import numpy as np

SR = 16000
BIN = 2.0
DEFAULT_WEIGHTS = dict(pace=40, surge=25, loudness=15, speech=10, change=10)


def normalize(values, mask=None):
    a = np.asarray(values, dtype=float)
    reference = a[np.asarray(mask, dtype=bool)] if mask is not None else a
    if not len(reference):
        return np.zeros_like(a)
    lo, hi = np.percentile(reference, [20, 95])
    if hi - lo < 1e-6:
        return np.zeros_like(a)
    return np.clip((a - lo) / (hi - lo), 0, 1)


def extract_features(audio, speech_intervals, words, progress=lambda *a: None):
    """Bounded FFT memory: process 2s bins, with 20ms analysis frames."""
    duration = len(audio) / SR
    count = math.ceil(duration / BIN)
    db, flux, quiet, speech = [], [], [], []
    previous = np.zeros(161)
    window = np.hanning(320)
    interval_index = 0
    for i in range(count):
        start, end = i * BIN, min(duration, (i + 1) * BIN)
        block = np.asarray(audio[int(start * SR):int(end * SR)], dtype=np.float32)
        padded = np.pad(block, (0, (-len(block)) % 320)).reshape(-1, 320)
        rms = np.sqrt(np.mean(padded ** 2, axis=1) + 1e-12)
        frame_db = 20 * np.log10(rms)
        db.append(float(20 * np.log10(np.sqrt(np.mean(block ** 2) + 1e-12))))
        quiet.append(float(np.mean(frame_db < -55)))
        spectrum = np.abs(np.fft.rfft(padded * window, axis=1))
        spectrum /= np.maximum(spectrum.sum(axis=1, keepdims=True), 1e-9)
        differences = spectrum - np.vstack([previous, spectrum[:-1]])
        # Ignore spectral change during near-silence.
        flux.append(float(np.mean(np.maximum(differences, 0).sum(axis=1) * (frame_db > -55))))
        previous = spectrum[-1]
        while interval_index < len(speech_intervals) and speech_intervals[interval_index][1] <= start:
            interval_index += 1
        overlap = 0.0
        for j in range(interval_index, len(speech_intervals)):
            a, b = speech_intervals[j]
            if a >= end:
                break
            overlap += max(0, min(end, b) - max(start, a))
        speech.append(min(1, overlap / (end - start)))
        if i % 300 == 0:
            progress(55 + 15 * i / max(1, count), 'Measuring sound and speech features')

    db = np.array(db)
    # Causal trailing 30 seconds, excluding the current bin. A sudden jump
    # should score differently from a continuously loud soundtrack.
    baseline = np.maximum(-55, np.array([np.median(db[max(0, i - 15):i]) if i else db[0] for i in range(count)]))
    surge_db = np.maximum(0, db - baseline)
    mids = np.array([(w['start'] + w['end']) / 2 for w in words])
    pace = []
    for i in range(count):
        center = min(duration, (i + .5) * BIN)
        a, b = max(0, center - 5), min(duration, center + 5)
        n = np.searchsorted(mids, b, side='left') - np.searchsorted(mids, a, side='left')
        pace.append(float(n * 60 / max(.1, b - a)))
    # 70% within-recording pace; 30% absolute 240 word-groups/min reference.
    pace_signal = .7 * normalize(pace) + .3 * np.clip(np.array(pace) / 240, 0, 1)
    active = np.array(quiet) < .95
    signals = dict(pace=pace_signal, surge=np.clip(surge_db / 12, 0, 1),
                   loudness=normalize(db, active), speech=np.array(speech), change=normalize(flux, active))
    bins = []
    for i in range(count):
        bins.append(dict(start=i * BIN, end=min(duration, (i + 1) * BIN),
                         db=round(float(db[i]), 2), surge_db=round(float(surge_db[i]), 2),
                         wpm=round(pace[i], 1), speech_fraction=round(speech[i], 3),
                         quiet_fraction=round(quiet[i], 3), silence=quiet[i] >= .95,
                         signals={k: round(float(v[i]), 5) for k, v in signals.items()}))
    return bins


def score_bins(bins, weights=None, has_words=True):
    weights = dict(DEFAULT_WEIGHTS if weights is None else weights)
    if not has_words:
        weights['pace'] = 0
    denominator = sum(weights.values()) or 1
    return [0 if b['silence'] else round(100 * sum(weights.get(k, 0) * v for k, v in b['signals'].items()) / denominator, 1) for b in bins]
