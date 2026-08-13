from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

ValidatorKind = Literal[
    "wave",
    "mp3",
    "flac",
    "iso_bmff",
    "adts",
    "ogg_vorbis",
    "ogg_opus",
]

PCM_CODECS = (
    "pcm_u8",
    "pcm_s16le",
    "pcm_s24le",
    "pcm_s32le",
    "pcm_f32le",
    "pcm_f64le",
)


@dataclass(frozen=True)
class AudioFormat:
    suffix: str
    canonical_media_type: str
    format_aliases: tuple[str, ...]
    allowed_codecs: tuple[str, ...]
    validator_kind: ValidatorKind


AUDIO_FORMATS = (
    AudioFormat(".wav", "audio/wav", ("wav",), PCM_CODECS, "wave"),
    AudioFormat(
        ".mp3",
        "audio/mpeg",
        ("mp3",),
        ("mp3float", "mp3"),
        "mp3",
    ),
    AudioFormat(".flac", "audio/flac", ("flac",), ("flac",), "flac"),
    AudioFormat(
        ".m4a",
        "audio/mp4",
        ("mov", "mp4", "m4a", "3gp", "3g2", "mj2"),
        ("aac", "alac"),
        "iso_bmff",
    ),
    AudioFormat(".aac", "audio/aac", ("aac",), ("aac",), "adts"),
    AudioFormat(".ogg", "audio/ogg", ("ogg",), ("vorbis",), "ogg_vorbis"),
    AudioFormat(".opus", "audio/opus", ("ogg",), ("opus",), "ogg_opus"),
)

AUDIO_FORMATS_BY_SUFFIX = MappingProxyType({item.suffix: item for item in AUDIO_FORMATS})


def audio_format_for_suffix(suffix: str) -> AudioFormat:
    return AUDIO_FORMATS_BY_SUFFIX[suffix.lower()]


def probe_matches_audio_format(
    audio_format: AudioFormat, *, format_name: str, codec_name: str
) -> bool:
    detected_aliases = frozenset(format_name.split(","))
    return bool(detected_aliases.intersection(audio_format.format_aliases)) and (
        codec_name in audio_format.allowed_codecs
    )


def matching_audio_format(*, format_name: str, codec_name: str) -> AudioFormat | None:
    for audio_format in AUDIO_FORMATS:
        if probe_matches_audio_format(
            audio_format,
            format_name=format_name,
            codec_name=codec_name,
        ):
            return audio_format
    return None


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


INPUT_FORMATS = _ordered_unique(
    tuple(alias for audio_format in AUDIO_FORMATS for alias in audio_format.format_aliases)
)
INPUT_CODECS = _ordered_unique(
    tuple(codec for audio_format in AUDIO_FORMATS for codec in audio_format.allowed_codecs)
    + ("mjpeg",)
)
INPUT_FORMAT_WHITELIST = ",".join(INPUT_FORMATS)
INPUT_CODEC_WHITELIST = ",".join(INPUT_CODECS)
INPUT_PROTOCOL_WHITELIST = "file,pipe"


__all__ = [
    "AUDIO_FORMATS",
    "AUDIO_FORMATS_BY_SUFFIX",
    "AudioFormat",
    "INPUT_CODEC_WHITELIST",
    "INPUT_FORMAT_WHITELIST",
    "INPUT_PROTOCOL_WHITELIST",
    "audio_format_for_suffix",
    "matching_audio_format",
    "probe_matches_audio_format",
]
