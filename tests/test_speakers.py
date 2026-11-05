import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from analysis import SR, extract_features
from speakers import normalize_speaker_features


class SpeakerScoringTests(unittest.TestCase):
    def analyze_voices(self, levels, excitement=False, frame_path=False):
        audio, turns = [], []
        for speaker, db in enumerate(levels):
            amplitude = .5 * 10 ** (db / 20)
            block = amplitude * np.sin(2*np.pi*(180+speaker*30)*np.arange(30*SR)/SR)
            if excitement and speaker == len(levels)-1:
                block[20*SR:24*SR] *= 10
            audio.append(block.astype('float32'))
            turns.append(dict(start=speaker*30,end=(speaker+1)*30,speaker=speaker))
        duration = 30*len(levels)
        sound = np.concatenate(audio)
        bins = extract_features(sound, [(0,duration)], [])
        info = normalize_speaker_features(bins, turns, [], sound if frame_path else None)
        return bins, info

    def test_different_number_of_commentators_and_large_gain_offsets(self):
        for count in (1,2,5,9):
            with self.subTest(count=count):
                levels = np.linspace(-40,-10,count)
                for frame_path in (False,True):
                    bins,info=self.analyze_voices(levels,frame_path=frame_path)
                    self.assertEqual(info['detected_speakers'],count)
                    self.assertEqual(info['calibrated_speakers'],count)
                    self.assertTrue(all(b['signals']['surge']==0 and b['signals']['loudness']==0 for b in bins))

    def test_actual_rise_within_one_voice_is_retained(self):
        bins,_=self.analyze_voices([-35,-25,-20],True)
        self.assertGreater(bins[40]['signals']['surge'],.9)
        self.assertGreater(bins[40]['signals']['loudness'],.9)
        self.assertEqual(bins[30]['signals']['surge'],0)  # Third voice enters louder.

    def test_overlap_unknown_and_short_reference_do_not_use_other_voice_level(self):
        sound=(.1*np.sin(2*np.pi*220*np.arange(12*SR)/SR)).astype('float32')
        for turns in ([],[dict(start=0,end=12,speaker=None)], [dict(start=0,end=12,speaker=0),dict(start=0,end=12,speaker=1)], [dict(start=0,end=4,speaker=0),dict(start=4,end=8,speaker=1),dict(start=8,end=12,speaker=2)]):
            bins=extract_features(sound,[(0,12)],[])
            normalize_speaker_features(bins,turns,[])
            self.assertTrue(all(b['signals']['surge']==0 and b['signals']['loudness']==0 for b in bins))

    def test_diarized_speech_is_corrected_even_if_vad_misses_it(self):
        first=.005*np.sin(2*np.pi*180*np.arange(20*SR)/SR)
        second=.15*np.sin(2*np.pi*250*np.arange(20*SR)/SR)
        audio=np.concatenate([first,second]).astype('float32')
        bins=extract_features(audio,[],[])
        turns=[dict(start=0,end=20,speaker=0),dict(start=20,end=40,speaker=1)]
        normalize_speaker_features(bins,turns,[],audio)
        self.assertTrue(all(b['signals']['surge']==0 and b['signals']['loudness']==0 for b in bins))

    def test_voice_switch_does_not_earn_a_timbre_change_bonus(self):
        bins,_=self.analyze_voices([-30,-10])
        self.assertEqual(bins[15]['signals']['change'],0)


if __name__=='__main__':unittest.main()
