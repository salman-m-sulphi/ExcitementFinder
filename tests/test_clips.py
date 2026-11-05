import io
import json
import sys
import time
import unittest
import uuid
import zipfile
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import av
import numpy as np
from scipy.io import wavfile
from fastapi.testclient import TestClient
from app import app, DATA, ffmpeg
from source_media import catalog_from_info, atomic_json, probe, youtube_section
from app import FFMPEG
from dash_ranges import SourceRetrievalError


class ClipExportTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.job = uuid.uuid4().hex
        self.folder = DATA / self.job
        self.folder.mkdir()
        sr = 16000
        t = np.arange(2 * sr) / sr
        sound = np.concatenate([.2 * np.sin(2 * np.pi * 440 * t), .2 * np.sin(2 * np.pi * 880 * t)]).astype('float32')
        wavfile.write(self.folder / 'test.wav', sr, sound)
        ffmpeg(['-f', 'lavfi', '-i', 'color=red:s=160x90:r=25:d=2',
                '-f', 'lavfi', '-i', 'color=blue:s=160x90:r=25:d=2',
                '-i', str(self.folder / 'test.wav'), '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]',
                '-map', '[v]', '-map', '2:a', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                '-shortest', str(self.folder / 'playback.mp4')])
        (self.folder / 'result.json').write_text(json.dumps({'duration': 4}))

    def tearDown(self):
        self.assertEqual(self.client.delete(f'/api/jobs/{self.job}').status_code, 200)

    def export(self, kind, segments, quality=None):
        base = f'/api/jobs/{self.job}/exports'
        response = self.client.post(base, json={'format': kind, 'segments': segments, 'quality': quality})
        self.assertEqual(response.status_code, 200, response.text)
        url = base + '/' + response.json()['id']
        for _ in range(300):
            state = self.client.get(url).json()
            if state['status'] in ('done', 'error'):
                break
            time.sleep(.05)
        self.assertEqual(state['status'], 'done', state)
        self.last_export_state = state
        response = self.client.get(url + '/download')
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response.headers['content-disposition'])
        return response.content

    def inspect_video(self, contents):
        with av.open(io.BytesIO(contents)) as container:
            duration = container.duration / av.time_base
            frames = [f.to_ndarray(format='rgb24').mean(axis=(0, 1)) for f in container.decode(video=0)]
        return duration, frames

    def test_single_cut_has_correct_duration_picture_and_audio(self):
        contents = self.export('clip', [{'start': 2.4, 'end': 3.4}])
        duration, frames = self.inspect_video(contents)
        self.assertAlmostEqual(duration, 1, delta=.12)
        self.assertGreater(frames[0][2], frames[0][0] + 150)  # blue second half
        path = self.folder / 'cut.mp4'
        path.write_bytes(contents)
        pcm = self.folder / 'cut.f32'
        ffmpeg(['-i', str(path), '-vn', '-ac', '1', '-ar', '16000', '-f', 'f32le', str(pcm)])
        sound = np.fromfile(pcm, dtype='float32')
        peak = np.fft.rfftfreq(len(sound), 1 / 16000)[np.argmax(abs(np.fft.rfft(sound)))]
        self.assertAlmostEqual(peak, 880, delta=5)

    def test_zip_contains_individual_playable_moments_and_timestamps(self):
        contents = self.export('zip', [{'start': .2, 'end': 1.2}, {'start': 2.4, 'end': 3.4}])
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
            videos = [n for n in archive.namelist() if n.endswith('.mp4')]
            self.assertEqual(len(videos), 2)
            self.assertEqual(len(json.loads(archive.read('timestamps.json'))['segments']), 2)
            for name in videos:
                duration, frames = self.inspect_video(archive.read(name))
                self.assertAlmostEqual(duration, 1, delta=.12)
                self.assertTrue(frames)

    def test_combined_video_sorts_and_merges_overlaps(self):
        contents = self.export('combined', [{'start': 2.4, 'end': 3.4}, {'start': .2, 'end': 1.2}, {'start': .7, 'end': 1.5}])
        duration, frames = self.inspect_video(contents)
        self.assertAlmostEqual(duration, 2.3, delta=.15)
        self.assertGreater(frames[0][0], frames[0][2] + 150)
        self.assertGreater(frames[-1][2], frames[-1][0] + 150)

    def test_invalid_export_ranges_are_rejected(self):
        base = f'/api/jobs/{self.job}/exports'
        for segments in ([{'start': 2, 'end': 1}], [{'start': 0, 'end': 5}]):
            self.assertEqual(self.client.post(base, json={'format': 'clip', 'segments': segments}).status_code, 400)
        self.assertEqual(self.client.post(base, json={'format': 'zip', 'segments': []}).status_code, 422)
        self.assertEqual(self.client.get(base + '/not-an-id/download').status_code, 404)

    def original_and_different_proxy(self):
        ffmpeg(['-i', str(self.folder / 'playback.mp4'), '-vf', 'scale=960:540',
                '-c:v', 'libx264', '-c:a', 'copy', str(self.folder / 'source.upload.mp4')])
        ffmpeg(['-f', 'lavfi', '-i', 'color=green:s=160x90:r=25:d=4',
                '-i', str(self.folder / 'test.wav'), '-map', '0:v', '-map', '1:a',
                '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(self.folder / 'playback.mp4')])

    def test_original_is_default_and_exports_original_picture_not_proxy(self):
        self.original_and_different_proxy()
        catalog = self.client.get(f'/api/jobs/{self.job}/qualities').json()
        self.assertEqual(catalog['default'], 'original')
        self.assertEqual(catalog['options'][0]['height'], 540)
        self.assertNotIn('local:720', [o['id'] for o in catalog['options']])
        contents = self.export('clip', [{'start': 2.375, 'end': 3.625}], 'original')
        with av.open(io.BytesIO(contents)) as container:
            self.assertEqual((container.streams.video[0].width, container.streams.video[0].height), (960, 540))
        duration, frames = self.inspect_video(contents)
        self.assertAlmostEqual(duration, 1.25, delta=.1)
        self.assertGreater(frames[0][2], frames[0][1] + 100)
        self.assertEqual(self.last_export_state['outputs'][0]['origin'], 'original-upload')
        self.assertEqual(self.last_export_state['outputs'][0]['source_start'], 2.375)

    def test_quality_propagates_to_single_zip_and_combined_without_upscaling(self):
        self.original_and_different_proxy()
        for kind in ('clip', 'zip', 'combined'):
            with self.subTest(kind=kind):
                contents = self.export(kind, [{'start': .375, 'end': 1.625}], 'local:360')
                self.assertEqual(self.last_export_state['quality'], 'local:360')
                if kind == 'zip':
                    with zipfile.ZipFile(io.BytesIO(contents)) as archive:
                        manifest = json.loads(archive.read('timestamps.json'))
                        self.assertEqual(manifest['quality']['id'], 'local:360')
                        contents = archive.read(next(n for n in archive.namelist() if n.endswith('.mp4')))
                with av.open(io.BytesIO(contents)) as container:
                    self.assertEqual((container.streams.video[0].width, container.streams.video[0].height), (640, 360))
                _, frames = self.inspect_video(contents)
                self.assertGreater(frames[0][0], frames[0][1] + 100)
        response = self.client.post(f'/api/jobs/{self.job}/exports', json={'format':'clip','quality':'local:1080','segments':[{'start':0,'end':1}]})
        self.assertEqual(response.status_code, 400)

    def test_youtube_catalog_defaults_to_actual_highest_and_keeps_cached_fallback(self):
        self.original_and_different_proxy()
        (self.folder / 'request.json').write_text(json.dumps({'url':'https://www.youtube.com/watch?v=EQRZ37hFQTM'}))
        options = catalog_from_info({'formats': [
            {'height':2160, 'fps':60, 'vcodec':'av01'},
            {'height':1080, 'fps':30, 'vcodec':'h264'},
            {'height':1080, 'fps':60, 'vcodec':'vp9'},
            {'height':4320, 'vcodec':'av01', 'has_drm':True},
            {'height':None, 'vcodec':'none'}]})
        atomic_json(self.folder / 'quality-catalog.json', {'checked':time.time(), 'options':options})
        catalog = self.client.get(f'/api/jobs/{self.job}/qualities').json()
        self.assertEqual(catalog['default'], 'yt:2160')
        self.assertEqual([q['id'] for q in catalog['options']], ['yt:2160', 'yt:1080', 'cached'])
        self.assertEqual(catalog['options'][1]['fps'], 60)

    def test_quality_choice_is_persisted_in_library_not_just_browser_origin(self):
        self.original_and_different_proxy()
        base = f'/api/jobs/{self.job}'
        response = self.client.post(base+'/quality-choice',json={'quality':'local:360'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(json.loads((self.folder/'quality-preference.json').read_text())['quality'],'local:360')
        with TestClient(app,base_url='http://localhost:9876') as new_origin:
            self.assertEqual(new_origin.get(base+'/qualities').json()['selected'],'local:360')
        self.assertEqual(self.client.post(base+'/quality-choice',json={'quality':'local:9999'}).status_code,400)

    def test_manual_fractional_bounds_are_preserved_and_not_clamped(self):
        contents = self.export('clip', [{'start':1.375, 'end':2.625}])
        self.assertEqual(self.last_export_state['outputs'][0]['source_start'], 1.375)
        self.assertEqual(self.last_export_state['outputs'][0]['source_end'], 2.625)
        duration, frames = self.inspect_video(contents)
        self.assertAlmostEqual(duration, 1.25, delta=.12)
        self.assertGreater(frames[0][0], frames[0][2] + 100)
        self.assertGreater(frames[-1][2], frames[-1][0] + 100)
        response = self.client.post(f'/api/jobs/{self.job}/exports', json={'format':'clip','segments':[{'start':0,'end':4.001}]})
        self.assertEqual(response.status_code, 400)


    def test_failed_youtube_partial_download_never_fetches_whole_video_or_substitutes_proxy(self):
        calls = []
        class UnavailableMetadata:
            def __init__(self, options): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def extract_info(self, url, download):
                calls.append(download)
                raise ValueError('Partial retrieval unavailable')
        with patch('yt_dlp.YoutubeDL', UnavailableMetadata):
            with self.assertRaisesRegex(ValueError, 'could not be retrieved'):
                youtube_section(self.folder, 'https://www.youtube.com/watch?v=EQRZ37hFQTM', 1080,
                                {'start':1.25,'end':2.5}, FFMPEG, lambda **k: None)
        self.assertEqual(calls, [False])

    def test_source_error_exposes_explicit_recovery_without_raw_encoder_code(self):
        self.original_and_different_proxy()
        (self.folder/'request.json').write_text(json.dumps({'url':'https://www.youtube.com/watch?v=EQRZ37hFQTM'}))
        atomic_json(self.folder/'quality-catalog.json',{'checked':time.time(),'options':[{'id':'yt:1080','height':1080,'origin':'youtube','label':'1080p source'}]})
        failure=SourceRetrievalError('The selected source section is temporarily unavailable. Retry or explicitly use the cached source.',{'returncode':3199971767,'stderr':'Invalid source stream'})
        with patch('app.export_input',side_effect=failure):
            response=self.client.post(f'/api/jobs/{self.job}/exports',json={'format':'clip','quality':'yt:1080','segments':[{'start':1.25,'end':2.5}]})
            self.assertEqual(response.status_code,200,response.text)
            export_id=response.json()['id']
            for _ in range(100):
                status=self.client.get(f'/api/jobs/{self.job}/exports/{export_id}').json()
                if status['status']=='error':break
                time.sleep(.05)
        self.assertEqual(status['status'],'error')
        self.assertEqual(status['recovery_quality'],'cached')
        self.assertIn('540p',status['recovery_label'])
        self.assertNotIn('3199971767',status['message'])
        target=self.folder/'exports'/export_id
        self.assertFalse(list(target.glob('*.mp4')))
        self.assertEqual(json.loads((target/'diagnostics.json').read_text())['returncode'],3199971767)


if __name__ == '__main__':
    unittest.main()
