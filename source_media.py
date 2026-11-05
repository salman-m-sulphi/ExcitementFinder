"""Source discovery and resolution-aware, section-only YouTube retrieval.

No original media is replaced. A proxy is offered only under an explicit label.
"""
import hashlib
import json
import os
import time
from pathlib import Path

import av


def atomic_json(path, value):
    import uuid
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def probe(path):
    with av.open(str(path)) as container:
        video = next(iter(container.streams.video), None)
        return dict(width=video.codec_context.width if video else 0,
                    height=video.codec_context.height if video else 0,
                    fps=float(video.average_rate or 0) if video else 0,
                    duration=container.duration / av.time_base if container.duration else None,
                    has_audio=bool(container.streams.audio))


def source_details(folder):
    metadata = folder / 'source.json'
    if metadata.exists():
        info = json.loads(metadata.read_text(encoding='utf-8'))
    else:
        request = folder / 'request.json'
        settings = json.loads(request.read_text(encoding='utf-8')) if request.exists() else {}
        info = dict(kind='youtube' if settings.get('url') else 'local', url=settings.get('url'))
    candidates = [folder / info.get('filename', 'source.upload'), folder / 'source.upload']
    candidates += sorted(folder.glob('source.*'))
    source = next((p for p in candidates if p.is_file() and p.suffix.lower() in ('.upload', '.mp4', '.mkv', '.webm', '.mov', '.m4a', '.mp3', '.wav', '.avi', '.flv', '.ogg', '.ts', '.mpeg', '.m4v')), None)
    info['path'] = source
    return info


def ydl_options(ffmpeg):
    return dict(quiet=True, noprogress=True, noplaylist=True, socket_timeout=25,
                retries=1, fragment_retries=1, ffmpeg_location=ffmpeg,
                js_runtimes={'node': {'path': os.environ['EXCITEMENT_NODE']} if os.environ.get('EXCITEMENT_NODE') else {}})


def catalog_from_info(info):
    heights = {}
    for f in info.get('formats', []):
        height = f.get('height')
        if not height or f.get('vcodec') in ('none', None) or f.get('has_drm'):
            continue
        h = int(height)
        fps = float(f.get('fps') or 0)
        heights[h] = max(heights.get(h, 0), fps)
    return [dict(id=f'yt:{h}', label=f'{h}p' + (f' · {fps:g} fps' if fps else '') + ' · YouTube source',
                 height=h, fps=fps, origin='youtube') for h, fps in sorted(heights.items(), reverse=True)]


def remember_source(folder, source, url=None, info=None):
    value = dict(kind='youtube' if url else 'local', url=url, filename=Path(source).name, **probe(source))
    atomic_json(folder / 'source.json', value)
    if info:
        atomic_json(folder / 'quality-catalog.json', dict(checked=time.time(), options=catalog_from_info(info)))


def quality_options(folder, ffmpeg, refresh=False):
    source = source_details(folder)
    path = source['path']
    warning = None
    if source['kind'] == 'youtube' and source.get('url'):
        options = []
        cache = folder / 'quality-catalog.json'
        try:
            cached = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
            if not refresh and time.time() - cached.get('checked', 0) < 6 * 3600:
                options = cached['options']
            else:
                from yt_dlp import YoutubeDL
                with YoutubeDL(ydl_options(ffmpeg)) as ydl:
                    info = ydl.extract_info(source['url'], download=False)
                options = catalog_from_info(info)
                atomic_json(cache, dict(checked=time.time(), options=options))
        except Exception as exc:
            warning = ('Could not check YouTube source qualities. Retry Refresh qualities, use the explicitly labelled cached source, '
                       'or upload the original file. ' + str(exc)[-250:])
        if path:
            native = probe(path)
            label = f'{native["height"]}p' if native['height'] else 'Audio'
            options.append(dict(id='cached', label=f'{label} · cached analysis source (offline)', origin='cached', **native))
        elif (folder / 'playback.mp4').exists():
            options.append(dict(id='proxy', label='Playback proxy only · original unavailable', origin='proxy', **probe(folder / 'playback.mp4')))
        return dict(options=options, default=options[0]['id'] if options else None, source_kind='youtube', warning=warning)
    path = path or folder / 'playback.mp4'
    native = probe(path)
    original = source['path'] is not None
    label = f'{native["width"]} × {native["height"]}' if native['height'] else 'Audio only'
    options = [dict(id='original' if original else 'proxy', label=f'{label} · ' + ('original upload' if original else 'playback proxy (original unavailable)'), origin='local' if original else 'proxy', **native)]
    if original:
        for height in (2160, 1440, 1080, 720, 480, 360):
            if height < native['height']:
                options.append(dict(id=f'local:{height}', label=f'{height}p · from original upload', height=height, origin='local'))
    return dict(options=options, default=options[0]['id'], source_kind='local', warning=None if original else 'The original file is missing. Only the playback proxy is available; it cannot restore source detail.')


