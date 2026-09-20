"""Shared OpenCode server lifecycle."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from band_wezterm.agent.opencode_server import (
    OpenCodeEndpoint,
    OpenCodeServerError,
    OpenCodeServerManager,
)


class FakeProcess:
    def __init__(self, output: bytes) -> None:
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(output)
        self.returncode: int | None = None

    def terminate(self) -> None:
        self.returncode = 0
        self.stdout.feed_eof()

    def kill(self) -> None:
        self.returncode = -9
        self.stdout.feed_eof()

    async def wait(self) -> int:
        return self.returncode or 0


def test_endpoint_accepts_only_explicit_loopback_http() -> None:
    assert OpenCodeEndpoint.parse("http://127.0.0.1:43117").url == (
        "http://127.0.0.1:43117"
    )
    for value in (
        "https://127.0.0.1:43117",
        "http://localhost:43117",
        "http://0.0.0.0:43117",
        "http://127.0.0.1:not-a-port",
        "http://127.0.0.1:43117/path",
    ):
        with pytest.raises(OpenCodeServerError):
            OpenCodeEndpoint.parse(value)


async def test_concurrent_ensure_starts_one_shared_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts: list[tuple[Any, ...]] = []
    process = FakeProcess(
        b"Warning: server is unsecured.\n"
        b"opencode server listening on http://127.0.0.1:43117\n"
    )

    async def create_process(*command: object, **_kwargs: object) -> FakeProcess:
        starts.append(command)
        return process

    async def healthy(_endpoint: OpenCodeEndpoint) -> bool:
        return True

    monkeypatch.setattr(
        "band_wezterm.agent.opencode_server.asyncio.create_subprocess_exec",
        create_process,
    )
    monkeypatch.setattr("band_wezterm.agent.opencode_server._health_check", healthy)
    manager = OpenCodeServerManager()

    first, second = await asyncio.gather(manager.ensure(), manager.ensure())

    assert first == second == OpenCodeEndpoint("http://127.0.0.1:43117")
    assert starts == [("opencode", "serve", "--hostname", "127.0.0.1", "--port", "0")]
    await manager.close()
    assert process.returncode == 0


async def test_ensure_surfaces_early_server_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess(b"configuration failed\n")
    process.stdout.feed_eof()

    async def create_process(*_args: object, **_kwargs: object) -> FakeProcess:
        process.returncode = 2
        return process

    monkeypatch.setattr(
        "band_wezterm.agent.opencode_server.asyncio.create_subprocess_exec",
        create_process,
    )
    manager = OpenCodeServerManager()

    with pytest.raises(OpenCodeServerError, match=r"code 2.*configuration failed"):
        await manager.ensure()
