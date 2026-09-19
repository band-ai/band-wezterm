"""PKCE S256 helpers — algorithm port of userAuth.ts."""

from __future__ import annotations

import base64
import hashlib
import secrets


def base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def random_base64url(nbytes: int = 32) -> str:
    return base64url(secrets.token_bytes(nbytes))


def code_verifier() -> str:
    return random_base64url(32)


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64url(digest)
