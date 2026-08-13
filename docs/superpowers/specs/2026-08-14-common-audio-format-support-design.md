# Common Audio Format Support Design

## Goal

Safely accept common non-DRM music formats without creating a browser/server mismatch or weakening the existing bounded audio-decode boundary.

## Supported input contract

| Extension | Stored media type | Allowed audio codec(s) | Demuxer |
| --- | --- | --- | --- |
| `.wav` | `audio/wav` | PCM | `wav` |
| `.mp3` | `audio/mpeg` | MP3 | `mp3` |
| `.flac` | `audio/flac` | FLAC | `flac` |
| `.m4a` | `audio/mp4` | AAC, ALAC | `mov,mp4,m4a,3gp,3g2,mj2` |
| `.aac` | `audio/aac` | AAC | `aac` |
| `.ogg` | `audio/ogg` | Vorbis | `ogg` |
| `.opus` | `audio/opus` | Opus | `ogg` |

Only these extensions and format/codec pairings are accepted. DRM/proprietary encrypted downloads and video/container variants remain unsupported. FFprobe validates every stream, rejects non-attached video and disallowed extra audio, and has exactly the same protocol, demuxer and codec whitelist as FFmpeg. A MP3-attached MJPEG cover remains explicitly supported and is never decoded as audio.

## Pipeline

One immutable Python registry owns extension, canonical stored media type, signature validator kind, demuxer aliases and permitted codec list. Upload uses it to validate the staged actual suffix and source/probe pairing. Coordinator resolves the stored canonical media type through the same registry when materializing encrypted plaintext, retaining the safe decoder suffix. Browser offers the exact extension list only; it does not treat browser MIME detection as trusted validation.
