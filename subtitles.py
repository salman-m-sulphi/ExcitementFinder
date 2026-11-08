"""Generate English SRT cues on the exported media's own timeline."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unicodedata import name

import numpy as np
from faster_whisper.vad import get_speech_timestamps, VadOptions

from analysis import SR


def stamp(ms):
    seconds, fraction = divmod(ms, 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d},{fraction:03d}'


def write_srt(video, duration, decode, translate):
    if not duration:
        raise ValueError('Could not measure the exported clip duration')
    cues, skipped, speech = [], 0, False
    # Restart language detection after a clear pause between speakers.
    vad = VadOptions(min_silence_duration_ms=1000, speech_pad_ms=300)
    with TemporaryDirectory(dir=video.parent, prefix='subtitle-') as directory:
        pcm = Path(directory) / 'audio.f32'
        decode(['-i', str(video), '-vn', '-map', '0:a:0', '-ac', '1',
                '-af', f'aresample={SR}:async=1:first_pts=0', '-t', str(duration),
                '-f', 'f32le', str(pcm)])
        samples = pcm.stat().st_size // 4
        if samples:
            audio = np.memmap(pcm, dtype='float32', mode='r')
            try:
                for core_start in range(0, samples, 30 * SR):
                    core_end = min(samples, core_start + 30 * SR)
                    a, b = max(0, core_start - 2 * SR), min(samples, core_end + 2 * SR)
                    window = np.array(audio[a:b])
                    for span in get_speech_timestamps(window, vad, sampling_rate=SR):
                        speech = True
                        offset = (a + span['start']) / SR
                        for segment in translate(window[span['start']:span['end']]):
                            start, end = segment.start + offset, segment.end + offset
                            if not core_start <= (start + end) * SR / 2 < core_end:
                                continue
                            line = ' '.join(segment.text.split())
                            if not line:
                                continue
                            if any(c.isalpha() and 'LATIN' not in name(c, '') for c in line):
                                skipped += 1
                                continue
                            cues.append((start, end, line))
            finally:
                audio._mmap.close()
    if speech and not cues:
        raise ValueError('Medium could not produce English cues for the detected speech')
    blocks = []
    limit, previous_end = int(duration * 1000), 0
    for start, end, line in sorted(cues):
        first = max(previous_end, round(start * 1000))
        last = min(limit, round(end * 1000))
        if last > first:
            blocks.append(f'{len(blocks) + 1}\n{stamp(first)} --> {stamp(last)}\n{line}\n')
            previous_end = last
    if speech and not blocks:
        raise ValueError('Medium could not produce English cues within the exported time range')
    subtitle = video.with_suffix('.srt')
    subtitle.write_text('\n'.join(blocks), encoding='utf-8')
    return {'filename': subtitle.name, 'status': 'ready' if blocks else 'empty',
            'cues': len(blocks), 'skipped': skipped}
