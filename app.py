import json
import os
import re
import shutil
import subprocess
import threading
import uuid
import zipfile
from typing import Literal
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import imageio_ffmpeg
import av
import numpy as np
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from faster_whisper import WhisperModel
from faster_whisper.vad import get_speech_timestamps, VadOptions
from analysis import SR, extract_features, DEFAULT_WEIGHTS
from source_media import quality_options, remember_source, export_input, probe, atomic_json
from source_media import source_details
from dash_ranges import SourceRetrievalError

ROOT = Path(__file__).resolve().parent
HOME_ROOT = Path(os.environ.get('EXCITEMENT_HOME', ROOT))
DATA = HOME_ROOT / 'data'
DATA.mkdir(exist_ok=True, parents=True)
MODELS = Path(os.environ.get('EXCITEMENT_MODELS', HOME_ROOT / 'models'))
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
MAX_BYTES = 8 * 1024 ** 3
MAX_SECONDS = 8 * 3600
app = FastAPI(title='Excitement Finder')
executor = ThreadPoolExecutor(max_workers=1)
jobs = {}
lock = threading.Lock()
models = {}
clip_executor = ThreadPoolExecutor(max_workers=1)
clip_exports = {}


class ClipRange(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)


class ClipRequest(BaseModel):
    format: Literal['clip', 'zip', 'combined']
    segments: list[ClipRange] = Field(min_length=1, max_length=24)
    quality: str | None = Field(default=None, max_length=64)


class QualityChoice(BaseModel):
    quality: str = Field(min_length=1, max_length=64)


@app.get('/api/jobs/{job_id}/qualities')
def export_qualities(job_id: str, refresh: bool = False):
    folder = job_dir(job_id)
    if not (folder / 'playback.mp4').exists():
        raise HTTPException(409, 'Wait for playback preparation to finish')
    catalog = quality_options(folder, FFMPEG, refresh)
    preference = folder / 'quality-preference.json'
    saved = json.loads(preference.read_text(encoding='utf-8')).get('quality') if preference.exists() else None
    catalog['selected'] = saved if any(q['id'] == saved for q in catalog['options']) else catalog['default']
    return catalog


@app.post('/api/jobs/{job_id}/quality-choice')
def remember_quality(job_id: str, choice: QualityChoice):
    folder = job_dir(job_id)
    catalog = quality_options(folder, FFMPEG)
    if not any(q['id'] == choice.quality for q in catalog['options']):
        raise HTTPException(400, 'Select an available source quality')
    atomic_json(folder / 'quality-preference.json', choice.model_dump())
    return {'saved': True}


def export_folder(job_id, export_id):
    if not re.fullmatch(r'[a-f0-9]{32}', export_id):
        raise HTTPException(404, 'Unknown export')
    folder = job_dir(job_id) / 'exports' / export_id
    if not folder.is_dir():
        raise HTTPException(404, 'Unknown export')
    return folder


