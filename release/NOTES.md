Excitement Finder v1.1.0 adds the floating review player.

Download ExcitementFinder-Windows.zip, extract the whole ZIP, and open ExcitementFinder.exe. Requires Windows 10/11 x64 and Microsoft Edge WebView2 Runtime. Python, FFmpeg, Node.js, Whisper Tiny, and speaker models are included. The portable app is unsigned.

- Moment numbers show only inside detected event areas, clear between them, and automatically follow the next event during continuous playback.
- The active moment is highlighted in the list. Lead-in and export tail do not extend the moment label.
- The player docks at the bottom-right while scrolling.
- Floating window opens a separate, resizable, always-on-top Windows player, with one active audio owner and synchronized position, volume, speed, and pause state.
- Fullscreen works in the app and floating window while retaining the moment number. Escape exits; closing or returning the floating player resumes in the app.
- Existing commentator normalization, nearby-event retention, source-quality downloads, ZIP/combined exports, and manual In/Out selection remain available.

Validation: 30 Python tests passed, one optional transcription test skipped; JavaScript event and player-boundary checks passed. Actual native window checks covered moment #24, continuous playback after the detected out point, corner docking, always-on-top pop-out, fullscreen/Escape, return, immediate reopen, and the Windows X button.

Original application code remains PolyForm Noncommercial 1.0.0: improvements and noncommercial sharing are welcome; commercial use or selling the app or derivatives requires separate permission. Third-party components retain their own licenses. Input and exported media retain their original rights.

No recordings, saved analyses, logs, profiles, or local settings are included. SHA256SUMS.txt verifies both release archives. Keep the entire extracted folder together. See PLAYER.md for controls and browser differences.
