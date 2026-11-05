"""Real codec regression for repeated MP4 headers and absolute DASH timestamps."""
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import av
import numpy as np
from app import FFMPEG,ffmpeg
from source_media import youtube_section,probe
from dash_ranges import mp4_boxes,packet_bounds,SourceRetrievalError,redact


class DashRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work=Path(__file__).resolve().parents[3]/'work/dash-regressions'
        work.mkdir(parents=True,exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(dir=work)
        cls.root=Path(cls.temp.name)
        video=cls.root/'video.mp4';audio=cls.root/'audio.mp4'
        ffmpeg(['-f','lavfi','-i','color=red:s=160x90:r=25:d=3','-f','lavfi','-i','color=blue:s=160x90:r=25:d=3',
            '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]','-map','[v]','-c:v','libx264','-g','25','-bf','0',
            '-video_track_timescale','90000','-movflags','empty_moov+frag_keyframe+default_base_moof',str(video)])
        ffmpeg(['-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=3','-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=3',
            '-filter_complex','[0:a][1:a]concat=n=2:v=0:a=1[a]','-map','[a]','-c:a','aac','-frag_duration','1000000',
            '-movflags','empty_moov+frag_keyframe+default_base_moof',str(audio)])
        cls.payloads={};cls.formats=[]
        for kind,path,scale,offset in [('video',video,90000,100),('audio',audio,48000,100.007)]:
            data=path.read_bytes();boxes=list(mp4_boxes(path))
            header=b''.join(data[o:o+s] for t,o,s in boxes if t in (b'ftyp',b'moov'))
            fragments=[];current=bytearray()
            for typ,at,size in boxes:
                if typ==b'moof':
                    current=bytearray(data[at:at+size]);pos=0
                    while True:
                        pos=current.find(b'tfdt',pos)
                        if pos<0:break
                        version=current[pos+4];fmt='>Q' if version else '>I'
                        tick=struct.unpack_from(fmt,current,pos+8)[0]
                        struct.pack_into(fmt,current,pos+8,tick+round(offset*scale));pos+=12
                elif typ==b'mdat':
                    current.extend(data[at:at+size]);url=f'https://fixture.test/{kind}/{len(fragments)}'
                    cls.payloads[url]=header+bytes(current);fragments.append({'url':url})
            cls.formats.append(dict(format_id=kind,protocol='http_dash_segments',ext='mp4' if kind=='video' else 'm4a',
                height=90 if kind=='video' else None,width=160 if kind=='video' else None,fps=25 if kind=='video' else None,
                vcodec='avc1' if kind=='video' else 'none',acodec='none' if kind=='video' else 'aac',
                url=f'https://fixture.test/{kind}/unseekable-base',fragments=fragments))

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_absolute_pts_headers_and_nearby_fragments_preserve_picture_and_audio(self):
        calls=[];payloads=self.payloads;formats=self.formats
        class MetadataAndFragments:
            def __init__(self,options):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def extract_info(self,url,download):
                if download:raise AssertionError('Whole-video download was requested')
                return {'formats':formats,'live_status':'post_live'}
            def urlopen(self,request):
                calls.append(request.url)
                return io.BytesIO(payloads[request.url])
        job=self.root/'job';job.mkdir(exist_ok=True)
        bounds={'start':102.125,'end':103.375}
        with patch('yt_dlp.YoutubeDL',MetadataAndFragments):
            path,notice=youtube_section(job,'https://www.youtube.com/watch?v=EQRZ37hFQTM',90,bounds,FFMPEG,lambda **k:None)
        self.assertIsNone(notice)
        info=probe(path);self.assertEqual((info['width'],info['height']),(160,90))
        self.assertTrue(info['has_audio']);self.assertAlmostEqual(info['duration'],1.25,delta=.06)
        with av.open(str(path)) as media:
            frames=[frame.to_ndarray(format='rgb24').mean(axis=(0,1)) for frame in media.decode(video=0)]
        self.assertGreater(frames[0][0],frames[0][2]+100)
        self.assertGreater(frames[-1][2],frames[-1][0]+100)
        self.assertFalse(any('unseekable-base' in url for url in calls))
        self.assertFalse(any(url.endswith('/5') for url in calls))
        manifest=json.loads(path.with_name('section.json').read_text())
        self.assertFalse(manifest['transport']['whole_source_downloaded'])
        self.assertEqual(manifest['transport']['requested'],bounds)
        with patch('yt_dlp.YoutubeDL',side_effect=AssertionError('Cached section should not redownload')):
            self.assertEqual(youtube_section(job,'https://www.youtube.com/watch?v=EQRZ37hFQTM',90,bounds,FFMPEG,lambda **k:None)[0],path)
        # Decode actual AAC output and check both tones, not just stream metadata.
        pcm=self.root/'audio.f32';ffmpeg(['-i',str(path),'-vn','-ar','16000','-ac','1','-f','f32le',str(pcm)])
        sound=np.fromfile(pcm,dtype='float32')
        for block,expected in [(sound[:6400],440),(sound[-3200:],880)]:
            frequencies=np.fft.rfftfreq(len(block),1/16000)
            peak=frequencies[np.argmax(abs(np.fft.rfft(block)))]
            self.assertAlmostEqual(peak,expected,delta=10)

    def test_diagnostics_redact_stream_urls(self):
        cleaned=redact('Error opening https://stream.test/path?ip=secret&sig=private\nInvalid data')
        self.assertNotIn('private',cleaned);self.assertNotIn('secret',cleaned)
        self.assertIn('Invalid data',cleaned)
