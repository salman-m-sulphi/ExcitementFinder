import io
import sys
import time
import unittest
import wave
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from fastapi.testclient import TestClient
from app import app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_invalid_input_and_origin(self):
        self.assertEqual(self.client.post('/api/jobs').status_code, 400)
        self.assertEqual(self.client.post('/api/jobs', data={'url': 'https://localhost/a'}).status_code, 400)
        self.assertEqual(self.client.post('/api/jobs', headers={'Origin': 'https://example.com'}).status_code, 403)
        self.assertEqual(self.client.get('/api/jobs/not-an-id').status_code, 404)
        self.assertEqual(self.client.get('/api/jobs', headers={'Host': 'evil.example'}).status_code, 403)

    def test_upload_real_analysis_range_playback_and_delete(self):
        stream = io.BytesIO()
        signal = np.concatenate([np.zeros(2 * 16000), .2 * np.sin(2 * np.pi * 220 * np.arange(2 * 16000) / 16000), np.zeros(16000)])
        with wave.open(stream, 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes((signal * 32767).astype('<i2').tobytes())
        response = self.client.post('/api/jobs', files={'file': ('test.wav', stream.getvalue(), 'audio/wav')}, data={'model': 'none'})
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()['id']
        try:
            self.assertEqual(self.client.get(f'/api/jobs/{job_id}/result').status_code, 409)
            for _ in range(300):
                status = self.client.get(f'/api/jobs/{job_id}').json()
                if status['status'] in ('done', 'error'):
                    break
                time.sleep(.1)
            self.assertEqual(status['status'], 'done', status)
            result = self.client.get(f'/api/jobs/{job_id}/result').json()
            self.assertEqual(self.client.post(f'/api/jobs/{job_id}/retry').status_code, 409)
            self.assertAlmostEqual(result['duration'], 5, places=1)
            self.assertTrue(result['bins'][0]['silence'])
            self.assertFalse(result['bins'][1]['silence'])
            self.assertFalse(result['has_words'])
            response = self.client.get(f'/api/jobs/{job_id}/media', headers={'Range': 'bytes=0-99'})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(len(response.content), 100)
            self.assertTrue(response.headers['content-type'].startswith('video/mp4'))
        finally:
            response = self.client.delete(f'/api/jobs/{job_id}')
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(f'/api/jobs/{job_id}').status_code, 404)

    def test_failed_decode_can_retry_with_saved_settings(self):
        response = self.client.post('/api/jobs', files={'file': ('invalid.mp4', b'not a media file', 'video/mp4')}, data={'model': 'none'})
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()['id']
        try:
            for attempt in range(2):
                for _ in range(100):
                    status = self.client.get(f'/api/jobs/{job_id}').json()
                    if status['status'] in ('done', 'error'):
                        break
                    time.sleep(.05)
                self.assertEqual(status['status'], 'error', status)
                self.assertIn('Cannot decode', status['message'])
                if attempt == 0:
                    response = self.client.post(f'/api/jobs/{job_id}/retry')
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()['id'], job_id)
        finally:
            self.assertEqual(self.client.delete(f'/api/jobs/{job_id}').status_code, 200)


if __name__ == '__main__':
    unittest.main()
