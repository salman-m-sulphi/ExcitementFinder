# Source quality and exact In / Out downloads

Updated November 5, 2026. These controls are included in both the local browser app and Windows desktop application.

## Choose download quality

In **Moments to check**, use **Download quality**. The same setting appears under **Download any section · In / Out**. Both selectors stay synchronized, and the app remembers the choice for each recording on this computer.

- For a local upload, the default is **original upload** at its actual resolution. Smaller resolutions are offered when the original supports them. All of these exports read the retained original, independently of the playback proxy. There are no fake higher-resolution/upscaling options.
- For YouTube, the app checks actual non-DRM video formats and offers their available resolutions, with the highest available resolution selected initially. **Refresh qualities** checks availability again. Each export requests only the selected intervals via yt-dlp and FFmpeg; there is no automatic full high-resolution video download.
- **Cached analysis source (offline)** is a separate, clearly labelled option for YouTube recordings. It uses the already downloaded source at its actual resolution, which may be lower than the video's highest available quality.
- If the original is missing and only a playback copy remains, the selector explicitly says **playback proxy**. It cannot restore original detail.

The choice applies to individual recommended clips, **Download all · ZIP**, **Combined video**, and exact manual ranges. Video is encoded as H.264/AAC MP4; source resolution is preserved or deliberately reduced. This is not a lossless stream-copy export.

## Download recommended moments

Choose **Moment length** (12, 20, 30, or 60 seconds after the recommended timestamp), then use the card's **Download clip** button. These recommended clips also include your selected playback lead-in, clipped to the start/end of the recording.

**Download all · ZIP** saves each listed moment as a separate MP4 plus `timestamps.json` documenting requested ranges, chosen source quality, measured output dimensions, and source origin.

**Combined video** sorts the listed ranges chronologically and merges overlapping ranges so footage is not repeated at an overlap.

## Download any manually selected section

1. Seek to the desired start and click **Mark In from player**.
2. Seek to the desired end and click **Mark Out from player**.
3. Alternatively, set **Heatmap click** to **Set In point** / **Set Out point**, then click the map. A highlighted region shows the selected bounds. Change back to **Seek playback** for ordinary heatmap navigation.
4. Edit either timestamp for precision. Accepted formats are `HH:MM:SS.mmm`, `MM:SS.mmm`, or numeric seconds such as `2708.250`.
5. Use **Preview selection** to review the range, choose its download quality, and click **Download selected range**.

Manual ranges work even if there are no recommended moments or all scoring weights are zero. **Playback lead-in never changes manual In/Out bounds.** Out must follow In by at least 0.1 seconds, and both must be inside the recording. Invalid inputs disable the download button. There is no two-second heatmap-bin snapping of typed or player-marked timestamps. Video frames and AAC audio packets impose their normal timing granularity; the encoded duration can differ by approximately a frame/audio packet from a millisecond selection.

## YouTube limitations and fallback

Archived live broadcasts can expose DASH fragments instead of a complete seekable MP4. The repaired downloader reads the fragment manifest, fetches only initialization and the nearby video/audio fragments, retains their original presentation timestamps, and trims the exact selected interval before encoding. Repeated MP4 headers are handled explicitly. This fixes the earlier failure caused by sending FFmpeg an unseekable stream base URL.

For **Kerala Race Wars 01**, real **1080p and 2160p/4K** short-section downloads now pass. A 45:08.250–45:10.750 selection produced a 2.500-second file with 150 frames and audio at each resolution. Comparing the final 1080p MP4 against the saved source measured zero video-frame offset and zero audio offset. Initial transfers were approximately 8.7 MB at 1080p and 19.0 MB at 4K, including necessary initialization/nearby fragments; no entire high-resolution recording was downloaded.

Availability can still change or a network request can fail. Such a failure displays a useful message and, when a retained source exists, **Retry same selection using cached … (lower quality)**. Clicking this button explicitly changes to the cached quality and retries the same bounds. There is no automatic downgrade or whole-source caching. Signed stream URLs are removed from diagnostics, and internal FFmpeg return codes are kept out of the main user error message. The app does not sign in or bypass access restrictions.

Very long manual ranges and high-resolution encoding take more processing time and disk space. Generated exports and reusable downloaded source sections stay under the analysis's data folder; deleting that analysis removes them. Closing the desktop app while processing prompts before interrupting the job.
