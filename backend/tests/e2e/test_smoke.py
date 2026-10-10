"""The smallest end-to-end check: the running stack answers and tags responses with a trace id."""

import re

import httpx2

HTTP_OK = 200


async def test_the_api_is_alive_ready_and_traced(api_url: str) -> None:
    async with httpx2.AsyncClient(base_url=api_url, timeout=10) as http:
        health = await http.get("/healthz")
        ready = await http.get("/readyz")
    assert health.status_code == HTTP_OK
    assert ready.status_code == HTTP_OK
    assert ready.json()["checks"]["postgres"]["status"] == "ok"
    assert re.fullmatch(r"[0-9a-f]{32}", health.headers["x-trace-id"])
