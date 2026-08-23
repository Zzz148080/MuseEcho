from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import nn


@dataclass(frozen=True)
class BtcModelConfig:
    feature_size: int
    hidden_size: int
    num_layers: int
    num_heads: int
    total_key_depth: int
    total_value_depth: int
    filter_size: int
    timestep: int
    num_chords: int = 170

    def __post_init__(self) -> None:
        values = (
            self.feature_size,
            self.hidden_size,
            self.num_layers,
            self.num_heads,
            self.total_key_depth,
            self.total_value_depth,
            self.filter_size,
            self.timestep,
            self.num_chords,
        )
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("BTC model dimensions must be positive integers")
        if self.total_key_depth % self.num_heads:
            raise ValueError("BTC key depth must be divisible by the head count")
        if self.total_value_depth % self.num_heads:
            raise ValueError("BTC value depth must be divisible by the head count")

    @classmethod
    def official(cls) -> BtcModelConfig:
        return cls(
            feature_size=144,
            hidden_size=128,
            num_layers=8,
            num_heads=4,
            total_key_depth=128,
            total_value_depth=128,
            filter_size=128,
            timestep=108,
        )

    @classmethod
    def small_test_config(cls) -> BtcModelConfig:
        return cls(
            feature_size=144,
            hidden_size=16,
            num_layers=2,
            num_heads=2,
            total_key_depth=16,
            total_value_depth=16,
            filter_size=32,
            timestep=8,
        )


def _timing_signal(length: int, channels: int) -> torch.Tensor:
    position = torch.arange(length, dtype=torch.float32)
    timescale_count = channels // 2
    log_increment = math.log(10_000.0) / (timescale_count - 1)
    inverse_timescales = torch.exp(
        torch.arange(timescale_count, dtype=torch.float32) * -log_increment
    )
    scaled_time = position[:, None] * inverse_timescales[None, :]
    signal = torch.cat((torch.sin(scaled_time), torch.cos(scaled_time)), dim=1)
    if channels % 2:
        signal = nn.functional.pad(signal, (0, 1))
    return signal.reshape(1, length, channels)


def _bias_mask(max_length: int) -> torch.Tensor:
    mask = torch.full((max_length, max_length), float("-inf"), dtype=torch.float32)
    return torch.triu(mask, diagonal=1).unsqueeze(0).unsqueeze(1)


class _LayerNorm(nn.Module):
    def __init__(self, features: int, eps: float = 1e-6) -> None:
        super().__init__()
        self.gamma = nn.Parameter(torch.ones(features))
        self.beta = nn.Parameter(torch.zeros(features))
        self.eps = eps

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        mean = inputs.mean(-1, keepdim=True)
        std = inputs.std(-1, keepdim=True)
        return self.gamma * (inputs - mean) / (std + self.eps) + self.beta


