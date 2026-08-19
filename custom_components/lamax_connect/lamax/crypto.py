"""LAMAX Connect wire encryption.

Reverse engineered from ``com.ztc.lamax.utils.AesUtil`` in the LAMAX Connect
Android app v1.0.17, and cross-validated against the original compiled Java
class in both directions.

Wire format::

    "3c3c" + key_index(1 digit) + iv(16 ascii chars)
           + hmac_sha256(iv + hmac_key[i], ciphertext_hex)
           + ciphertext_hex + "2f2f"

AES-256-CTR with a random 16-byte alphanumeric IV used directly as the initial
counter block. The key is chosen from a fixed 5-entry table by an index derived
from the plaintext length. Integrity is HMAC-SHA256 over the ciphertext *hex
string*, keyed by IV + a second fixed per-index key.

All keys are hardcoded in the APK, so this layer provides no real
confidentiality - but the backend requires it, so any client must implement it.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Index 0..4 <-> AesUtil.f13227a / f13228b (HMAC salt / AES key tables).
_HMAC_KEYS = (
    "!mXnPGMeO8Xi@GkT",
    "uJfOmj7O3XHSRj5b",
    "Rt3Bn!BYDSSkyNzV",
    "rVM92NHRu!j*Qb^^",
    "@rtUcxScGPK&LdVg",
)
_AES_KEYS = (
    "su6lmuo9a6NgaFUMANWRz0OvgCl3JL0t",
    "eJRoYBlux@$9ZPbmHU#drC%sLZw^a9Sl",
    "y2mKusCvDTxAe$UJcFJOM7C8el$L6o^R",
    "nGZkr88fdLYSfZYxg4PlkL^*HpGIHKSX",
    "e&tJRUol6py7aIZmiV#Zi$uij2sU9DiL",
)

_ALPHABET = string.ascii_letters + string.digits
_ENVELOPE_PREFIX = "3c3c"
_ENVELOPE_SUFFIX = "2f2f"


def _random_iv(length: int = 16) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def _hmac_hex(key: bytes, msg: bytes) -> str:
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _aes_ctr(key: bytes, iv16: bytes, data: bytes) -> bytes:
    """Encrypt or decrypt - CTR mode is symmetric."""
    cipher = Cipher(algorithms.AES(key), modes.CTR(iv16)).encryptor()
    return cipher.update(data) + cipher.finalize()


def _key_index(plaintext: str) -> int:
    """Mirror AesUtil's index selection. Returns 0-4."""
    length = len(plaintext) % 6
    if length > 5:  # pragma: no cover - unreachable, mirrors the original AesUtil
        length = len(plaintext) % 3
    if length == 0:
        length = len(plaintext) % 2
    return (length if length != 0 else 5) - 1


def encrypt(plaintext: str) -> str:
    """Wrap a plaintext payload in the LAMAX wire envelope."""
    index = _key_index(plaintext)
    iv = _random_iv()
    ciphertext_hex = _aes_ctr(_AES_KEYS[index].encode(), iv.encode(), plaintext.encode()).hex()
    mac = _hmac_hex((iv + _HMAC_KEYS[index]).encode(), ciphertext_hex.encode())
    return f"{_ENVELOPE_PREFIX}{index + 1}{iv}{mac}{ciphertext_hex}{_ENVELOPE_SUFFIX}"


def decrypt(wire: str) -> str | None:
    """Unwrap a LAMAX wire envelope. Returns None if it is malformed or forged."""
    if not wire.startswith(_ENVELOPE_PREFIX) or not wire.endswith(_ENVELOPE_SUFFIX):
        return None
    try:
        index = int(wire[4:5]) - 1
        if not 0 <= index < len(_AES_KEYS):
            return None
        iv = wire[5:21]
        mac = wire[21:85]
        ciphertext_hex = wire[85 : -len(_ENVELOPE_SUFFIX)]
        expected = _hmac_hex((iv + _HMAC_KEYS[index]).encode(), ciphertext_hex.encode())
        if not hmac.compare_digest(expected, mac):
            return None
        return _aes_ctr(
            _AES_KEYS[index].encode(), iv.encode(), bytes.fromhex(ciphertext_hex)
        ).decode()
    except (ValueError, UnicodeDecodeError):
        return None