def youtube_section(folder, source_url, height, segment, ffmpeg, notify):
    """Retrieve only required DASH fragments, or seek a complete HTTP stream."""
    from yt_dlp import YoutubeDL
    from dash_ranges import (choose_streams, retrieve_fragment_section, run_encoder,
                             SourceRetrievalError, redact)
    key = hashlib.sha256(json.dumps([source_url, height, segment['start'], segment['end']]).encode()).hexdigest()[:24]
    target = folder / 'source-sections' / key
    target.mkdir(parents=True, exist_ok=True)
    manifest = target / 'section.json'
    if manifest.exists():
        saved = json.loads(manifest.read_text(encoding='utf-8'))
        path = target / saved['filename']
        if path.exists():
            details = probe(path)
            if details['height'] == height and details['has_audio'] and details['duration'] and abs(details['duration']-(segment['end']-segment['start'])) <= .25:
                return path, saved.get('notice')
    diagnostics = dict(requested=segment, height=height, whole_source_downloaded=False)
    try:
        notify(message=f'Checking the {height}p source streams for your selected interval…')
        with YoutubeDL(ydl_options(ffmpeg)) as ydl:
            info = ydl.extract_info(source_url, download=False)
            video, audio = choose_streams(info, height)
            diagnostics.update(live_status=info.get('live_status'), selected_video=video['format_id'],
                               selected_audio=audio['format_id'] if audio else 'combined',
                               video_protocol=video.get('protocol'), audio_protocol=audio.get('protocol') if audio else None)
            if video.get('protocol') == 'http_dash_segments' and video.get('fragments'):
                if not audio or audio.get('protocol') != 'http_dash_segments' or not audio.get('fragments'):
                    raise SourceRetrievalError('The selected fragmented video has no matching timestamped audio manifest. Refresh qualities or retry using the cached source explicitly.', diagnostics)
                path, transfer = retrieve_fragment_section(folder, target, info, video, audio, segment, ffmpeg, ydl, notify)
                diagnostics.update(transfer)
            else:
                # A complete HTTP/HLS resource can be sought directly. DASH base
                # URLs must never reach this branch: they are not complete MP4s.
                args = []
                for fmt in [video] + ([audio] if audio else []):
                    url = fmt['url']
                    if not url.startswith(('https://','http://')):
                        raise SourceRetrievalError('This source protocol cannot provide a partial download.', diagnostics)
                    headers = ''.join(f'{k}: {v}\r\n' for k,v in (fmt.get('http_headers') or {}).items())
                    args += ['-rw_timeout','25000000','-ss',str(segment['start'])]
                    if headers:
                        args += ['-headers',headers]
                    args += ['-threads','2','-i',url]
                path = target / 'section.mp4'
                length = segment['end']-segment['start']
                notify(message=f'Retrieving and encoding only the selected section at {height}p…')
                args += ['-map','0:v:0','-map','1:a:0' if audio else '0:a:0','-t',str(length),
                         '-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p',
                         '-c:a','aac','-b:a','192k','-threads','2','-movflags','+faststart',str(path)]
                diagnostics['method']='seekable-http-stream'
                run_encoder(ffmpeg,args,length,diagnostics)
        details=probe(path)
        expected=segment['end']-segment['start']
        if details['height']!=height or not details['has_audio']:
            raise SourceRetrievalError('The retrieved section did not contain the chosen resolution and audio. It was not offered as a successful download.',diagnostics)
        if not details['duration'] or abs(details['duration']-expected)>max(.25,2/max(details['fps'],1)):
            raise SourceRetrievalError('The source did not provide the complete requested interval. Retry or choose the cached source explicitly.',diagnostics)
        atomic_json(manifest,dict(filename=path.name,segment=segment,notice=None,transport=diagnostics,**details))
        return path,None
    except Exception as exc:
        if isinstance(exc,SourceRetrievalError):
            diagnostics.update(exc.details)
            message=str(exc)
        else:
            diagnostics['error']=redact(str(exc))
            message='The selected YouTube section could not be retrieved. Retry or refresh qualities; you can also retry explicitly using the cached source.'
        atomic_json(target/'diagnostics.json',diagnostics)
        raise SourceRetrievalError(message,diagnostics) from exc



def export_input(folder, quality, segment, ffmpeg, notify):
    source = source_details(folder)
    if quality.startswith('yt:'):
        if source['kind'] != 'youtube' or not source.get('url'):
            raise ValueError('This recording has no retained YouTube source URL.')
        path, notice = youtube_section(folder, source['url'], int(quality.split(':')[1]), segment, ffmpeg, notify)
        return path, 0.0, None, 'youtube-section', notice
    if quality == 'proxy':
        return folder / 'playback.mp4', segment['start'], None, 'playback-proxy', None
    if not source['path']:
        raise ValueError('The original source is missing. Explicitly select the playback proxy or import the original again.')
    height = int(quality.split(':')[1]) if quality.startswith('local:') else None
    return source['path'], segment['start'], height, 'cached-analysis-source' if quality == 'cached' else 'original-upload', None
