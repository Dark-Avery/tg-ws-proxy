from __future__ import annotations

import os
from typing import Protocol


class AesCtrTransform(Protocol):
    def update(self, data: bytes) -> bytes:
        ...

    def finalize(self) -> bytes:
        ...


def _create_cryptography_transform(key: bytes,
                                   iv: bytes) -> AesCtrTransform:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    cipher = Cipher(algorithms.AES(key), modes.CTR(iv))
    return cipher.encryptor()


def create_aes_ctr_transform(key: bytes, iv: bytes,
                             backend: str | None = None) -> AesCtrTransform:
    """
    Create a stateful AES-CTR transform.

    The backend name is configurable so Android can supply an alternative
    implementation later without touching proxy logic.
    """
    selected = backend or os.environ.get(
        'TG_WS_PROXY_CRYPTO_BACKEND', 'cryptography')

    if selected == 'cryptography':
        return _create_cryptography_transform(key, iv)

    raise ValueError(f"Unsupported AES-CTR backend: {selected}")
