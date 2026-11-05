"""Local, count-free speaker tracking and gain-invariant scoring features.

Models are used for who-spoke-when, never for emotion classification. Ambiguous
or overlapping speech has no volume score. No voice embeddings are persisted.
"""
from pathlib import Path
import hashlib
import os
import urllib.request
import numpy as np

SR = 16000
MODEL_FILES = {
    'segmentation.onnx': ('speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2', '220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079'),
    'embedding.onnx': ('speaker-recongition-models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx', '357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b'),
}


def ensure_models(model_home, progress=lambda *_: None):
    import tarfile
    home = Path(model_home) / 'speakers'
    home.mkdir(parents=True, exist_ok=True)
    for name, (asset, digest) in MODEL_FILES.items():
        target = home / name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
            continue
        progress('Downloading free local speaker models (first use only)')
        temporary = home / (name + '.download')
        try:
            with urllib.request.urlopen('https://github.com/k2-fsa/sherpa-onnx/releases/download/' + asset, timeout=30) as response, temporary.open('wb') as out:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
            if name == 'segmentation.onnx':
                with tarfile.open(temporary) as archive:
                    for member in archive.getmembers():
                        if Path(member.name).name == 'model.onnx':
                            target.write_bytes(archive.extractfile(member).read())
                        elif Path(member.name).name in {'LICENSE', 'README.md'}:
                            (home / ('SEGMENTATION-' + Path(member.name).name)).write_bytes(archive.extractfile(member).read())
            else:
                temporary.replace(target)
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                target.unlink(missing_ok=True)
                raise ValueError('Speaker model integrity check failed')
        finally:
            temporary.unlink(missing_ok=True)
    return home


def unit(vector):
    vector = np.asarray(vector, dtype=np.float32)
    return vector / max(float(np.linalg.norm(vector)), 1e-8)


def detect_speakers(audio, model_home, progress=lambda *_: None):
    """180-second cores bound inference memory; embeddings join voices across cores.

    Clustering estimates its own count. Speaker IDs are local anonymous labels,
    not identities. This does not impose a fixed maximum commentator count.
    """
    import sherpa_onnx as so
    home = ensure_models(model_home, lambda message: progress(0, message))
    threads = max(1, min(4, os.cpu_count() or 1))
    embedding_config = so.SpeakerEmbeddingExtractorConfig(model=str(home / 'embedding.onnx'), num_threads=threads)
    config = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(home / 'segmentation.onnx')),
            num_threads=threads),
        embedding=embedding_config,
        clustering=so.FastClusteringConfig(num_clusters=-1, threshold=.5),
        min_duration_on=.3, min_duration_off=.3)
    if not config.validate():
        raise ValueError('Invalid local speaker model configuration')
    diarizer, extractor = so.OfflineSpeakerDiarization(config), so.SpeakerEmbeddingExtractor(embedding_config)
    profiles, turns = [], []
    duration = len(audio) / SR
    for core_start in range(0, len(audio), 180 * SR):
        core_end = min(len(audio), core_start + 180 * SR)
        a, b = max(0, core_start - 5 * SR), min(len(audio), core_end + 5 * SR)
        block = np.ascontiguousarray(audio[a:b], dtype=np.float32)
        def callback(processed, total):
            fraction = (core_start + (core_end - core_start) * processed / max(1, total)) / len(audio)
            progress(fraction, f'Detecting commentator voices: {fraction * duration / 60:.1f} / {duration / 60:.1f} minutes')
            return 0
        local = diarizer.process(block, callback).sort_by_start_time()
        mapping, used_profiles = {}, set()
        for label in sorted({s.speaker for s in local}):
            # Exclude simultaneous speech when building a voice reference.
            candidates = [s for s in local if s.speaker == label and s.end - s.start >= 1 and not any(t.speaker != label and min(s.end, t.end) > max(s.start, t.start) for t in local)]
            vectors = []
            for segment in sorted(candidates, key=lambda s: s.end - s.start, reverse=True)[:3]:
                sound = block[int(segment.start * SR):int(min(segment.end, segment.start + 6) * SR)].copy()
                sound *= min(100, .1 / max(float(np.sqrt(np.mean(sound ** 2))), 1e-6))
                stream = extractor.create_stream()
                stream.accept_waveform(sample_rate=SR, waveform=sound)
                stream.input_finished()
                if extractor.is_ready(stream):
                    vectors.append(unit(extractor.compute(stream)))
            if not vectors:
                mapping[label] = None
                continue
            vector = unit(np.mean(vectors, axis=0))
            similarities = np.array([float(np.dot(p, vector)) for p in profiles])
            # Distinct clusters in the same core cannot be collapsed just
            # because two commentators have similar-sounding voices.
            for used in used_profiles:
                similarities[used] = -np.inf
            best = int(np.argmax(similarities)) if len(similarities) else -1
            if best >= 0 and similarities[best] >= .6:
                mapping[label] = best
                profiles[best] = unit(.8 * profiles[best] + .2 * vector)
            else:
                mapping[label] = len(profiles)
                profiles.append(vector)
            used_profiles.add(mapping[label])
        for s in local:
            start, end = max(core_start / SR, a / SR + s.start), min(core_end / SR, a / SR + s.end)
            if end > start:
                turns.append(dict(start=round(start, 3), end=round(end, 3), speaker=mapping[s.speaker]))
    return sorted(turns, key=lambda t: (t['start'], t['end']))


