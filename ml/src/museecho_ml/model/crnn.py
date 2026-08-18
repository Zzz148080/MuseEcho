from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import torch
from torch import Tensor, nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence


@dataclass(frozen=True)
class CrnnConfig:
    input_channels: int = 1
    main_conv_channels: tuple[int, ...] = (16, 32)
    bass_conv_channels: tuple[int, ...] = (8, 16)
    gru_hidden_size: int = 96
    gru_layers: int = 2
    dropout: float = 0.2
    bidirectional: bool = True
    root_classes: int = 14
    quality_classes: int = 11
    bass_classes: int = 14

    def __post_init__(self) -> None:
        integer_values = (
            self.input_channels,
            self.gru_hidden_size,
            self.gru_layers,
            self.root_classes,
            self.quality_classes,
            self.bass_classes,
            *self.main_conv_channels,
            *self.bass_conv_channels,
        )
        if any(type(value) is not int or value <= 0 for value in integer_values):
            raise ValueError("CRNN dimensions must be positive integers")
        if not self.main_conv_channels or not self.bass_conv_channels:
            raise ValueError("CRNN convolution branches must be non-empty")
        if (
            isinstance(self.dropout, bool)
            or not isinstance(self.dropout, (int, float))
            or not math.isfinite(self.dropout)
            or not 0 <= self.dropout < 1
        ):
            raise ValueError("CRNN dropout must be within [0, 1)")
        if type(self.bidirectional) is not bool:
            raise ValueError("CRNN bidirectional must be boolean")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CrnnConfig:
        required = {
            "schema_version",
            "model_version",
            "input_channels",
            "main_conv_channels",
            "bass_conv_channels",
            "gru_hidden_size",
            "gru_layers",
            "dropout",
            "bidirectional",
            "root_classes",
            "quality_classes",
            "bass_classes",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("CRNN config fields are invalid")
        if value["schema_version"] != 1 or value["model_version"] != "crnn-v1":
            raise ValueError("CRNN config version is unsupported")
        for field in ("main_conv_channels", "bass_conv_channels"):
            if not isinstance(value[field], list):
                raise ValueError(f"CRNN {field} must be a list")
        return cls(
            input_channels=value["input_channels"],
            main_conv_channels=tuple(value["main_conv_channels"]),
            bass_conv_channels=tuple(value["bass_conv_channels"]),
            gru_hidden_size=value["gru_hidden_size"],
            gru_layers=value["gru_layers"],
            dropout=value["dropout"],
            bidirectional=value["bidirectional"],
            root_classes=value["root_classes"],
            quality_classes=value["quality_classes"],
            bass_classes=value["bass_classes"],
        )


@dataclass(frozen=True)
class ChordLogits:
    root: Tensor
    quality: Tensor
    bass: Tensor
    boundary: Tensor


class ChordCrnn(nn.Module):
    def __init__(self, config: CrnnConfig) -> None:
        super().__init__()
        self.config = config
        self.main_encoder = _FrequencyEncoder(
            config.input_channels, config.main_conv_channels, config.dropout
        )
        self.bass_encoder = _FrequencyEncoder(
            config.input_channels, config.bass_conv_channels, config.dropout
        )
        encoder_size = config.main_conv_channels[-1] + config.bass_conv_channels[-1]
        self.temporal = nn.GRU(
            encoder_size,
            config.gru_hidden_size,
            num_layers=config.gru_layers,
            batch_first=True,
            dropout=config.dropout if config.gru_layers > 1 else 0.0,
            bidirectional=config.bidirectional,
        )
        temporal_size = config.gru_hidden_size * (2 if config.bidirectional else 1)
        self.output_dropout = nn.Dropout(config.dropout)
        self.root_head = nn.Linear(temporal_size, config.root_classes)
        self.quality_head = nn.Linear(temporal_size, config.quality_classes)
        self.bass_head = nn.Linear(temporal_size, config.bass_classes)
        self.boundary_head = nn.Linear(temporal_size, 1)

    def forward(self, main: Tensor, bass: Tensor, mask: Tensor) -> ChordLogits:
        _validate_inputs(main, bass, mask, self.config)
        input_mask = mask[:, None, None, :]
        main_encoded = self.main_encoder(main * input_mask)
        bass_encoded = self.bass_encoder(bass * input_mask)
        encoded = torch.cat((main_encoded, bass_encoded), dim=-1)
        lengths = mask.sum(dim=1).to(dtype=torch.int64, device="cpu")
        packed = pack_padded_sequence(
            encoded, lengths, batch_first=True, enforce_sorted=False
        )
        packed_output, _ = self.temporal(packed)
        temporal, _ = pad_packed_sequence(
            packed_output, batch_first=True, total_length=main.shape[-1]
        )
        temporal = self.output_dropout(temporal)
        return ChordLogits(
            root=self.root_head(temporal),
            quality=self.quality_head(temporal),
            bass=self.bass_head(temporal),
            boundary=self.boundary_head(temporal).squeeze(-1),
        )


class _FrequencyEncoder(nn.Module):
    def __init__(
        self, input_channels: int, channels: tuple[int, ...], dropout: float
    ) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        current = input_channels
        for output in channels:
            layers.extend(
                (
                    nn.Conv2d(current, output, kernel_size=3, padding=1),
                    nn.GroupNorm(_group_count(output), output),
                    nn.GELU(),
                    nn.Dropout2d(dropout),
                    nn.MaxPool2d(kernel_size=(2, 1)),
                )
            )
            current = output
        self.network = nn.Sequential(*layers)

    def forward(self, features: Tensor) -> Tensor:
        encoded = self.network(features)
        return encoded.mean(dim=2).transpose(1, 2)


def _group_count(channels: int) -> int:
    return next(group for group in range(min(8, channels), 0, -1) if channels % group == 0)


def _validate_inputs(
    main: Tensor, bass: Tensor, mask: Tensor, config: CrnnConfig
) -> None:
    if main.ndim != 4 or bass.ndim != 4:
        raise ValueError("CRNN features must have batch, channel, frequency and time axes")
    if (
        main.shape[0] != bass.shape[0]
        or main.shape[-1] != bass.shape[-1]
        or main.shape[1] != config.input_channels
        or bass.shape[1] != config.input_channels
    ):
        raise ValueError("CRNN main and bass feature shapes are incompatible")
    if main.shape[2] < 2 ** len(config.main_conv_channels) or bass.shape[2] < 2 ** len(
        config.bass_conv_channels
    ):
        raise ValueError("CRNN feature frequency axis is too short")
    if mask.dtype != torch.bool or mask.shape != (main.shape[0], main.shape[-1]):
        raise ValueError("CRNN mask must be boolean and time-aligned")
    if torch.any(mask.sum(dim=1) == 0):
        raise ValueError("CRNN every sequence must contain a valid frame")
    after_padding = (~mask).cumsum(dim=1) > 0
    if torch.any(after_padding & mask):
        raise ValueError("CRNN valid mask must be prefix-contiguous")
    if not torch.is_floating_point(main) or not torch.is_floating_point(bass):
        raise ValueError("CRNN features must be floating point")
    if not torch.isfinite(main).all() or not torch.isfinite(bass).all():
        raise ValueError("CRNN features must be finite")
