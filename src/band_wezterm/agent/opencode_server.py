"""Control-owned OpenCode server lifecycle."""

from __future__ import annotations

import asyncio
import re
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

import httpx

from band_wezterm.diagnostics import log_event

_HOST: Final = "127.0.0.1"
_STARTUP_TIMEOUT_SECONDS: Final = 10.0
_SHUTDOWN_TIMEOUT_SECONDS: Final = 3.0
_HEALTH_RETRY_SECONDS: Final = 0.1
_HEALTH_PATH: Final = "/global/health"
_OUTPUT_LIMIT: Final = 8
_OUTPUT_LINE_LIMIT: Final = 300
_LISTENING_PATTERN: Final = re.compile(
    r"opencode server listening on (?P<url>http://[^\s]+)"
)


class OpenCodeServerError(RuntimeError):
    """Raised when the shared OpenCode backend cannot become ready."""


@dataclass(frozen=True)
class OpenCodeEndpoint:
    """Validated loopback endpoint announced by OpenCode."""

    url: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", _normalize_endpoint_url(self.url))

    @classmethod
    def parse(cls, value: str) -> OpenCodeEndpoint:
        return cls(value)


class OpenCodeServerManager:
    """Own one shared ``opencode serve`` child for the Control lifetime."""

    def __init__(self, *, startup_timeout: float = _STARTUP_TIMEOUT_SECONDS) -> None:
        self._startup_timeout = startup_timeout
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._endpoint: OpenCodeEndpoint | None = None

    async def ensure(self) -> OpenCodeEndpoint:
        """Return the healthy shared endpoint, starting it exactly once."""
        async with self._lock:
            if await self._is_healthy():
                assert self._endpoint is not None
                return self._endpoint
            await self._close_locked()
            return await self._start_locked()

    async def close(self) -> None:
        """Stop the shared backend and release its output reader."""
        async with self._lock:
            await self._close_locked()

    async def _start_locked(self) -> OpenCodeEndpoint:
        output: deque[str] = deque(maxlen=_OUTPUT_LIMIT)
        loop = asyncio.get_running_loop()
        announced: asyncio.Future[OpenCodeEndpoint] = loop.create_future()
        try:
            self._process = await asyncio.create_subprocess_exec(
                "opencode",
                "serve",
                "--hostname",
                _HOST,
                "--port",
                "0",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert self._process.stdout is not None
            self._reader_task = asyncio.create_task(
                self._read_output(self._process.stdout, announced, output)
            )
            async with asyncio.timeout(self._startup_timeout):
                endpoint = await announced
                await self._wait_until_healthy(endpoint)
        except TimeoutError as error:
            detail = _startup_detail(output)
            await self._close_locked()
            raise OpenCodeServerError(
                f"OpenCode server did not become ready within "
                f"{self._startup_timeout:g} seconds{detail}."
            ) from error
        except (OSError, OpenCodeServerError):
            await self._close_locked()
            raise
        except asyncio.CancelledError:
            await self._close_locked()
            raise
        self._endpoint = endpoint
        log_event("opencode server started", endpoint=endpoint.url)
        return endpoint

    async def _read_output(
        self,
        stream: asyncio.StreamReader,
        announced: asyncio.Future[OpenCodeEndpoint],
        output: deque[str],
    ) -> None:
        while line := await stream.readline():
            text = line.decode(errors="replace").strip()
            if not announced.done():
                output.append(text[:_OUTPUT_LINE_LIMIT])
                match = _LISTENING_PATTERN.search(text)
                if match is not None:
                    try:
                        announced.set_result(OpenCodeEndpoint.parse(match["url"]))
                    except OpenCodeServerError as error:
                        announced.set_exception(error)
        if not announced.done():
            return_code = (
                self._process.returncode if self._process is not None else None
            )
            detail = _startup_detail(output)
            announced.set_exception(
                OpenCodeServerError(
                    f"OpenCode server exited before announcing its address "
                    f"(code {return_code}){detail}."
                )
            )

    async def _wait_until_healthy(self, endpoint: OpenCodeEndpoint) -> None:
        while not await _health_check(endpoint):
            if self._process is None or self._process.returncode is not None:
                raise OpenCodeServerError(
                    "OpenCode server exited before its health check succeeded."
                )
            await asyncio.sleep(_HEALTH_RETRY_SECONDS)

    async def _is_healthy(self) -> bool:
        return (
            self._process is not None
            and self._process.returncode is None
            and self._endpoint is not None
            and await _health_check(self._endpoint)
        )

    async def _close_locked(self) -> None:
        process = self._process
        reader_task = self._reader_task
        self._process = None
        self._reader_task = None
        self._endpoint = None
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                async with asyncio.timeout(_SHUTDOWN_TIMEOUT_SECONDS):
                    await process.wait()
            except TimeoutError:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        if reader_task is not None:
            if not reader_task.done():
                reader_task.cancel()
            await asyncio.gather(reader_task, return_exceptions=True)
        if process is not None:
            log_event("opencode server stopped", return_code=process.returncode)


async def _health_check(endpoint: OpenCodeEndpoint) -> bool:
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_RETRY_SECONDS) as client:
            response = await client.get(f"{endpoint.url}{_HEALTH_PATH}")
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return False
    return (
        response.is_success
        and isinstance(payload, dict)
        and payload.get("healthy") is True
    )


def _startup_detail(output: deque[str]) -> str:
    visible = [line for line in output if line]
    return f": {' | '.join(visible)}" if visible else ""


def _normalize_endpoint_url(value: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise OpenCodeServerError(
            "OpenCode announced an invalid server port."
        ) from error
    if (
        parsed.scheme != "http"
        or parsed.hostname != _HOST
        or port is None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise OpenCodeServerError(
            f"OpenCode announced an unexpected server address: {value!r}."
        )
    return f"http://{_HOST}:{port}"