def render_clips(job_id, export_id, segments, kind, quality):
    folder = DATA / job_id / 'exports' / export_id
    state = dict(status='running', progress=0, message='Preparing clips', quality=quality['id'], quality_label=quality['label'])
    def save(**changes):
        state.update(changes)
        with lock:
            clip_exports[export_id] = dict(state, job_id=job_id)
        # Atomic replacement prevents a polling request reading partial JSON.
        temp = folder / 'status.tmp'
        temp.write_text(json.dumps(state), encoding='utf-8')
        temp.replace(folder / 'status.json')
    try:
        save()
        if kind == 'combined':
            merged = []
            for s in sorted(segments, key=lambda x: x['start']):
                if merged and s['start'] <= merged[-1]['end']:
                    merged[-1]['end'] = max(merged[-1]['end'], s['end'])
                else:
                    merged.append(dict(s))
            segments = merged
        def stamp(t):
            t = int(t)
            return f'{t//3600:02d}-{t//60%60:02d}-{t%60:02d}'
        files, measurements, notices = [], [], []
        for i, s in enumerate(segments):
            name = f'moment_{i+1:02d}_{stamp(s["start"])}_to_{stamp(s["end"])}.mp4'
            p = folder / name
            source, offset, height, origin, notice = export_input(DATA / job_id, quality['id'], s, FFMPEG, save)
            if notice and notice not in notices:
                notices.append(notice)
            filters = ['-vf', f"scale=w=-2:h='min(ih,{height})':force_divisible_by=2,setsar=1"] if height else ['-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1']
            ffmpeg(['-ss', str(offset), '-i', str(source),
                    '-t', str(s['end'] - s['start']), '-map', '0:v:0?', '-map', '0:a:0',
                    *filters,
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '160k', '-threads', '2', '-movflags', '+faststart', str(p)])
            files.append(p)
            measurements.append(dict(filename=name, origin=origin, notice=notice, source_start=s['start'], source_end=s['end'], **probe(p)))
            save(progress=round(90 * (i + 1) / len(segments)), message=f'Extracted {i+1} of {len(segments)} moments')
        manifest = dict(segments=segments, source_job=job_id, quality=quality, outputs=measurements,
                        timing='Exact requested bounds, quantized to source video frames; H.264/AAC re-encode')
        atomic_json(folder / 'export.json', manifest)
        if kind == 'zip':
            output = folder / 'all-moments.zip'
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_STORED) as archive:
                for p in files:
                    archive.write(p, p.name)
                archive.writestr('timestamps.json', json.dumps(manifest, indent=2))
        elif kind == 'combined':
            listing = folder / 'concat.txt'
            listing.write_text(''.join(f"file '{p.name}'\n" for p in files), encoding='utf-8')
            output = folder / 'all-moments-combined.mp4'
            ffmpeg(['-f', 'concat', '-safe', '1', '-i', str(listing), '-c', 'copy', '-movflags', '+faststart', str(output)])
        else:
            output = files[0]
        save(status='done', progress=100, message='Ready to download', filename=output.name, outputs=measurements, warnings=notices)
    except Exception as exc:
        if isinstance(exc, SourceRetrievalError):
            atomic_json(folder / 'diagnostics.json', exc.details)
            retained = source_details(DATA / job_id)['path']
            recovery = {}
            if retained:
                details = probe(retained)
                recovery = dict(recovery_quality='cached', recovery_label=f'Retry same selection using cached {details["height"]}p (lower quality)' if details['height'] else 'Retry same selection using retained audio')
            save(status='error', message=str(exc), progress=0, **recovery)
        else:
            save(status='error', message='Could not extract clips: ' + str(exc), progress=0)


@app.get('/api/activity')
def activity():
    with lock:
        return {'busy': any(j['status'] in ('uploading', 'queued', 'running') for j in jobs.values()) or
                any(j['status'] in ('queued', 'running') for j in clip_exports.values())}


@app.post('/api/jobs/{job_id}/exports')
def create_clip_export(job_id: str, request: ClipRequest):
    folder = job_dir(job_id)
    if not (folder / 'result.json').exists() or not (folder / 'playback.mp4').exists():
        raise HTTPException(409, 'Wait for the analysis to finish first')
    duration = json.loads((folder / 'result.json').read_text(encoding='utf-8'))['duration']
    segments = [s.model_dump() for s in request.segments]
    for s in segments:
        if s['start'] >= duration or s['end'] > duration or not .1 <= s['end'] - s['start'] <= MAX_SECONDS:
            raise HTTPException(400, 'In must precede Out by at least 0.1 seconds, and both must be within the recording')
    if request.format == 'clip' and len(segments) != 1:
        raise HTTPException(400, 'Single-clip export needs exactly one moment')
    if sum(s['end'] - s['start'] for s in segments) > MAX_SECONDS:
        raise HTTPException(400, 'Limit each export to eight hours of clips')
    catalog = quality_options(folder, FFMPEG)
    choice = request.quality or catalog['default']
    quality = next((q for q in catalog['options'] if q['id'] == choice), None)
    if not quality:
        raise HTTPException(400, 'That source quality is not available. Refresh qualities and select an available option.')
    atomic_json(folder / 'quality-preference.json', {'quality': choice})
    export_id = uuid.uuid4().hex
    with lock:
        if sum(e['status'] in ('queued', 'running') for e in clip_exports.values()) >= 3:
            raise HTTPException(429, 'Three exports are already pending; please wait')
        clip_exports[export_id] = dict(job_id=job_id, status='queued', progress=0, message='Export queued')
        target = folder / 'exports' / export_id
        target.mkdir(parents=True)
        (target / 'status.json').write_text(json.dumps(clip_exports[export_id]), encoding='utf-8')
    clip_executor.submit(render_clips, job_id, export_id, segments, request.format, quality)
    return {'id': export_id}