def normalize_speaker_features(bins, turns, words, audio=None):
    """Replace speech energy/pace cues with same-speaker deviations.

    Persistent gain offsets cancel in dB. A new voice needs >=8 seconds of
    uncontested reference; short, mixed and unknown speech gets no volume cue.
    Non-speech bins retain sound-event cues. Original measurements are retained.
    """
    assignments, speech_present = [], []
    for b in bins:
        coverage = {}
        overlaps = []
        for t in turns:
            if t['start'] >= b['end']:
                break
            start, end = max(b['start'], t['start']), min(b['end'], t['end'])
            if end > start:
                overlaps.append((start, end, t['speaker']))
                if t['speaker'] is not None:
                    coverage[t['speaker']] = coverage.get(t['speaker'], 0) + end - start
        mixed = any(min(x[1], y[1]) - max(x[0], y[0]) > .05 and x[2] != y[2] for j, x in enumerate(overlaps) for y in overlaps[j+1:])
        dominant = max(coverage, key=coverage.get) if coverage else None
        # A boundary bin is intentionally excluded from energy evidence.
        if mixed or len(coverage) != 1 or (dominant is not None and coverage[dominant] < .6 * (b['end'] - b['start'])):
            dominant = None
        assignments.append(dominant)
        speech_present.append(b['speech_fraction'] >= .2 or bool(overlaps))
    references = {}
    for i, b in enumerate(bins):
        label = assignments[i]
        if label is not None and b['speech_fraction'] >= .5 and not b['silence']:
            references.setdefault(label, []).append(i)
    baselines = {label: float(np.median([bins[i]['db'] for i in indices])) for label, indices in references.items() if sum(bins[i]['end'] - bins[i]['start'] for i in indices) >= 8}
    speech_energy = {}
    if audio is not None:
        # Calibrate from speech frames, rather than discarding reference speech
        # just because a short turn crosses a two-second display-bin boundary.
        for turn in turns:
            label = turn['speaker']
            if label is None:
                continue
            start = int(turn['start'] * SR)
            end = min(len(audio), int(turn['end'] * SR))
            block = np.asarray(audio[start:end], dtype=np.float32)
            size = len(block) // 320
            if not size:
                continue
            levels = 20 * np.log10(np.sqrt(np.mean(block[:size*320].reshape(-1,320)**2,axis=1)+1e-12))
            times = turn['start'] + (np.arange(size)+.5)*.02
            valid = levels > -55
            for other in turns:
                if other['start'] >= turn['end']:
                    break
                if other['speaker'] != label and other['end'] > turn['start']:
                    valid &= ~((times >= other['start']) & (times < other['end']))
            speech_energy.setdefault(label, []).append((times[valid],levels[valid]))
        speech_energy = {label:(np.concatenate([x[0] for x in chunks]),np.concatenate([x[1] for x in chunks])) for label,chunks in speech_energy.items()}
        baselines = {label:float(np.median(levels)) for label,(_,levels) in speech_energy.items() if len(levels)*.02 >= 8}
    # Count only this voice's words over this voice's speaking time. A fast
    # commentator entering the centered window must not inflate another voice.
    voice_words = {}
    cursor = 0
    for word in sorted(words, key=lambda w: (w['start'] + w['end']) / 2):
        mid = (word['start'] + word['end']) / 2
        while cursor < len(turns) and turns[cursor]['end'] <= mid:
            cursor += 1
        labels = set()
        for t in turns[cursor:]:
            if t['start'] > mid:
                break
            if mid < t['end']:
                labels.add(t['speaker'])
        if len(labels) == 1 and None not in labels:
            label = next(iter(labels))
            voice_words.setdefault(label, []).append(mid)
    voice_turns = {}
    voice_words = {label:np.asarray(times) for label,times in voice_words.items()}
    for turn in turns:
        voice_turns.setdefault(turn['speaker'], []).append(turn)
    for i, b in enumerate(bins):
        label = assignments[i]
        a, end = max(0, (b['start'] + b['end']) / 2 - 5), (b['start'] + b['end']) / 2 + 5
        times = voice_words.get(label, [])
        speaking = sum(max(0, min(end,t['end']) - max(a,t['start'])) for t in voice_turns.get(label, []))
        count = np.searchsorted(times, end) - np.searchsorted(times, a)
        b['speaker_wpm'] = round(float(count * 60 / speaking), 1) if speaking >= 2 else 0
    pace_baselines = {label: max(1, float(np.median([bins[i]['speaker_wpm'] for i in indices if bins[i]['speaker_wpm'] > 0] or [1]))) for label, indices in references.items() if label in baselines}
    previous, previous_voice = {}, None
    for i, b in enumerate(bins):
        label = assignments[i]
        b['raw_surge_db'] = b['surge_db']
        b['speaker'] = label
        b['speaker_baseline_db'] = round(baselines[label], 2) if label in baselines else None
        b['speaker_normalized'] = label in baselines
        if not speech_present[i]:
            b['signals']['pace'] = 0
            continue
        # Suppress uncertain speech energy; do not silently fall back to the
        # previous commentator's level if detection fails or voices overlap.
        if label not in baselines:
            b['surge_db'] = 0
            b['signals'].update(surge=0, loudness=0, pace=0, change=0)
            continue
        if label != previous_voice:
            b['signals']['change'] = 0
        previous_voice = label
        measured = b['db']
        if label in speech_energy:
            times, levels = speech_energy[label]
            values = levels[np.searchsorted(times,b['start']):np.searchsorted(times,b['end'])]
            if not len(values):
                b['surge_db'] = 0
                b['signals'].update(surge=0,loudness=0,pace=0)
                continue
            measured = float(np.median(values))
        residual = measured - baselines[label]
        b['relative_voice_db'] = round(residual, 2)
        history = [(time, value) for time, value in previous.get(label, []) if b['start'] - time <= 30]
        prior = float(np.median([v for _, v in history])) if history else 0
        # Require both a rise above normal delivery and a recent same-voice rise.
        rise = max(0., min(residual, residual - prior) - 1.)
        b['surge_db'] = round(rise, 2)
        b['signals']['surge'] = round(min(1., rise / 12), 5)
        b['signals']['loudness'] = round(float(np.clip((residual - 1) / 12, 0, 1)), 5)
        b['signals']['pace'] = round(float(np.clip((b['speaker_wpm'] / pace_baselines[label] - 1) / 1.0, 0, 1)), 5) if words and label in pace_baselines else 0
        history.append((b['start'], residual))
        previous[label] = history
    return dict(detected_speakers=len({t['speaker'] for t in turns if t['speaker'] is not None}), calibrated_speakers=len(baselines), turns=turns)
