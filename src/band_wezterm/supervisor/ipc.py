"""Authenticated local IPC transport, portable across supported hosts."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

TCP_SCHEME = "tcp"
LOOPBACK_HOST = "127.0.0.1"


def new_endpoint(directory: Path, name: str) -> str:
    """Return an unbound private endpoint; TCP obtains its port at bind time."""
    if os.name == "nt":
        return f"{TCP_SCHEME}://{LOOPBACK_HOST}:0"
    return str(directory / name)


def is_tcp(endpoint: str) -> bool:
    return urlparse(endpoint).scheme == TCP_SCHEME


async def start_server(
    callback: Callable[[asyncio.StreamReader, asyncio.StreamWriter], object], endpoint: str
) -> tuple[asyncio.Server, str]:
    if not is_tcp(endpoint):
        path = Path(endpoint)
        await asyncio.to_thread(path.unlink, missing_ok=True)
        server = await asyncio.start_unix_server(callback, path=str(path))
        return server, endpoint
    parsed = urlparse(endpoint)
    server = await asyncio.start_server(callback, parsed.hostname, parsed.port)
    port = server.sockets[0].getsockname()[1]
    return server, f"{TCP_SCHEME}://{LOOPBACK_HOST}:{port}"


async def open_connection(endpoint: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    if not is_tcp(endpoint):
        return await asyncio.open_unix_connection(endpoint)
    parsed = urlparse(endpoint)
    return await asyncio.open_connection(parsed.hostname, parsed.port)


async def remove_endpoint(endpoint: str) -> None:
    if not is_tcp(endpoint):
        await asyncio.to_thread(Path(endpoint).unlink, missing_ok=True)
