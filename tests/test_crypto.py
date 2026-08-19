"""Tests for the LAMAX wire encryption.

The expected values below were produced by the original compiled ``AesUtil``
class from the LAMAX Connect APK, so they pin this implementation to the real
app's behaviour rather than just to itself.
"""

from __future__ import annotations

import pytest

from custom_components.lamax_connect.lamax.crypto import decrypt, encrypt

# (wire envelope produced by the Android app, expected plaintext)
JAVA_VECTORS = [
    (
        "3c3c5MXr87WCjx2xWEcxN394cee87a3244137b81d6e3c2bebf4eea49b3fe1a844e2fdbb"
        "3d8cdb483bdef452ce692a745deb24bd2a7c2f2f",
        "hello world",
    ),
    (
        "3c3c4qTPXK7Huxxfx1Dlxa937ebd7efc0dd8bd19b1f2a538aa7bba3306d3f9868f933de"
        "fb529d0f6c025ad229f572e950e743779a1b27efedbe4cd12594fecd6d16adb213afefe"
        "9c9f35cf590f6f545703efd9a1c249f8c53719593ee1cd07c8a6961c726fd263e807411"
        "20fc3045426f97f16fb12a3e3602b66c1c6e2f2f",
        '{"imei":"869123456789012","phone":"+420123456789","lat":"49.1234","lng":"14.5678"}',
    ),
]


@pytest.mark.parametrize(("wire", "expected"), JAVA_VECTORS)
def test_decrypt_matches_android_app(wire: str, expected: str) -> None:
    """Envelopes produced by the real app decrypt to the expected plaintext."""
    assert decrypt(wire) == expected


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "a",
        "hello world",
        '{"imei":"869123456789012"}',
        "diakritika: ěščřžýáíé",
        "x" * 5000,
    ],
)
def test_encrypt_decrypt_roundtrip(payload: str) -> None:
    """Anything encrypted can be decrypted back."""
    assert decrypt(encrypt(payload)) == payload


def test_encrypt_uses_random_iv() -> None:
    """The same plaintext produces different envelopes each time."""
    assert encrypt("hello world") != encrypt("hello world")


def test_decrypt_rejects_tampered_ciphertext() -> None:
    """A modified ciphertext fails the HMAC check."""
    wire = encrypt("hello world")
    tampered = f"{wire[:-6]}00{wire[-4:]}"
    assert decrypt(tampered) is None


def test_decrypt_rejects_tampered_hmac() -> None:
    """A modified HMAC is rejected."""
    wire = encrypt("hello world")
    tampered = f"{wire[:21]}{'0' * 64}{wire[85:]}"
    assert decrypt(tampered) is None


@pytest.mark.parametrize(
    "wire",
    [
        "",
        "garbage",
        "3c3c1shorty2f2f",
        "ffff5MXr87WCjx2xWEcxN394cee82f2f",  # bad prefix
        "3c3c0MXr87WCjx2xWEcxN394cee82f2f",  # key index out of range
        "3c3c9MXr87WCjx2xWEcxN394cee82f2f",  # key index out of range
    ],
)
def test_decrypt_rejects_malformed_input(wire: str) -> None:
    """Malformed envelopes return None instead of raising."""
    assert decrypt(wire) is None


def test_decrypt_rejects_non_utf8_plaintext() -> None:
    """A valid envelope whose plaintext is not UTF-8 returns None."""
    from custom_components.lamax_connect.lamax.crypto import (
        _AES_KEYS,
        _HMAC_KEYS,
        _aes_ctr,
        _hmac_hex,
    )

    index, iv = 0, "A" * 16
    ciphertext_hex = _aes_ctr(_AES_KEYS[index].encode(), iv.encode(), b"\xff\xfe").hex()
    mac = _hmac_hex((iv + _HMAC_KEYS[index]).encode(), ciphertext_hex.encode())
    assert decrypt(f"3c3c{index + 1}{iv}{mac}{ciphertext_hex}2f2f") is None
