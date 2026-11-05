"""Download timestamped DASH fragments, preserving their original PTS.

YouTube post-live streams expose complete MP4 fragments through yt-dlp, while
their base URL is not a seekable MP4. Read only the fragments covering a range.
"""
import io
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import time
import uuid

import av
from yt_dlp.networking import Request

MAX_FRAGMENT = 128 * 1024**2
MAX_TRANSFER = 8 * 1024**3


class SourceRetrievalError(ValueError):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def redact(text):
    text = re.sub(r'https?://[^\s\]\)]+', '[stream URL]', str(text))
    return text[-16000:]


def run_encoder(ffmpeg, args, seconds, diagnostics):
    try:
        result = subprocess.run([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=max(120, min(43200, seconds * 12 + 60)),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except subprocess.TimeoutExpired as exc:
        raise SourceRetrievalError('Encoding the selected section timed out. Try a shorter range or retry the download.',
                                   dict(diagnostics, stderr=redact(exc.stderr or b''), reason='encoder-timeout')) from exc
    if result.returncode:
        raise SourceRetrievalError('The retrieved stream could not be decoded into a complete section. Retry, refresh qualities, or use the cached source explicitly.',
                                   dict(diagnostics, returncode=result.returncode, stderr=redact(result.stderr.decode(errors='replace'))))


def mp4_boxes(path):
    length = path.stat().st_size
    at = 0
    with path.open('rb') as stream:
        while at < length:
            stream.seek(at)
            header = stream.read(8)
            if len(header) != 8:
                raise ValueError('Truncated MP4 box header')
            size, kind = struct.unpack('>I4s', header)
            minimum = 8
            if size == 1:
                size = struct.unpack('>Q', stream.read(8))[0]
                minimum = 16
            elif size == 0:
                size = length - at
            if size < minimum or at + size > length:
                raise ValueError('Incomplete MP4 fragment')
            yield kind, at, size
            at += size


def assemble_mp4(parts, output, initialization=None):
    """Keep one initialization header and all selected moof/mdat pairs.

    Each post-live part repeats ftyp/moov. Blind concatenation loses indexing;
    keep PTS in moof unchanged, including independent audio/video offsets.
    """
    header_written = False
    media_count = 0
    with output.open('wb') as destination:
        for path, header_only in ([(initialization, True)] if initialization else []) + [(p, False) for p in parts]:
            boxes = list(mp4_boxes(path))
            has_moov = any(kind == b'moov' for kind, _, _ in boxes)
            include_header = not header_written and has_moov
            with path.open('rb') as source:
                for kind, offset, size in boxes:
                    if header_only and kind not in (b'ftyp', b'moov'):
                        continue
                    if kind not in (b'moof', b'mdat') and not (include_header and kind in (b'ftyp', b'moov')):
                        continue
                    if kind == b'moof':
                        media_count += 1
                    source.seek(offset)
                    remaining = size
                    while remaining:
                        data = source.read(min(1024**2, remaining))
                        if not data:
                            raise ValueError('Truncated MP4 fragment payload')
                        destination.write(data)
                        remaining -= len(data)
            header_written |= include_header
    if not header_written or not media_count:
        raise ValueError('DASH fragment is missing initialization or media boxes')


def packet_bounds(path):
    with av.open(str(path)) as container:
        stream = next(iter(container.streams), None)
        if stream is None:
            raise ValueError('Fragment has no stream')
        start, end, first_key = None, None, None
        for packet in container.demux(stream):
            if packet.pts is None:
                continue
            pts = float(packet.pts * packet.time_base)
            finish = float((packet.pts + (packet.duration or 0)) * packet.time_base)
            if first_key is None:
                first_key = packet.is_keyframe
            start = pts if start is None else min(start, pts)
            end = finish if end is None else max(end, finish)
        return dict(start=start, end=end, first_key=first_key, type=stream.type,
                    width=stream.codec_context.width if stream.type == 'video' else 0,
                    height=stream.codec_context.height if stream.type == 'video' else 0)


class FragmentReader:
    def __init__(self, ydl, fmt, cache, notify):
        self.ydl, self.fmt, self.cache, self.notify = ydl, fmt, cache, notify
        self.fragments = list(fmt.get('fragments') or [])
        self.cache.mkdir(parents=True, exist_ok=True)
        self.bounds = {}
        self.initialization = None
        self.network_bytes = 0
        self.fetched = []

    def load(self, index):
        if index in self.bounds:
            return self.bounds[index]
        path = self.cache / f'{index:06d}.mp4'
        if not path.exists():
            part = self.fragments[index]
            url = part.get('url')
            if not url:
                from urllib.parse import urljoin
                url = urljoin(self.fmt.get('fragment_base_url', ''), part.get('path', ''))
            temp = self.cache / f'{index:06d}.{uuid.uuid4().hex}.part'
            try:
                with self.ydl.urlopen(Request(url, headers=self.fmt.get('http_headers') or {})) as response, temp.open('wb') as output:
                    size = 0
                    while block := response.read(1024**2):
                        size += len(block)
                        self.network_bytes += len(block)
                        if size > MAX_FRAGMENT or self.network_bytes > MAX_TRANSFER:
                            raise ValueError('Selected fragments exceed the download-size limit')
                        output.write(block)
                # Validate the public stream response; HTML/error pages cannot
                # become cached media and are never handed to the decoder.
                list(mp4_boxes(temp))
                temp.replace(path)
                self.fetched.append(index)
            finally:
                temp.unlink(missing_ok=True)
        kinds = {kind for kind, _, _ in mp4_boxes(path)}
        if b'moov' in kinds and self.initialization is None:
            self.initialization = path
        if b'moof' not in kinds:
            self.bounds[index] = dict(path=path, start=None, end=None, first_key=None)
            return self.bounds[index]
        if b'moov' not in kinds:
            if self.initialization is None:
                raise ValueError('No initialization header for DASH media')
            wrapped = self.cache / f'{index:06d}-probe.mp4'
            assemble_mp4([path], wrapped, self.initialization)
            try:
                bounds = packet_bounds(wrapped)
            finally:
                wrapped.unlink(missing_ok=True)
        else:
            bounds = packet_bounds(path)
        self.bounds[index] = dict(bounds, path=path)
        return self.bounds[index]

    def select(self, start, end):
        if not self.fragments:
            raise ValueError('No fragment manifest for selected stream')
        first_index = 0
        first = self.load(first_index)
        while first['start'] is None and first_index < min(3, len(self.fragments) - 1):
            first_index += 1
            first = self.load(first_index)
        if first['start'] is None or not first['end'] > first['start']:
            raise ValueError('Could not read initial fragment timestamps')
        span = first['end'] - first['start']
        guessed = max(first_index, min(len(self.fragments)-1, first_index + int((start-first['start'])/span)))
        lo, hi = first_index, len(self.fragments) - 1
        for attempt in range(32):
            part = self.load(guessed)
            if part['start'] is None:
                raise ValueError('Selected fragment has no timestamped media')
            if part['start'] <= start + .0001 and part['end'] > start:
                break
            if part['start'] > start:
                hi = guessed - 1
            else:
                lo = guessed + 1
            if lo > hi:
                raise ValueError('Requested start is outside the available stream fragments')
            if attempt < 3:
                step = -max(1, int((part['start']-start)/span)) if part['start'] > start else max(1, int((start-part['end'])/span)+1)
                guessed = max(lo, min(hi, guessed + step))
            else:
                guessed = (lo + hi) // 2
        else:
            raise ValueError('Unable to locate fragment timestamps')
        index = guessed
        selected = []
        if self.fmt.get('vcodec') not in (None, 'none') and not part['first_key'] and index > first_index:
            selected.append(self.load(index-1))
        while index < len(self.fragments):
            part = self.load(index)
            if part['start'] >= end:
                break
            selected.append(part)
            if part['end'] >= end - .0001:
                break
            index += 1
        if not selected or selected[0]['start'] > start + .001 or selected[-1]['end'] < end - .03:
            raise ValueError('The source fragments do not cover the complete requested range')
        for previous, current in zip(selected, selected[1:]):
            if current['start'] - previous['end'] > .05:
                raise ValueError('A source fragment is missing inside the requested range')
        return [p['path'] for p in selected]


def choose_streams(info, height):
    formats = [f for f in info.get('formats', []) if not f.get('has_drm')]
    videos = [f for f in formats if f.get('height') == height and f.get('vcodec') not in (None, 'none')]
    if not videos:
        raise SourceRetrievalError('That source resolution is no longer available. Refresh qualities and choose an available resolution.')
    # Respect resolution and maximum available FPS. Prefer MP4/H.264 at equal
    # FPS for native compatibility, then other MP4 codecs, then WebM.
    video = max(videos, key=lambda f: (f.get('fps') or 0, f.get('ext') == 'mp4', str(f.get('vcodec','')).startswith('avc1'), f.get('tbr') or 0))
    if video.get('acodec') not in (None, 'none'):
        return video, None
    audios = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') not in (None, 'none')]
    if not audios:
        raise SourceRetrievalError('No commentary audio stream is available for this quality. Refresh qualities or use the cached source explicitly.')
    audio = max(audios, key=lambda f: (f.get('ext') in ('m4a','mp4'), f.get('abr') or f.get('tbr') or 0))
    return video, audio


def retrieve_fragment_section(folder, target, info, video, audio, segment, ffmpeg, ydl, notify):
    if audio is None:
        raise SourceRetrievalError('This fragmented source has no separately timestamped audio stream.')
    if any(f.get('ext') not in ('mp4','m4a') for f in (video,audio)):
        raise SourceRetrievalError('This fragmented container does not support precise partial export yet. Choose an MP4 source quality or retry using the cached source explicitly.')
    readers = []
    for kind, fmt in [('video',video),('audio',audio)]:
        ident = re.sub(r'[^A-Za-z0-9_-]', '_', str(fmt['format_id']))
        reader = FragmentReader(ydl, fmt, folder/'source-sections'/'fragments'/ident, notify)
        notify(message=f'Fetching only timestamped {kind} fragments for the selected section…')
        parts = reader.select(segment['start'], segment['end'])
        assembled = target / f'assembled-{kind}.mp4'
        # Self-contained fragments already carry the header. Initialization-only
        # fragments are prepended only for manifests which separate it.
        init = None if any(kind == b'moov' for kind,_,_ in mp4_boxes(parts[0])) else reader.initialization
        assemble_mp4(parts, assembled, init)
        readers.append((reader,assembled,parts))
    length = segment['end'] - segment['start']
    output = target / 'section.mp4'
    start, end = segment['start'], segment['end']
    filters = f'[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v];[1:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a]'
    diagnostics = dict(method='timestamped-dash-fragments', selected_video=video['format_id'], selected_audio=audio['format_id'],
        requested=segment, fetched_fragments={str(r.fmt['format_id']):r.fetched for r,_,_ in readers},
        network_bytes=sum(r.network_bytes for r,_,_ in readers), whole_source_downloaded=False)
    notify(message=f'Encoding the exact selected interval at {video["height"]}p…')
    run_encoder(ffmpeg, ['-copyts','-threads','2','-i',str(readers[0][1]),'-threads','2','-i',str(readers[1][1]),
        '-filter_complex_threads','2','-filter_complex',filters,'-map','[v]','-map','[a]','-t',str(length),
        '-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',
        '-threads','2','-movflags','+faststart',str(output)], length, diagnostics)
    return output, diagnostics
