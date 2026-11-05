Excitement Finder v1.1.1 fixes confusing or missing moment numbers when a selected moment has playback lead-in.

Download ExcitementFinder-Windows.zip, extract the entire ZIP and open ExcitementFinder.exe. Close the previous version before opening the update. Windows 10/11 x64 and WebView2 are required; runtimes and models are included.

- The clicked number appears immediately as Selected moment #25 with a lead-in countdown.
- Once its detected range begins, the badge shows Moment #25 and its exact detected bounds. It clears at the detected out point; playback continues and follows later detected events.
- A previous event crossed during lead-in no longer looks like the selected moment. Cards display detected bounds consistently with the playing badge.
- Floating-window reselection ignores stale playback updates from the previous selection.
- Existing floating-window, fullscreen, scoring and download features are retained.

Verified with the actual Windows player using the real #25/#19 collision, plus floating-window reselection, fullscreen, return and native close. Event/player JavaScript regressions and the Windows release checks must pass before publication.

The PolyForm Noncommercial license for original application code is unchanged. Third-party components retain their own licenses. No recordings, analyses, browser profiles or local preferences are included. Checksums are in SHA256SUMS.txt.
