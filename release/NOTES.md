Excitement Finder v1.4.0 adds selective bulk downloads and English subtitles.

- All moments start checked. Use Check all, Uncheck all, or individual checkboxes to choose which moments go in ZIP and combined downloads.
- Enable Include English subtitles (.srt) to use Whisper Medium on the finished clip. Save the separate matching SRT after a single, manual, or combined MP4 download. Bulk ZIPs contain a matching SRT per clip.
- Subtitle times are relative to the downloaded video. Whisper can translate Malayalam and Hindi speech into English, with accuracy affected by noise and language switching. First use may download model weights.
- Whisper tries NVIDIA CUDA, then compatible Vulkan GPUs, then CPU. A separate CUDA runtime may be needed for NVIDIA CUDA. The Vulkan backend is bundled.
- Player labels match the moment list. Individual clips can include up to 30 seconds after the detected end.

Download **ExcitementFinder-Windows.zip**, extract the entire ZIP, and open **ExcitementFinder.exe**. Windows 10 or 11 x64 and WebView2 are required.

The original application code remains under PolyForm Noncommercial 1.0.0. Third-party components retain their licenses. Release files contain no local recordings, analyses, or preferences. Checksums are in SHA256SUMS.txt.
