import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from analysis import SR, extract_features, score_bins
from app import canonical_youtube


class SignalTests(unittest.TestCase):
    def tone(self, seconds, amplitude):
        return (amplitude * np.sin(2 * np.pi * 220 * np.arange(int(seconds * SR)) / SR)).astype('float32')

    def test_silence_stays_zero_with_transcript_hallucination(self):
        audio = np.zeros(8 * SR, dtype='float32')
        words = [dict(start=i / 10, end=i / 10 + .05) for i in range(70)]
        bins = extract_features(audio, [(0, 8)], words)
        self.assertTrue(all(b['silence'] for b in bins))
        self.assertEqual(score_bins(bins), [0] * 4)

    def test_local_volume_jump_scores_above_continuous_tone(self):
        audio = np.concatenate([self.tone(30, .02), self.tone(4, .2)])
        bins = extract_features(audio, [], [])
        self.assertAlmostEqual(bins[15]['surge_db'], 20, delta=.2)
        self.assertGreater(score_bins(bins, has_words=False)[15], score_bins(bins, has_words=False)[10])
        self.assertLess(bins[10]['signals']['surge'], .01)

    def test_fast_commentary_increases_pace(self):
        audio = self.tone(60, .1)
        words = [dict(start=float(t), end=float(t + .1)) for t in np.concatenate([np.arange(0, 20, 1), np.arange(20, 40, .2), np.arange(40, 60, 1)])]
        bins = extract_features(audio, [(0, 60)], words)
        self.assertGreater(bins[15]['wpm'], bins[4]['wpm'] * 3)
        weights = dict(pace=100, surge=0, loudness=0, speech=0, change=0)
        scores = score_bins(bins, weights)
        self.assertGreater(scores[15], scores[4])
        self.assertTrue(all(b['speech_fraction'] == 1 for b in bins))

    def test_partial_bin_and_speech_overlap(self):
        bins = extract_features(self.tone(5, .1), [(1, 3), (4, 4.5)], [])
        self.assertEqual(len(bins), 3)
        self.assertEqual([b['speech_fraction'] for b in bins], [.5, .5, .5])
        self.assertEqual(bins[-1]['end'], 5)
        self.assertEqual(score_bins(bins, dict(pace=0, surge=0, loudness=0, speech=0, change=0)), [0, 0, 0])

    def test_spectral_change_detects_new_sound(self):
        stationary = self.tone(6, .1)
        rng = np.random.default_rng(42)
        noise = rng.normal(0, .1, 4 * SR).astype('float32')
        bins = extract_features(np.concatenate([stationary, noise]), [], [])
        self.assertGreater(bins[3]['signals']['change'], bins[1]['signals']['change'])

    def test_youtube_normalization_and_host_rejection(self):
        self.assertEqual(canonical_youtube('https://youtu.be/BaW_jenozKc?t=1'), 'https://www.youtube.com/watch?v=BaW_jenozKc')
        for u in ('http://youtube.com/watch?v=BaW_jenozKc', 'https://youtube.com.evil.test/watch?v=BaW_jenozKc', 'https://127.0.0.1/test', 'https://youtube.com/playlist?list=abc'):
            with self.assertRaises(ValueError):
                canonical_youtube(u)


if __name__ == '__main__':
    unittest.main()