class _MultiHeadAttention(nn.Module):
    def __init__(
        self,
        input_depth: int,
        total_key_depth: int,
        total_value_depth: int,
        output_depth: int,
        num_heads: int,
        bias_mask: torch.Tensor,
        dropout: float,
    ) -> None:
        super().__init__()
        self.num_heads = num_heads
        self.query_scale = (total_key_depth // num_heads) ** -0.5
        self.bias_mask = bias_mask
        self.query_linear = nn.Linear(input_depth, total_key_depth, bias=False)
        self.key_linear = nn.Linear(input_depth, total_key_depth, bias=False)
        self.value_linear = nn.Linear(input_depth, total_value_depth, bias=False)
        self.output_linear = nn.Linear(total_value_depth, output_depth, bias=False)
        self.dropout = nn.Dropout(dropout)

    def _split_heads(self, value: torch.Tensor) -> torch.Tensor:
        if value.ndim != 3:
            raise ValueError("BTC attention input must have rank three")
        batch, frames, depth = value.shape
        return value.view(batch, frames, self.num_heads, depth // self.num_heads).permute(
            0, 2, 1, 3
        )

    def _merge_heads(self, value: torch.Tensor) -> torch.Tensor:
        if value.ndim != 4:
            raise ValueError("BTC attention heads must have rank four")
        batch, _, frames, depth = value.shape
        return (
            value.permute(0, 2, 1, 3)
            .contiguous()
            .view(batch, frames, depth * self.num_heads)
        )

    def forward(
        self,
        queries: torch.Tensor,
        keys: torch.Tensor,
        values: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        query_heads = self._split_heads(self.query_linear(queries)) * self.query_scale
        key_heads = self._split_heads(self.key_linear(keys))
        value_heads = self._split_heads(self.value_linear(values))
        logits = torch.matmul(query_heads, key_heads.permute(0, 1, 3, 2))
        mask = self.bias_mask[
            :, :, : logits.shape[-2], : logits.shape[-1]
        ].type_as(logits)
        weights = self.dropout(torch.softmax(logits + mask, dim=-1))
        contexts = self._merge_heads(torch.matmul(weights, value_heads))
        return self.output_linear(contexts), weights


class _Conv(nn.Module):
    def __init__(
        self,
        input_size: int,
        output_size: int,
        kernel_size: int,
        pad_type: str,
    ) -> None:
        super().__init__()
        padding = (
            (kernel_size - 1, 0)
            if pad_type == "left"
            else (kernel_size // 2, (kernel_size - 1) // 2)
        )
        self.pad = nn.ConstantPad1d(padding, 0)
        self.conv = nn.Conv1d(input_size, output_size, kernel_size=kernel_size)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        padded = self.pad(inputs.permute(0, 2, 1))
        return self.conv(padded).permute(0, 2, 1)


class _PositionwiseFeedForward(nn.Module):
    def __init__(
        self,
        input_depth: int,
        filter_size: int,
        output_depth: int,
        dropout: float,
    ) -> None:
        super().__init__()
        self.layers = nn.ModuleList(
            (
                _Conv(input_depth, filter_size, kernel_size=3, pad_type="both"),
                _Conv(filter_size, output_depth, kernel_size=3, pad_type="both"),
            )
        )
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(dropout)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        value = inputs
        for layer in self.layers:
            value = self.dropout(self.relu(layer(value)))
        return value


class _SelfAttentionBlock(nn.Module):
    def __init__(
        self,
        hidden_size: int,
        total_key_depth: int,
        total_value_depth: int,
        filter_size: int,
        num_heads: int,
        bias_mask: torch.Tensor,
        *,
        layer_dropout: float,
        attention_dropout: float,
        relu_dropout: float,
    ) -> None:
        super().__init__()
        self.multi_head_attention = _MultiHeadAttention(
            hidden_size,
            total_key_depth,
            total_value_depth,
            hidden_size,
            num_heads,
            bias_mask,
            attention_dropout,
        )
        self.positionwise_convolution = _PositionwiseFeedForward(
            hidden_size,
            filter_size,
            hidden_size,
            relu_dropout,
        )
        self.dropout = nn.Dropout(layer_dropout)
        self.layer_norm_mha = _LayerNorm(hidden_size)
        self.layer_norm_ffn = _LayerNorm(hidden_size)

    def forward(self, inputs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        normalized = self.layer_norm_mha(inputs)
        attended, weights = self.multi_head_attention(
            normalized, normalized, normalized
        )
        residual = self.dropout(inputs + attended)
        normalized = self.layer_norm_ffn(residual)
        filtered = self.positionwise_convolution(normalized)
        return self.dropout(residual + filtered), weights


class _BidirectionalSelfAttention(nn.Module):
    def __init__(
        self,
        hidden_size: int,
        total_key_depth: int,
        total_value_depth: int,
        filter_size: int,
        num_heads: int,
        max_length: int,
        *,
        layer_dropout: float,
        attention_dropout: float,
        relu_dropout: float,
    ) -> None:
        super().__init__()
        forward_mask = _bias_mask(max_length)
        backward_mask = forward_mask.transpose(2, 3)
        block_arguments = (
            hidden_size,
            total_key_depth,
            total_value_depth,
            filter_size,
            num_heads,
        )
        block_keywords = {
            "layer_dropout": layer_dropout,
            "attention_dropout": attention_dropout,
            "relu_dropout": relu_dropout,
        }
        self.attn_block = _SelfAttentionBlock(
            *block_arguments, forward_mask, **block_keywords
        )
        self.backward_attn_block = _SelfAttentionBlock(
            *block_arguments, backward_mask, **block_keywords
        )
        self.linear = nn.Linear(hidden_size * 2, hidden_size)

    def forward(
        self,
        inputs: tuple[torch.Tensor, list[torch.Tensor]],
    ) -> tuple[torch.Tensor, list[torch.Tensor]]:
        value, weights_list = inputs
        forward_value, forward_weights = self.attn_block(value)
        backward_value, backward_weights = self.backward_attn_block(value)
        output = self.linear(torch.cat((forward_value, backward_value), dim=2))
        return output, [*weights_list, forward_weights, backward_weights]


class _BidirectionalSelfAttentionLayers(nn.Module):
    def __init__(self, config: BtcModelConfig) -> None:
        super().__init__()
        self.timing_signal = _timing_signal(config.timestep, config.hidden_size)
        layer_arguments = (
            config.hidden_size,
            config.total_key_depth,
            config.total_value_depth,
            config.filter_size,
            config.num_heads,
            config.timestep,
        )
        layer_keywords = {
            "layer_dropout": 0.2,
            "attention_dropout": 0.2,
            "relu_dropout": 0.2,
        }
        self.embedding_proj = nn.Linear(
            config.feature_size, config.hidden_size, bias=False
        )
        self.self_attn_layers = nn.Sequential(
            *(
                _BidirectionalSelfAttention(*layer_arguments, **layer_keywords)
                for _ in range(config.num_layers)
            )
        )
        self.layer_norm = _LayerNorm(config.hidden_size)
        self.input_dropout = nn.Dropout(0.2)

    def forward(
        self, inputs: torch.Tensor
    ) -> tuple[torch.Tensor, list[torch.Tensor]]:
        value = self.embedding_proj(self.input_dropout(inputs))
        value = value + self.timing_signal[:, : inputs.shape[1], :].type_as(value)
        encoded, weights = self.self_attn_layers((value, []))
        return self.layer_norm(encoded), weights


class _SoftmaxOutputLayer(nn.Module):
    def __init__(self, hidden_size: int, output_size: int) -> None:
        super().__init__()
        self.output_size = output_size
        self.output_projection = nn.Linear(hidden_size, output_size)
        self.lstm = nn.LSTM(
            input_size=hidden_size,
            hidden_size=hidden_size // 2,
            batch_first=True,
            bidirectional=True,
        )
        self.hidden_size = hidden_size

    def forward(self, hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        logits = self.output_projection(hidden)
        return logits, torch.softmax(logits, dim=-1)


class BtcModel(nn.Module):
    def __init__(self, config: BtcModelConfig) -> None:
        super().__init__()
        self.config = config
        self.timestep = config.timestep
        self.self_attn_layers = _BidirectionalSelfAttentionLayers(config)
        self.output_layer = _SoftmaxOutputLayer(config.hidden_size, config.num_chords)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        if features.ndim != 3 or features.shape[-1] != self.config.feature_size:
            raise ValueError("BTC feature tensor shape is invalid")
        if features.shape[1] > self.config.timestep:
            raise ValueError("BTC feature tensor exceeds the configured timestep")
        encoded, _ = self.self_attn_layers(features)
        logits, _ = self.output_layer(encoded)
        return logits
