# Changelog

## 1.4.0

- Select which moments to include in ZIP and combined downloads. All moments start checked.
- Optionally export English SRT sidecars using Whisper Medium on the finished clip audio.

## 1.3.0

- Automatically use NVIDIA CUDA or a compatible Vulkan GPU for Whisper transcription.
- Try the next compatible GPU backend and then CPU if inference fails.
- Show the transcription device in progress and in completed analyses.

## 1.2.0

- Use the same moment numbers in the review list and all player modes.
- Preserve selected-moment labels when handing off playback to the floating window.
- Add an independent end extension and export range preview to each individual clip.

## 1.1.1

- Immediately identify the clicked moment during playback lead-in, with a countdown.
- Prevent an earlier event crossed by the lead-in from looking like the selected moment.
- Show the detected range consistently on cards and the playing badge.
- Ignore stale floating-player updates after selecting another moment.
- Verify the real #25/#19 lead-in collision and reselection through the native Windows player.

## 1.1.0 — 2026-11-06

- Detected event numbers over the player, automatic next-event labels, and active-row highlighting.
- Bottom-right docking while scrolling, with return and hide controls.
- Separate resizable, always-on-top Windows player with synchronized playback and controls.
- Fullscreen with moment labels, Escape to exit, and safe playback return on window close.
- Browser pop-out fallback and playback-aware manual In/Out controls.
- Include Node.js runtime notices when the installed runtime does not provide a local LICENSE file.

## 1.0.0

- Automatic commentator-count estimation and same-voice level/pace normalization.
- Conservative suppression of uncertain speech evidence and saved-result scoring updates.
- Full event ranges, nearby-peak retention, adjustable threshold/tail, and removal of top-twelve truncation.

- Initial portable Windows release with local analysis and multilingual transcription.
- Ranked audio moments, heatmap, transcript search, and saved analyses.
- Individual MP4, all-moments ZIP, and combined chronological exports.
- Source-quality selection and precise manual In/Out ranges.
- Timestamp-aware segmented YouTube retrieval with explicit cached-source recovery.
- PolyForm Noncommercial licensing for original application code.
