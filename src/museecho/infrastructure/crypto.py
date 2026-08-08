from __future__ import annotations

import os
import struct
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"MUSEAEAD"
FORMAT_VERSION = 1
NONCE_PREFIX_SIZE = 8
GCM_NONCE_SIZE = 12
GCM_TAG_SIZE = 16
HEADER_STRUCT = struct.Struct(">8sB16sI8s")
HEADER_SIZE = HEADER_STRUCT.size
KEY_WRAP_AAD_PREFIX = b"MuseEcho-DEK-v1"


def build_header(analysis_id: uuid.UUID, chunk_size: int, nonce_prefix: bytes) -> bytes:
    if len(nonce_prefix) != NONCE_PREFIX_SIZE:
        raise ValueError("nonce prefix must be 8 bytes")
    return HEADER_STRUCT.pack(MAGIC, FORMAT_VERSION, analysis_id.bytes, chunk_size, nonce_prefix)


def parse_header(value: bytes) -> tuple[uuid.UUID, int, bytes]:
    if len(value) != HEADER_SIZE:
        raise ValueError("invalid encrypted audio header length")
    magic, version, analysis_bytes, chunk_size, nonce_prefix = HEADER_STRUCT.unpack(value)
    if magic != MAGIC or version != FORMAT_VERSION or chunk_size <= 0:
        raise ValueError("unsupported encrypted audio format")
    return uuid.UUID(bytes=analysis_bytes), chunk_size, nonce_prefix


def derive_nonce(nonce_prefix: bytes, chunk_index: int) -> bytes:
    if len(nonce_prefix) != NONCE_PREFIX_SIZE or not 0 <= chunk_index < 2**32:
        raise ValueError("invalid nonce derivation input")
    return nonce_prefix + chunk_index.to_bytes(4, "big")


def chunk_aad(
    analysis_id: uuid.UUID,
    chunk_size: int,
    chunk_index: int,
    plaintext_length: int,
) -> bytes:
    if not 0 <= chunk_index < 2**32 or not 0 < plaintext_length <= chunk_size:
        raise ValueError("invalid chunk authentication metadata")
    return struct.pack(
        ">B16sIII",
        FORMAT_VERSION,
        analysis_id.bytes,
        chunk_size,
        chunk_index,
        plaintext_length,
    )


def wrap_data_key(kek: bytes, analysis_id: uuid.UUID, data_key: bytes) -> bytes:
    if len(kek) != 32 or len(data_key) != 32:
        raise ValueError("AES-256 keys must be 32 bytes")
    nonce = os.urandom(GCM_NONCE_SIZE)
    wrapped = AESGCM(kek).encrypt(nonce, data_key, KEY_WRAP_AAD_PREFIX + analysis_id.bytes)
    return nonce + wrapped


def unwrap_data_key(kek: bytes, analysis_id: uuid.UUID, wrapped_data_key: bytes) -> bytes:
    if len(kek) != 32 or len(wrapped_data_key) != GCM_NONCE_SIZE + 32 + GCM_TAG_SIZE:
        raise ValueError("invalid wrapped data key")
    nonce = wrapped_data_key[:GCM_NONCE_SIZE]
    wrapped = wrapped_data_key[GCM_NONCE_SIZE:]
    return AESGCM(kek).decrypt(nonce, wrapped, KEY_WRAP_AAD_PREFIX + analysis_id.bytes)


def wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0
