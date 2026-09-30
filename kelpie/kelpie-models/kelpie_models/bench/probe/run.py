# copied from crucible/verification/engines/probe/run.py @ dfb735f9a8d9
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import trio

logger = logging.getLogger("crucible.verification.engines.probe.run")


def substitute_probe_port(command: list[str], port: int) -> list[str]:
    return [arg.replace("{PROBE_PORT}", str(port)) for arg in command]


async def run_with_probe(
    *,
    target_url: str,
    command: list[str],
    trace_path: Path,
    env: dict[str, str] | None = None,
    proxy_port: int = 0,
    upstream_timeout_s: float | None = None,
) -> dict[str, Any]:
    from kelpie_models.bench.probe.proxy import ProbeProxy

    proxy = ProbeProxy(
        target=target_url,
        output=trace_path,
        upstream_timeout_s=upstream_timeout_s,
    )
    app = proxy.starlette()
    actual_port = proxy_port or _pick_free_port()
    config = _hypercorn_config(actual_port)

    logger.info(
        "probe.proxy_started",
        extra={"port": actual_port, "target": target_url},
    )

    resolved_cmd = substitute_probe_port(command, actual_port)
    subprocess_env = {**os.environ, **(env or {})}

    send_shutdown, recv_shutdown = trio.open_memory_channel[None](0)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(_serve, app, config, recv_shutdown)
        await trio.sleep(0.1)

        t0 = time.monotonic()
        try:
            result = await trio.run_process(
                resolved_cmd,
                capture_stdout=True,
                capture_stderr=True,
                env=subprocess_env,
                check=False,
            )
            elapsed = round(time.monotonic() - t0, 2)
            return {
                "trace": str(trace_path),
                "elapsed_s": elapsed,
                "returncode": result.returncode,
                "stdout": result.stdout.decode(
                    "utf-8", errors="replace",
                ),
                "stderr": result.stderr.decode(
                    "utf-8", errors="replace",
                ),
            }
        finally:
            await send_shutdown.send(None)


def _hypercorn_config(port: int) -> Any:
    from hypercorn.config import Config

    config = Config()
    config.bind = [f"127.0.0.1:{port}"]
    config.loglevel = "WARNING"
    return config


async def shutdown_trigger(recv_shutdown: trio.MemoryReceiveChannel[None]) -> bool:
    async for _ in recv_shutdown:
        return True
    return True


async def _serve(
    app: Any, config: Any, recv_shutdown: trio.MemoryReceiveChannel[None],
) -> Any:
    from hypercorn.trio import serve

    async def trigger() -> None:
        await shutdown_trigger(recv_shutdown)

    return await serve(app, config, shutdown_trigger=trigger)


def _pick_free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