@app.get('/api/jobs/{job_id}/exports/{export_id}')
def clip_export_status(job_id: str, export_id: str):
    folder = export_folder(job_id, export_id)
    with lock:
        if export_id in clip_exports:
            return dict(clip_exports[export_id])
    state = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
    if state['status'] in ('queued', 'running'):
        state.update(status='error', message='Export interrupted by restart. Download the moments again.')
    return state


@app.get('/api/jobs/{job_id}/exports/{export_id}/download')
def download_clips(job_id: str, export_id: str):
    folder = export_folder(job_id, export_id)
    state = clip_export_status(job_id, export_id)
    if state['status'] != 'done':
        raise HTTPException(409, 'The export is not ready yet')
    name = state['filename']
    return FileResponse(folder / name, filename=name, media_type='application/zip' if name.endswith('.zip') else 'video/mp4')


@app.middleware('http')
async def local_only(request: Request, call_next):
    # Reject cross-origin browser mutations and DNS rebinding. No public server.
    if request.url.hostname not in ('127.0.0.1', 'localhost', 'testserver'):
        return JSONResponse({'detail': 'Local connections only'}, status_code=403)
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD') and origin and origin != str(request.base_url).rstrip('/'):
        return JSONResponse({'detail': 'Cross-origin request rejected'}, status_code=403)
    return await call_next(request)


def job_dir(job_id):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise HTTPException(404, 'Unknown analysis')
    path = DATA / job_id
    if not path.is_dir():
        raise HTTPException(404, 'Unknown analysis')
    return path


def update(job_id, percent, message, **extra):
    with lock:
        jobs[job_id].update(progress=round(percent), message=message, **extra)


