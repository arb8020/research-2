#!/usr/bin/env python3
"""Fire N concurrent /v1/completions at a kelpie-http server (baseline load for step_breakdown)."""

from __future__ import annotations

import asyncio
import sys
import time

import httpx

PROMPTS = [
    "The capital of France is",
    "Once upon a time, in a land far away,",
    "def fibonacci(n):",
    "The theory of relativity states that",
    "In the beginning",
]


async def main(url: str, n: int, max_tokens: int, concurrency: int) -> None:
    sem = asyncio.Semaphore(concurrency)

    async def one(client: httpx.AsyncClient, i: int) -> int:
        body = {"prompt": PROMPTS[i % len(PROMPTS)], "max_tokens": max_tokens, "temperature": 0.8}
        async with sem:
            while True:
                r = await client.post(f"{url}/v1/completions", json=body)
                if r.status_code != 429:  # noqa: PLR2004
                    break
                await asyncio.sleep(0.2)
        r.raise_for_status()
        return r.json()["usage"]["completion_tokens"]

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=600) as client:
        toks = await asyncio.gather(*(one(client, i) for i in range(n)))
    dt = time.perf_counter() - t0
    print(f"{n} requests, {sum(toks)} tokens in {dt:.1f}s = {sum(toks) / dt:.1f} tok/s")


if __name__ == "__main__":
    url, n, max_tokens, conc = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
    asyncio.run(main(url, n, max_tokens, conc))
