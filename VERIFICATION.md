# Release verification

The clean release source was tested on Windows on 2026-11-05. The automated suite ran 26 tests: 25 passed and the opt-in real-model transcription test was skipped. Previous application verification exercised actual local Tiny transcription and playback.

Coverage includes signal scoring, upload/retry/deletion, local-origin checks, media seeking, individual/ZIP/combined exports, precise manual bounds, source-quality propagation, explicit cached recovery, and timestamped DASH fragments with real generated pictures and sound.

The packaged Windows engine was also exercised through its actual web interface. All 12 clips in an actual user-generated ZIP, plus new manual and recommended individual downloads, were compared with the retained input. Sampled first/middle/last pictures matched the requested source positions; whole-clip audio comparisons measured zero offset. The manual 45:08.250–45:10.750 selection produced 2.500 seconds. A recommendation at 1:11:06 with five seconds of lead-in and twelve seconds of moment length produced 1:11:01–1:11:18 (17 seconds). Media and private analysis data are not included in the release.

This is functional verification, not a human-labeled highlight-accuracy or multilingual transcription benchmark. YouTube retrieval depends on upstream availability.

Speaker/event revision: gain-offset regression cases cover 1, 2, 5, and 9 voices, with up to 30 dB between their normal levels. A real within-voice rise remains detectable. Overlap, unknown voices and short references have no volume evidence. JavaScript event checks cover nearby separate events, clear valleys, sustained excitement, plateaus, no top-twelve cutoff, and threshold behavior. Full-precision local diarization detected four voices in the official four-speaker sample without specifying its count; only one voice had the eight seconds of reference required for calibration. This does not constitute a general diarization benchmark.
