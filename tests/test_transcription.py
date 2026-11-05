"""Opt-in real multilingual Tiny model test, with speech across a chunk boundary."""
import os
import sys
import time
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy.io import wavfile
from fastapi.testclient import TestClient
from app import app


@unittest.skipUnless(os.environ.get('RUN_TRANSCRIPTION_TEST') == '1', 'Set RUN_TRANSCRIPTION_TEST=1 to use the real Tiny model')
class TranscriptionTest(unittest.TestCase):
    def test_real_words_preserve_timestamps_across_three_minute_boundary(self):
        rate, speech = wavfile.read(Path(__file__).parent / 'fixtures/synthetic-commentary.wav')
        if speech.ndim > 1:
            speech = speech.mean(axis=1)
        speech = speech.astype('float32')
        speech *= .45 / max(1, np.max(np.abs(speech)))
        audio = np.concatenate([np.zeros(174 * rate), speech, np.zeros(4 * rate)]).astype('float32')
        with tempfile.TemporaryDirectory() as directory, TestClient(app) as client:
            path = Path(directory) / 'chunk-boundary.wav'
            wavfile.write(path, rate, audio)
            with path.open('rb') as source:
                response = client.post('/api/jobs', files={'file': ('chunk-boundary.wav', source, 'audio/wav')}, data={'model': 'tiny', 'language': 'en'})
            self.assertEqual(response.status_code, 200, response.text)
            job_id = response.json()['id']
            try:
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    status = client.get(f'/api/jobs/{job_id}').json()
                    if status['status'] in ('done', 'error'):
                        break
                    time.sleep(.2)
                self.assertEqual(status['status'], 'done', status)
                result = client.get(f'/api/jobs/{job_id}/result').json()
                self.assertTrue(result['has_words'], result['warnings'])
                self.assertFalse(result['warnings'])
                self.assertGreaterEqual(len(result['words']), 38)
                self.assertLessEqual(len(result['words']), 47)
                starts = [w['start'] for w in result['words']]
                self.assertGreater(min(starts), 172)
                self.assertTrue(any(t < 180 for t in starts))
                self.assertTrue(any(t > 185 for t in starts))
                self.assertTrue(all(b['silence'] for b in result['bins'][:80]))
                text = ' '.join(w['text'].strip().lower() for w in result['words'])
                self.assertIn('game', text)
                print(f'\nReal chunk-boundary transcription: {len(starts)} word-groups, {min(starts):.2f}–{max(starts):.2f}s')
            finally:
                response = client.delete(f'/api/jobs/{job_id}')
                self.assertEqual(response.status_code, 200, response.text)


if __name__ == '__main__':
    unittest.main()
