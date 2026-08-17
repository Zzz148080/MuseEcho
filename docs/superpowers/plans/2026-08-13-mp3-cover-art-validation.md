# MP3 Cover-art Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept otherwise-valid MP3 files that contain an embedded cover-art stream, while retaining the existing fail-closed audio-decoding policy.

**Architecture:** `ffprobe` must inspect the selected first audio stream without requiring every non-audio stream to satisfy the audio codec whitelist. `ffmpeg` remains unchanged: it maps `0:a:0`, disables video, and retains the strict audio decoder whitelist before producing bounded PCM. A real integration fixture carrying MJPEG cover art protects the behavior.

**Tech Stack:** Python 3.12, pytest, FFmpeg/FFprobe, Docker Linux app image.

## Global Constraints

- Support only WAV and MP3, maximum 30 MiB and 600 seconds.
- Retain `file,pipe` protocol and audio decoder allowlists for decoding.
- Do not add dependencies or download tools.
- Verify in the existing Linux container image and through the live Edge frontend.

---

### Task 1: Probe audio streams without rejecting embedded artwork

**Files:**
- Modify: `src/museecho/analysis/decode.py:375-405`
- Modify: `tests/integration/test_decode.py`

**Interfaces:**
- Consumes: `probe_audio(path, ffprobe_executable=...)`.
- Produces: an `AudioProbe` for MP3 audio with a non-audio attached-picture stream.

- [x] **Step 1: Write the failing real integration test**

Create a short MP3 with an attached MJPEG artwork stream using the existing FFmpeg fixture tools. Call `probe_audio()` and `decode_audio()` on it, asserting a mono decoded duration of approximately one second.

- [x] **Step 2: Run the test to verify it fails**

Run the focused integration test in the existing Linux app image. Expected: `InvalidAudioError: file is not valid WAV or MP3 audio` because `ffprobe` currently applies the audio codec whitelist to MJPEG artwork.

- [x] **Step 3: Write the minimal implementation**

Remove `-codec_whitelist` only from the `ffprobe` metadata command. Keep `-select_streams a:0`; do not change the `ffmpeg` decode command, duration validation, protocol whitelist, format whitelist, mapping, or PCM output limit.

- [x] **Step 4: Run focused and related regression tests**

Run the new cover-art integration test and existing decode tests in the locked Linux container. Expected: PASS, while unsupported codecs remain rejected by the actual decoding command.

- [ ] **Step 5: Commit**

Commit the source, test, and plan on `codex/fix-mp3-cover-art` with a focused message.

### Task 2: Keep decoded waveform and music-theory payloads within the frontend contract

**Files:**
- Modify: `src/museecho/analysis/waveform.py`
- Modify: `tests/unit/analysis/test_signal_features.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`

- [x] **Step 1: Reproduce the result-read failure with production data**

An otherwise-complete upload reported “无法读取分析结果”. Server-side output showed small lossy-decoder waveform overshoot, then a double-sharp pitch class (`C##`) rejected by the frontend schema.

- [x] **Step 2: Add focused regression coverage**

Add a waveform test that includes values outside `[-1, 1]` and a client-contract fixture containing `A#`, `C##`, and `E#`.

- [x] **Step 3: Implement the smallest boundary-preserving fixes**

Clamp only presentation waveform extrema to `[-1, 1]`; accept deterministic one- or two-accidental note spellings without loosening the chord-label contract.

- [x] **Step 4: Verify the focused backend and frontend tests**

The locked Linux image passed the cover-art and waveform regressions; the frontend client suite passed 14 tests. The available offline TypeScript cache lacks `node:fs` declarations, so its unrelated whole-project typecheck remains an explicitly recorded environment limitation.

### Task 3: Rebuild and exercise the real browser flow

**Files:**
- No product files beyond Task 1.

**Interfaces:**
- Consumes: the local development Compose profile and the user-authorized `D:\AI民族音乐\江南烟雨.mp3` file.
- Produces: a completed result page in the existing Edge tab.

- [x] **Step 1: Build the local app and gateway from the source**

Use the existing Compose development profile without changing dependency manifests.

- [x] **Step 2: Upload the user-authorized file in Edge**

Select `D:\AI民族音乐\江南烟雨.mp3`, acknowledge the two upload confirmations, and submit it.

- [x] **Step 3: Verify each live stage**

Verify upload acceptance, real status progression, completion, and successful result rendering. Inspect only project logs if a stage fails.

- [x] **Step 4: Record outcome**

Observed result: analysis `16366c9e-fdb8-4c18-954d-1000029cbc22` rendered on the real Edge page with a 4:36 player, BPM 117, 542 beats, 3 chords, 168 sections, waveform, and an active A# chord. Selecting the chord moved the player to 3:31 with no page alert.

Report the analysis ID, observed final result state, and any remaining browser-control limitation without claiming manual checks that were not performed.
