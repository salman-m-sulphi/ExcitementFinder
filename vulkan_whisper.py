"""Word-timed Whisper transcription through the cross-vendor Vulkan backend."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from huggingface_hub import hf_hub_download
from scipy.io import wavfile

CLI = Path(__file__).resolve().parent / 'whisper_vulkan' / 'whisper-cli.exe'
MODEL_REVISION = '5359861c739e955e79d9a303bcbc70fb988958b1'


def adapters():
    if os.name != 'nt' or not CLI.is_file():
        return []
    try:
        probe = subprocess.run([str(CLI), '--help'], cwd=CLI.parent, capture_output=True,
                               encoding='utf-8', errors='replace',
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    detected = re.findall(r'^ggml_vulkan: (\d+) = ', probe.stderr, re.MULTILINE)
    requested = os.environ.get('EXCITEMENT_VULKAN_DEVICE')
    return [requested] if requested in detected else detected


def transcribe(name, audio, sample_rate, language, cache, adapter, translate=False):
    try:
        model = hf_hub_download('ggerganov/whisper.cpp', f'ggml-{name}-q8_0.bin',
                                revision=MODEL_REVISION, cache_dir=cache)
        with tempfile.TemporaryDirectory(prefix='excite-vulkan-') as directory:
            source = Path(directory) / 'audio.wav'
            output = Path(directory) / 'words'
            wavfile.write(source, sample_rate, (np.clip(audio, -1, 1) * 32767).astype(np.int16))
            result = subprocess.run(
                [str(CLI), '-m', model, '-f', str(source), '-l', language or 'auto',
                 '-dev', adapter, '-t', str(max(1, min(8, os.cpu_count() or 4))),
                 '-bs', '3', '-mc', '0', '-ml', '1', '-sow', '-ojf', '-of', str(output),
                 *(['-tr'] if translate else [])],
                cwd=CLI.parent, capture_output=True, encoding='utf-8', errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=900)
            if result.returncode or not re.search(r'using Vulkan\d+ backend', result.stderr):
                raise RuntimeError('No usable Vulkan GPU was selected by Whisper.')
            document = json.loads(output.with_suffix('.json').read_text(encoding='utf-8', errors='replace'))
        groups = word_segments(document, len(audio) / sample_rate)
        for group in groups:
            group.text = ''.join(word.word for word in group.words)
        return groups, SimpleNamespace(language=document['result']['language'])
    except Exception as exc:
        raise RuntimeError(f'Vulkan Whisper could not transcribe this window. {exc}') from exc


def word_segments(document, duration):
    # The CLI emits real word boundaries with --split-on-word. Rejoin words
    # into readable transcript rows while keeping their individual timestamps.
    groups = []
    for item in document['transcription']:
        if not item['text'].strip():
            continue
        start = max(0, min(duration, item['offsets']['from'] / 1000))
        end = max(start, min(duration, item['offsets']['to'] / 1000))
        probabilities = [token['p'] for token in item['tokens'] if token['id'] < 50257]
        word = SimpleNamespace(word=item['text'], start=start, end=end,
                               probability=sum(probabilities) / max(1, len(probabilities)))
        if not groups or start - groups[-1].end > 1 or end - groups[-1].start > 6:
            groups.append(SimpleNamespace(start=start, end=end, words=[word]))
        else:
            groups[-1].words.append(word)
            groups[-1].end = max(groups[-1].end, end)
    return groups
