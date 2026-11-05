Initial Windows release with both commentator-level and nearby-event corrections.

Download ExcitementFinder-Windows.zip, extract the whole ZIP, and run ExcitementFinder.exe. Windows 10/11 x64 and Microsoft Edge WebView2 Runtime are required. Python, FFmpeg, Node.js, Whisper Tiny, and local speaker models are bundled. The portable app is unsigned.

- Automatic speaker clustering without entering a commentator count; per-voice volume and pace baselines.
- Unknown, overlapping or short-reference speech contributes no volume/pace evidence.
- Full event ranges keep nearby peaks separated by meaningful valleys, extend through sustained excitement, and have no top-twelve cutoff. Threshold, lead-in and tail are adjustable.
- Update older saved scoring using retained media/transcript, preserving the previous result.
- Individual MP4, all-events ZIP, combined video, source-quality selection, and precise manual In/Out export.

Validation: 27 Python tests passed, one optional transcription test skipped, and event-selection regression checks passed. Count-free diarization separated the four-voice reference example; speaker detection remains imperfect with overlap, short turns and background audio. Scores are review suggestions, not guaranteed highlights.

Original application code: PolyForm Noncommercial 1.0.0. Improvements and noncommercial sharing are welcome; commercial use or selling the app or derivatives requires separate permission. Third-party components retain their own licenses. Input and exported media retain their original rights.

No recordings, saved analyses, logs, or local settings are included. SHA256SUMS.txt verifies the archives. The release is built from this tag's source and tested on a clean Windows runner, including the actual frozen engine and bundled speaker inference.
