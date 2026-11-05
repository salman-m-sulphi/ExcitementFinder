# How scoring works

Audio is decoded locally to 16 kHz mono. Measurements use two-second display bins and 20 ms sound frames. The five weights default to word pace 40, volume surge 25, loudness 15, speech activity 10, and sound change 10. The weighted average is a heuristic score, not a probability of excitement.

## Different commentators

Sherpa-ONNX combines a full-precision pyannote segmentation model with a 3D-Speaker CAMPPlus voice-embedding model. Threshold clustering estimates the number of voices (`num_clusters=-1`), without a user-supplied count or hard-coded global commentator cap. Processing uses 180-second cores and five seconds of context; voice embeddings join anonymous speaker profiles across cores. Distinct local clusters cannot collapse into one profile within a core. Embeddings are kept in memory, not written into saved results.

Each voice's baseline is the median level of its non-overlapping, non-silent speech frames throughout the recording. At least eight seconds of reference are required. Speech loudness is positive deviation from this baseline, after a 1 dB deadband, capped at 12 dB. A constant gain difference between voices therefore cancels. Volume surge must exceed both the voice's normal level and the preceding thirty seconds of that same voice. Word pace uses only that voice's word midpoints and speaking duration within centered ten-second windows, compared with its typical rate.

Bins containing an uncertain identity, a voice switch, overlapping speakers, or insufficient reference have no speech volume or pace evidence. Non-speech sound cues remain available. Raw dBFS and the old uncorrected surge remain in the result for inspection. A naturally louder voice can still affect recognition quality; diarization itself is imperfect and may split or merge speakers. This is not a guarantee of exact speaker counts in every mix.

Silero VAD measures speech fraction. Positive changes in normalized FFT spectra measure sound changes, including impacts, music, and crowd noise. At least 95% of frames below −55 dBFS makes a bin silent and forces its score to zero. Non-speech loudness and surge remain recording-relative. Transcription failure disables word pace and displays a warning. Speaker detection failure disables uncertain speech volume and pace rather than falling back to another speaker's level.

## Nearby and sustained moments

The event threshold defaults to 60. An event can continue down to threshold minus 15, so small fluctuations do not chop continuous excitement into separate clips. A valley of at least 15 score points between two strong peaks splits them, even if they occur less than twenty seconds apart. Separate regions crossing below the continuation level remain separate. Flat plateaus are one event. There is no top-twelve truncation or fixed minimum distance between events.

Every retained event includes its full detected start/end range. Download controls add playback lead-in before the event and the selected tail after it. Individual and ZIP downloads retain separate events; the combined video sorts ranges and merges overlaps to avoid repeated footage. Manual In/Out bounds remain independent and exact to frame/packet granularity. Lowering the event threshold exposes weaker candidates; no threshold guarantees every important sporting event will be found.

## Saved analyses and privacy

Older results have an **Update commentator scoring** action. It decodes retained playback, reuses the saved transcript and speech intervals, computes speaker-aware features, and atomically replaces the result only after successful processing. The original result is backed up. Media and transcription settings are preserved; no YouTube redownload or retranscription is needed.

Analysis and inference run locally. First-time models and YouTube sources require internet access. Voices are anonymous labels, not personal identities. The application cannot detect quiet visual action and has no human-labeled highlight-accuracy benchmark.