def ffmpeg(args):
    result = subprocess.run([FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', *args],
                            capture_output=True, timeout=12 * 3600,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise ValueError('Cannot decode this media. Check that it has an audio track and is not damaged. ' + result.stderr.decode(errors='replace')[-600:])


def canonical_youtube(url):
    p = urlparse(url.strip())
    host = (p.hostname or '').lower()
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
        raise ValueError('Use an https:// YouTube video link.')
    if host == 'youtu.be':
        video_id = p.path.strip('/')
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
        video_id = parse_qs(p.query).get('v', [''])[0] if p.path == '/watch' else p.path.split('/')[-1] if p.path.startswith(('/shorts/', '/embed/')) else ''
    else:
        video_id = ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise ValueError('Enter a single YouTube watch, shorts, or youtu.be video link; otherwise upload a local file.')
    return 'https://www.youtube.com/watch?v=' + video_id


def retrieve_youtube(url, folder, job_id):
    from yt_dlp import YoutubeDL
    def hook(d):
        if d['status'] == 'downloading':
            if d.get('downloaded_bytes', 0) > MAX_BYTES:
                raise ValueError('Download exceeds the 8 GiB limit. Upload a smaller local video.')
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            fraction = min(1, downloaded / total) if total else 0
            message = f'Downloading YouTube stream: {downloaded / 1024**2:.1f} MiB'
            if total:
                message += f' / about {total / 1024**2:.1f} MiB'
            update(job_id, 2 + 4 * fraction, message)
    def match(info, **kwargs):
        if info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming'):
            return 'Live streams are not supported. Upload a finished recording.'
        if (info.get('duration') or 0) > MAX_SECONDS:
            return 'Video exceeds 8 hours. Upload a shorter recording.'
    opts = dict(format='bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[height<=720]/bv*[height<=720]+ba/b',
                merge_output_format='mp4',
                outtmpl=str(folder / 'source.%(ext)s'), noplaylist=True, max_filesize=MAX_BYTES,
                socket_timeout=25, retries=1, fragment_retries=1, concurrent_fragment_downloads=8, quiet=True, noprogress=True,
                progress_hooks=[hook], match_filter=match, js_runtimes={'node': {'path': os.environ['EXCITEMENT_NODE']} if os.environ.get('EXCITEMENT_NODE') else {}},
                ffmpeg_location=FFMPEG)
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
        if not path.is_file():
            raise ValueError('No downloadable video/audio format was provided.')
        remember_source(folder, path, url, info)
        return path, info.get('title', 'YouTube video')
    except Exception as exc:
        raise ValueError('YouTube retrieval unavailable. Upload a local copy you are allowed to use. No sign-in or access restrictions are bypassed. Details: ' + str(exc)[-600:]) from exc


def analyze(job_id, source, title, model_name, language, url=None):
    folder = DATA / job_id
    warnings = []
    try:
        update(job_id, 1, 'Starting analysis', status='running')
        if url:
            source, title = retrieve_youtube(url, folder, job_id)
            update(job_id, 5, 'Downloaded video', title=title)
        update(job_id, 8, 'Decoding audio (16 kHz mono)')
        pcm = folder / 'audio.f32'
        ffmpeg(['-i', str(source), '-vn', '-ac', '1', '-ar', str(SR), '-f', 'f32le', str(pcm)])
        samples = pcm.stat().st_size // 4
        if not samples:
            raise ValueError('No audio samples were found in this file.')
        duration = samples / SR
        if duration > MAX_SECONDS:
            raise ValueError('The limit is 8 hours per recording. Split this recording first.')
        if not url:
            remember_source(folder, source)
        audio = np.memmap(pcm, dtype='float32', mode='r', shape=(samples,))
        update(job_id, 15, 'Detecting speech with Silero VAD')
        # Bound VAD and transcription memory even for multi-hour recordings.
        # Context overlaps are clipped to a non-overlapping core timeline.
        intervals = []
        for core_start in range(0, samples, 60 * SR):
            core_end = min(samples, core_start + 60 * SR)
            a, b = max(0, core_start - SR), min(samples, core_end + SR)
            speech = get_speech_timestamps(audio[a:b], VadOptions(min_silence_duration_ms=500), sampling_rate=SR)
            for x in speech:
                start, end = max(core_start, a + x['start']) / SR, min(core_end, a + x['end']) / SR
                if end > start:
                    if intervals and start <= intervals[-1][1]:
                        intervals[-1] = (intervals[-1][0], max(end, intervals[-1][1]))
                    else:
                        intervals.append((start, end))
            update(job_id, 15 + 6 * core_end / samples, f'Detecting speech: {core_end / SR / 60:.1f} / {duration / 60:.1f} minutes')
        words, transcript = [], []
        detected_language = language or 'undetermined'
        transcription_ok = model_name != 'none'
        if transcription_ok and intervals:
            try:
                update(job_id, 22, f'Loading {model_name} transcription model (first use downloads free model weights)')
                if model_name not in models:
                    models.clear()
                    models[model_name] = WhisperModel(model_name, device='cpu', compute_type='int8', download_root=str(MODELS), cpu_threads=max(1, min(8, os.cpu_count() or 4)))
                update(job_id, 25, 'Transcribing locally; long recordings can take a while')
                detected_languages = set()
                for core_start in range(0, samples, 180 * SR):
                    core_end = min(samples, core_start + 180 * SR)
                    a, b = max(0, core_start - 2 * SR), min(samples, core_end + 2 * SR)
                    segments, info = models[model_name].transcribe(audio[a:b], language=language or None,
                        word_timestamps=True, vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500),
                        beam_size=3, condition_on_previous_text=False)
                    detected_languages.add(info.language)
                    for s in segments:
                        kept = []
                        for w in s.words or []:
                            start, end = w.start + a / SR, w.end + a / SR
                            if w.word.strip() and core_start / SR <= (start + end) / 2 < core_end / SR:
                                item = dict(start=max(0, start), end=min(duration, end), text=w.word, probability=round(w.probability, 3))
                                words.append(item)
                                kept.append(item)
                        if kept:
                            transcript.append(dict(start=kept[0]['start'], end=kept[-1]['end'], text=''.join(w['text'] for w in kept)))
                        done = min(duration, s.end + a / SR)
                        update(job_id, 25 + 28 * done / duration, f'Transcribing: {done / 60:.1f} / {duration / 60:.1f} minutes')
                    update(job_id, 25 + 28 * core_end / samples, f'Transcribing: {core_end / SR / 60:.1f} / {duration / 60:.1f} minutes')
                detected_language = ', '.join(sorted(detected_languages))
            except Exception as exc:
                transcription_ok = False
                words, transcript = [], []
                warnings.append('Transcription failed; word pace was excluded from the score. Audio features remain available. ' + str(exc)[:400])
        elif model_name == 'none':
            warnings.append('Audio-only mode: transcription and word pace are disabled.')
        words.sort(key=lambda w: (w['start'] + w['end']) / 2)
        bins = extract_features(audio, intervals, words, lambda p, m: update(job_id, p, m))
        del audio
        update(job_id, 72, 'Preparing browser-compatible playback')
        with av.open(str(source)) as container:
            videos = list(container.streams.video)
            audios = list(container.streams.audio)
            copy_video = bool(videos and videos[0].codec_context.name == 'h264' and videos[0].codec_context.pix_fmt in ('yuv420p', 'yuvj420p'))
            copy_audio = bool(audios and audios[0].codec_context.name == 'aac')
        # Compatible video is remuxed without re-encoding, which matters for hours
        # of footage. Other formats get an H.264/AAC preview, preserving timing.
        video_args = ['-c:v', 'copy'] if copy_video else [
                '-vf', "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '25', '-pix_fmt', 'yuv420p']
        audio_args = ['-c:a', 'copy'] if copy_audio else ['-c:a', 'aac', '-b:a', '128k']
        ffmpeg(['-i', str(source), '-map', '0:v:0?', '-map', '0:a:0', *video_args, *audio_args,
                '-movflags', '+faststart', '-threads', '4', str(folder / 'playback.mp4')])
        result = dict(id=job_id, title=title, duration=duration, bin_seconds=2,
                      language=detected_language, model=model_name, has_words=bool(words),
                      transcription_ok=transcription_ok, bins=bins, words=words,
                      transcript=transcript, speech_intervals=intervals, warnings=warnings,
                      default_weights=DEFAULT_WEIGHTS, media_url=f'/api/jobs/{job_id}/media',
                      methodology='Audio-based heuristic, not a probability or a visual-action detector. Pace uses model word-groups in centered 10-second windows. Volume surge compares each 2-second bin to the preceding 30 seconds, with a -55 dBFS baseline floor. Loudness and sound-change percentiles exclude near-silent bins. Spectral change measures positive normalized FFT changes. Silence: >=95% of frames below -55 dBFS.')
        (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        pcm.unlink(missing_ok=True)
        update(job_id, 100, 'Ready', status='done', title=title)
    except Exception as exc:
        update(job_id, 0, str(exc), status='error')
    finally:
        (folder / 'status.json').write_text(json.dumps(jobs[job_id], ensure_ascii=False), encoding='utf-8')


@app.get('/api/jobs')
def list_jobs():
    saved = {}
    for p in DATA.glob('*/status.json'):
        try:
            saved[p.parent.name] = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
    with lock:
        saved.update({k: dict(v) for k, v in jobs.items()})
        for k, v in saved.items():
            if k not in jobs and v.get('status') in ('queued', 'running', 'uploading'):
                v.update(status='error', progress=0, message='Analysis interrupted by server restart. Please submit again.')
    return list(reversed(list(saved.values())))


@app.post('/api/jobs')
async def create_job(file: UploadFile | None = File(None), url: str = Form(''),
                     model: str = Form('base'), language: str = Form('')):
    if model not in ('none', 'tiny', 'base', 'small', 'medium'):
        raise HTTPException(400, 'Choose a supported model')
    if language and not re.fullmatch(r'[a-z]{2,3}', language):
        raise HTTPException(400, 'Use a language code such as en, hi, es, ja, or leave it empty for automatic detection.')
    if bool(file and file.filename) == bool(url.strip()):
        raise HTTPException(400, 'Choose one local file or one YouTube URL')
    if url:
        try:
            url = canonical_youtube(url)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    with lock:
        if sum(j['status'] in ('queued', 'running', 'uploading') for j in jobs.values()) >= 3:
            raise HTTPException(429, 'Three jobs are already pending. Wait for one to finish.')
        job_id = uuid.uuid4().hex
        jobs[job_id] = dict(id=job_id, title=(file.filename if file else 'YouTube video'), status='uploading', progress=0, message='Receiving file')
    folder = DATA / job_id
    folder.mkdir()
    source = folder / 'source.upload'
    try:
        if file:
            size = 0
            with source.open('wb') as out:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(413, 'File exceeds 8 GiB; upload a smaller recording.')
                    out.write(chunk)
            if not size:
                raise HTTPException(400, 'The file is empty')
        update(job_id, 0, 'Queued; one analysis runs at a time', status='queued')
        (folder / 'request.json').write_text(json.dumps(dict(title=jobs[job_id]['title'], model=model, language=language, url=url or None), ensure_ascii=False), encoding='utf-8')
        (folder / 'status.json').write_text(json.dumps(jobs[job_id], ensure_ascii=False), encoding='utf-8')
        executor.submit(analyze, job_id, source, jobs[job_id]['title'], model, language, url or None)
        return {'id': job_id}
    except Exception:
        with lock:
            jobs.pop(job_id, None)
        shutil.rmtree(folder)
        raise
    finally:
        if file:
            await file.close()


@app.get('/api/jobs/{job_id}')
def status(job_id: str):
    folder = job_dir(job_id)
    with lock:
        if job_id in jobs:
            return dict(jobs[job_id])
    if (folder / 'status.json').exists():
        saved = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
        if saved.get('status') in ('queued', 'running', 'uploading'):
            saved.update(status='error', progress=0, message='Analysis interrupted by server restart. Please submit again.')
        return saved
    return dict(id=job_id, status='error', progress=0, message='Analysis interrupted by a server restart. Please submit again.')


@app.get('/api/jobs/{job_id}/result')
def result(job_id: str):
    p = job_dir(job_id) / 'result.json'
    if not p.exists():
        raise HTTPException(409, 'Analysis is not ready')
    return FileResponse(p, media_type='application/json')


@app.post('/api/jobs/{job_id}/retry')
def retry_job(job_id: str):
    folder = job_dir(job_id)
    request_file = folder / 'request.json'
    if not request_file.exists():
        raise HTTPException(409, 'This older job has no saved request. Submit it again.')
    settings = json.loads(request_file.read_text(encoding='utf-8'))
    with lock:
        if jobs.get(job_id, {}).get('status') in ('queued', 'running', 'uploading'):
            raise HTTPException(409, 'This analysis is already running')
        if (folder / 'result.json').exists():
            raise HTTPException(409, 'This analysis is already complete. Open its saved result.')
        if sum(j['status'] in ('queued', 'running', 'uploading') for j in jobs.values()) >= 3:
            raise HTTPException(429, 'Three jobs are already pending. Wait for one to finish.')
        jobs[job_id] = dict(id=job_id, title=settings['title'], status='queued', progress=0, message='Retry queued; partial YouTube downloads will resume where supported')
    (folder / 'status.json').write_text(json.dumps(jobs[job_id], ensure_ascii=False), encoding='utf-8')
    executor.submit(analyze, job_id, folder / 'source.upload', settings['title'], settings['model'], settings['language'], settings['url'])
    return {'id': job_id}


@app.get('/api/jobs/{job_id}/media')
def media(job_id: str):
    p = job_dir(job_id) / 'playback.mp4'
    if not p.exists():
        raise HTTPException(404, 'Playback is not ready')
    return FileResponse(p, media_type='video/mp4')


@app.delete('/api/jobs/{job_id}')
def delete_job(job_id: str):
    folder = job_dir(job_id)
    with lock:
        if jobs.get(job_id, {}).get('status') in ('uploading', 'queued', 'running'):
            raise HTTPException(409, 'Wait for this analysis to finish before deleting it')
        if any(e.get('job_id') == job_id and e['status'] in ('queued', 'running') for e in clip_exports.values()):
            raise HTTPException(409, 'Wait for this recording’s clip exports to finish before deleting it')
        jobs.pop(job_id, None)
    shutil.rmtree(folder)
    return {'deleted': True}


app.mount('/', StaticFiles(directory=ROOT / 'static', html=True), name='ui')
