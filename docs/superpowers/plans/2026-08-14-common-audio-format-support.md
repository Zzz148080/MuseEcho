# Common Audio Format Support Implementation Plan

**Goal:** Safely accept and analyze common non-DRM music-file formats without a front-end/back-end format mismatch.

**Architecture:** A single server format registry ties suffixes to detected FFmpeg demuxers and canonical stored media types. Format-specific signature validation rejects malformed inputs before the existing bounded FFmpeg probe/decode; the coordinator maps stored type back to a safe temporary suffix. The front end lists the same public extensions as the server registry tests.

## Global Constraints

- Keep the 30 MB upload and 10-minute duration limits unchanged.
- Do not trust MIME type or extension alone.
- Permit only WAV/MP3/FLAC/AAC/ALAC/Vorbis/Opus audio decoders and required demuxers over `file,pipe`.
- Do not support DRM or proprietary encrypted download formats.
- Do not alter result-page design or analysis algorithms.

## Tasks

1. Add server registry, signature validation, full-stream probe validation, exact FFprobe/FFmpeg allowlists, and real acceptance/rejection integration coverage.
2. Restore encrypted pipeline source suffix from the shared canonical media-type registry and test every canonical type.
3. Expand the browser chooser using exact suffix filters only, update upload guidance/README, and verify frontend/container/smoke paths.
