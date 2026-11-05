# Analysis and development guide

## Use the map

- **Gray** marks near-silence. Cool blue/green through orange/red marks increasing audio cue scores.
- Move the pointer across the map to inspect timestamp, word density, dBFS, local volume rise, and detected speech fraction. Click to seek. With the map focused, arrow keys step by two seconds; Home/End move to its ends.
- Five independent sliders change the mix immediately without repeating analysis. Their weights are relative; they need not add up to 100. Setting all weights to zero produces no ranked moments.
- Ranked cards provide review windows starting at scored timestamps, with the three largest contributions shown in **score points**. A card's number scores its first two-second bin, not the average of the whole twelve-second review window. Picks are spaced at least twenty seconds apart; up to twelve appear.
- Search the timestamped transcript and click a line to review it. Current spoken text follows playback.
- **Export results** saves JSON containing timestamped word groups, transcript, measurements, normalized signals, current weights, scores, and ranked windows.
- Saved analyses survive a restart. Use **Open** to review them or **Delete** to remove their stored media and results. Running jobs cannot be deleted; stop the server to interrupt processing. Interrupted jobs are marked as errors after restart. **Retry** repeats analysis with the saved settings and resumes partial YouTube downloads where supported, avoiding an unnecessary download from the beginning.

## What is actually measured

The app decodes the first audio track to mono 16 kHz. It does not inspect image content, infer sentiment, or use a fabricated excitement model.

| Signal | Measurement | Default weight |
| --- | --- | ---: |
| Word pace | Whisper word-group midpoints in centered ten-second windows, expressed per minute. 70% recording-relative pace and 30% a 240-groups/minute reference. | 40 |
| Volume surge | Two-second RMS loudness minus the median of the preceding thirty seconds, excluding the current bin. Baseline floor is −55 dBFS; +12 dB reaches maximum signal strength. | 25 |
| Relative loudness | Two-second RMS level normalized using the non-silent bins' 20th–95th percentile range. | 15 |
| Speech activity | Fraction of each two-second bin detected as speech by local Silero VAD. | 10 |
| Abrupt sound changes | Mean positive changes in normalized FFT spectra over 20 ms frames, ignoring near-silent frames; scaled by non-silent bins' percentiles. | 10 |

Word pace is scaled using the recording's 20th–95th percentile range. A constant relative signal becomes zero rather than inventing differences. Each normalized signal lies between zero and one. The weighted average is multiplied by 100. This is an explainable ranking heuristic, **not a calibrated probability of excitement**.

Bins with at least 95% of 20 ms frames below −55 dBFS are gray and score zero, even if transcription mistakenly supplies words there. Silence is an absolute digital-level rule; very quiet recordings can therefore need external audio normalization before import. If transcription is disabled, fails, or yields no words, its weight is excluded and the other signals remain usable. A visible warning explains disabled or failed transcription.

For multi-hour recordings, decoded samples use a disk-backed array, speech detection runs in one-minute chunks with context, and Whisper runs in three-minute chunks with two seconds of context. Word midpoints assign overlapping context to one core chunk to avoid duplicated words. Language auto-detection runs per transcription chunk; selecting a known commentary language can improve consistency. Chunk boundaries and imperfect word timestamps can still affect a few words. On dense timelines, a display pixel shows the strongest bin it covers so brief peaks remain visible; pointer details and exports retain the actual two-second bins.

## Models and multilingual recordings

Tiny is pre-downloaded and is the quickest starting point. Base and Small usually offer a useful accuracy tradeoff; Medium uses substantially more RAM and CPU time. The first use of each additional model downloads its free weights from Hugging Face. There is no API key, subscription, or paid transcription service.

All offered models are multilingual variants. Choose a listed language, automatic detection, or **Other language code** (for example `ml`). Word boundaries differ between languages, especially those without spaces, so the UI deliberately calls them **word-groups**. Compare pace within the same recording; do not interpret it as a language-independent linguistic word count. Overlapping speech, accents, crowd noise, and mixed languages can reduce transcription quality. English was exercised in the real speech integration test; accuracy in other languages was not benchmarked.

## YouTube

The importer accepts single HTTPS watch, shorts, embed, and youtu.be links. It uses yt-dlp with its installed JavaScript support and Node, requests video up to 720p with audio, and uses FFmpeg to merge separate streams where necessary. It does not import browser cookies, sign in, or circumvent restrictions. Playlists and live streams are unsupported.

Retrieval depends on what YouTube makes available from this computer. Private, removed, restricted, geographically unavailable, or temporarily blocked videos can fail. The app gives the underlying error and asks for a local upload. Use a local recording or a copy you have permission to obtain. Uploading such a copy does not depend on YouTube retrieval.

If public-video retrieval later stops working, update the downloader and its JavaScript helper from this folder, then restart the app:

```powershell
.\.venv\Scripts\python.exe -m pip install -U --pre "yt-dlp[default]"
```

Official references consulted for implementation: [faster-whisper timestamps and VAD](https://github.com/SYSTRAN/faster-whisper), [yt-dlp formats, FFmpeg, and JavaScript runtime requirements](https://github.com/yt-dlp/yt-dlp), and [bundled FFmpeg distribution](https://pypi.org/project/imageio-ffmpeg/).

## Practical limits and storage

- Eight GiB per upload/download stream and eight hours per recording; up to three jobs can be pending, with one analysis at a time. A large YouTube download or a long CPU transcription can take several minutes or longer. There is no GPU acceleration in this build.
- Inputs need a decodable audio track. The first video track and first audio track are used; other audio tracks are not selectable in this version.
- Browser-compatible H.264/AAC is remuxed without recompressing the video. Other codecs get an H.264/AAC playback preview up to 720p; that conversion adds time. Audio-only files are supported and play through the same media player.
- `data/<analysis-id>/` stores the original file, a playback copy, result JSON, and status. Temporary mono audio uses about 230 MB per hour during analysis and is removed after success; failed jobs may retain it until deleted. Leave room for the original, playback, temporary audio, and any YouTube stream merge files.
- `models/` stores downloaded weights. Models stay after deleting an analysis so they can be reused offline. The original input is copied into this app; deleting an analysis never deletes the file you selected outside it.
- Video is not sent to an external analysis service. YouTube ingestion, higher-quality source interval retrieval, and first-time model downloads require the internet. Once a model is cached, local-file analysis and original-upload exports run locally without internet access.
- Music, cheering, advertisements, and sound effects can score highly. Quiet visual action can score low. These are timestamps to **review**, not guaranteed highlights. The app exports recommended or manually selected sections; visual-action detection and a general video editor are outside its scope.

## Reinstall and validate

For a fresh installation, install Python 3.14 for Windows with pip and Node.js, then run **Setup.cmd**. Internet access is required. The script creates `.venv` and installs pinned direct dependencies from `requirements.txt`; FFmpeg is bundled by `imageio-ffmpeg`. If moving the folder to another computer or Python installation, recreate `.venv` with Setup rather than copying a virtual environment.

From this folder, run the automated signal and API checks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests exercise real generated audio, silence, pace, a known volume rise, speech overlap, sound changes, upload/analysis, seekable media range responses, invalid inputs, local-origin restrictions, and deletion. See **VERIFICATION.md** for the actual browser and YouTube check outcomes. No highlight-accuracy benchmark or manual annotation dataset is included.

To also run the real Tiny transcription test (downloads model weights if not already cached):

```powershell
$env:RUN_TRANSCRIPTION_TEST = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
