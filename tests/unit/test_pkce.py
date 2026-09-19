"""Unit tests for PKCE helpers."""

from __future__ import annotations

import base64
import hashlib
import re

from band_wezterm.auth.pkce import base64url, code_challenge, code_verifier


def test_base64url_has_no_padding() -> None:
    encoded = base64url(b"\xff\xfe\xfd")
    assert "=" not in encoded
    assert re.fullmatch(r"[A-Za-z0-9_-]+", encoded)


def test_code_challenge_is_s256_of_verifier() -> None:
    verifier = code_verifier()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert code_challenge(verifier) == expected


def test_code_verifier_is_urlsafe() -> None:
    verifier = code_verifier()
    assert "=" not in verifier
    assert re.fullmatch(r"[A-Za-z0-9_-]+", verifier)
