"""Authenticated encryption for provider token bundles and OAuth verifiers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class TokenDecryptionError(ValueError):
    pass


class TokenCipher:
    def __init__(self, keys: Sequence[str]) -> None:
        self._cipher = MultiFernet([Fernet(key.encode()) for key in keys])

    def encrypt(self, payload: Mapping[str, Any]) -> str:
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return self._cipher.encrypt(raw).decode()

    def decrypt(self, ciphertext: str) -> dict[str, Any]:
        try:
            result = json.loads(self._cipher.decrypt(ciphertext.encode()).decode())
        except (InvalidToken, UnicodeError, json.JSONDecodeError) as exc:
            raise TokenDecryptionError("stored provider credentials cannot be decrypted") from exc
        if not isinstance(result, dict):
            raise TokenDecryptionError("stored provider credentials have an invalid format")
        return result

    def rotate(self, ciphertext: str) -> str:
        try:
            return self._cipher.rotate(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise TokenDecryptionError("stored provider credentials cannot be rotated") from exc
