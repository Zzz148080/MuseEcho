# Broadcast WAV Zero-Padding Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept valid Pro Tools Broadcast WAV files whose ordinary PCM `fmt ` chunk contains only zero padding, without weakening MuseEcho's signature validation.

**Architecture:** Extend only `_validate_pcm_wave_format` in the upload boundary. Preserve the existing RIFF parser, registry, FFprobe/FFmpeg validation, upload limits, duration limits, and codec policy.

**Tech Stack:** Python 3.12, pytest, FastAPI upload service, FFprobe/FFmpeg, Docker Compose.

## Global Constraints

- The maximum audio payload remains exactly `100 * 1024 * 1024` bytes.
- Non-extensible PCM padding is accepted only when `cbSize == 0` and every trailing byte is zero.
- WAVEFORMATEXTENSIBLE, chunk ordering, RIFF length, PCM field, decode, and duration checks remain unchanged.
- The user's original WAV must pass through the real HTTPS gateway after the fix.

---

### Task 1: Accept Zero-Padded Ordinary PCM `fmt ` Chunks

**Files:**
- Modify: `tests/api/test_upload.py`
- Modify: `src/museecho/application/uploads.py`

**Interfaces:**
- Consumes: `_minimal_wave(...)`, `FFmpegAudioValidator`, and `audio_format_for_suffix(".wav")`.
- Produces: `_validate_pcm_wave_format(format_data: bytes) -> None` accepting canonical PCM data plus bounded all-zero padding.

- [ ] **Step 1: Write the failing acceptance and rejection tests**

Construct a PCM WAVE whose `fmt ` payload is the canonical 16 bytes followed by `cbSize=0` and 22 zero bytes. Assert that `FFmpegAudioValidator` reaches the monkeypatched `probe_audio` and `decode_audio` calls. In a paired test, replace the last padding byte with `\x01` and assert `InvalidAudioError` occurs before either tool is called.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/api/test_upload.py -k "zero_padded_pcm_format" -q`

Expected: the acceptance case fails with `InvalidAudioError: audio file signature is invalid`; the non-zero padding rejection passes.

- [ ] **Step 3: Implement the minimal validation change**

For non-extensible formats, retain the 16-byte canonical case. Otherwise require at least 18 bytes, require the two-byte extension size at offset 16 to be zero, and reject when any byte from offset 18 onward is non-zero. Keep the existing 64-byte outer `fmt ` chunk bound.

- [ ] **Step 4: Verify focused and module tests GREEN**

Run: `python -m pytest tests/api/test_upload.py -k "zero_padded_pcm_format" -q`

Expected: 2 passed.

Run: `python -m pytest tests/api/test_upload.py -q`

Expected: every runnable upload test passes; environment-specific skips remain explicit.

- [ ] **Step 5: Verify the actual file through the development stack**

Restart the development app if reload has not applied the source change. Submit `D:\CloudMusic\华晨宇 - 忒修斯的船.wav` through `https://localhost:4173/api/analyses`, verify HTTP 202, verify the analysis reaches a terminal successful stage, and verify both Compose services remain healthy.

- [ ] **Step 6: Commit**

Stage only the two source/test files plus this design and plan, then commit with message `fix: accept zero-padded broadcast wav formats`.
