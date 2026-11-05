# Excitement Finder

A local Windows application that finds timestamps worth reviewing from commentary and sound. Analyze a recording or public YouTube video, inspect an audio excitement heatmap, search the transcript, and extract clips.

## Download for Windows

Get **ExcitementFinder-Windows.zip** from [Releases](https://github.com/salman-m-sulphi/ExcitementFinder/releases/latest). Extract the entire ZIP to a writable folder and open **ExcitementFinder.exe**. Keep `_internal`, `runtime`, and `library` beside it.

Requires Windows 10/11 x64 and [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/). Python, FFmpeg, Node.js, and the multilingual Tiny model are bundled. This portable build is unsigned.

## Features

- Local audio analysis and multilingual Whisper transcription; no paid API or API key.
- Adjustable scoring from word pace, volume surge, loudness, speech activity, and sound changes.
- Timestamped transcript, heatmap seeking, playback lead-in, and saved analyses.
- Individual moment MP4s, all moments in a ZIP, or a combined chronological video.
- Exact manual In/Out selection and available original/source download qualities.

Scores are audio-based review suggestions, not a visual-action detector or a calibrated probability of excitement. YouTube availability and transcription accuracy vary. Use recordings you have permission to obtain and process. [Download guide](DOWNLOADS.md).

## Run from source

Install Python 3.14 with pip and Node.js, then run **Setup.cmd**, followed by **Start.cmd**. Open http://127.0.0.1:8765. The first use of a transcription model downloads its weights; subsequent local-file analysis can work offline.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

To build the desktop folder:

```powershell
.\.venv\Scripts\python.exe -m pip install -r desktop-requirements.txt
.\.venv\Scripts\python.exe build_desktop.py
```

The result is under `dist/ExcitementFinder`. Analyze a short recording with Tiny before building to cache its weights in `models/`. The build copies cached models into the portable library. Local libraries, videos, logs, browser profiles, and settings are excluded from this repository and release.

## Modules

| Module | Responsibility |
| --- | --- |
| `static/` | HTML/CSS/JavaScript interface, heatmap, transcript, ranking, download controls |
| `app.py` | FastAPI server, saved jobs, uploads, playback, export jobs, local-origin checks |
| `analysis.py` | Audio measurements, local transcription, speech detection, scoring inputs |
| `source_media.py` | Source qualities, interval retrieval, validation, caching |
| `dash_ranges.py` | Timestamp-aware retrieval and trimming of segmented YouTube streams |
| `desktop.py` | Windows window through pywebview/WebView2, local server lifecycle |
| `build_desktop.py` | Portable Windows packaging through PyInstaller |
| `tests/` | Signal, API, export, and fragment-timing regression tests |

The application interface and orchestration were developed for this project with AI assistance. Speech recognition, media decoding/encoding, YouTube retrieval, and the desktop runtime use existing third-party projects. [Analysis details](ANALYSIS.md) and [third-party notices](THIRD_PARTY_NOTICES.txt).

## License and contributions

Original application code is **source-available under [PolyForm Noncommercial 1.0.0](LICENSE)**. You may study, improve, and share it for permitted noncommercial purposes. Commercial use or selling the application or derivatives requires separate permission from the copyright holder. Keep `LICENSE` and the required notices when sharing changes. This is not an OSI-approved open-source license.

Third-party libraries and models retain their own licenses; this application's noncommercial terms do not replace them. Your input media and exported clips remain subject to their original rights.

Improvements and bug reports are welcome. By submitting an original contribution, you agree to license it under the same application license. Identify any third-party code and its license.
