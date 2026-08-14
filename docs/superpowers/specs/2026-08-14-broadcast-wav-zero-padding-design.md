# Broadcast WAV Zero-Padding Compatibility Design

## Problem

MuseEcho rejects `D:\CloudMusic\华晨宇 - 忒修斯的船.wav` before FFprobe even though the file is a valid Pro Tools Broadcast WAV. Its RIFF and WAVE boundaries are correct, FFprobe identifies one `pcm_s24le` stream with probe score 99, and its duration is 289.065 seconds. The file uses a 40-byte non-extensible PCM `fmt ` chunk whose declared extension size and remaining 22 padding bytes are all zero. MuseEcho currently accepts non-extensible PCM `fmt ` chunks only when their length is exactly 16 or 18 bytes.

## Decision

Keep the existing strict RIFF chunk traversal and PCM field checks. For non-extensible PCM or IEEE-float WAVE formats:

- continue accepting the canonical 16-byte `fmt ` payload;
- accept payloads of 18 through 64 bytes only when `cbSize` is zero and every byte after `cbSize` is zero padding;
- reject any non-zero trailing byte, non-zero extension size, duplicate or reordered `fmt `/`data` chunks, inconsistent RIFF length, or invalid PCM rate/alignment fields;
- leave WAVEFORMATEXTENSIBLE validation unchanged.

This is narrower than delegating signature trust to FFprobe and more portable than whitelisting a Pro Tools-specific chunk sequence.

## Verification

Add focused tests that construct the same 40-byte PCM `fmt ` layout and prove that validation reaches the existing probe/decode boundary. Add a paired rejection test with one non-zero padding byte. Run the upload test module, then rebuild/reload the development app and submit the user's original WAV through `https://localhost:4173/api/analyses`. A successful fix returns HTTP 202 and creates an analysis instead of returning `invalid_audio` or gateway 502.
