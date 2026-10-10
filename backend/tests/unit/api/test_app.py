"""The operational endpoints, the trace header, the metrics and the access log."""

import json
import re
from collections.abc import AsyncIterator

import httpx2
import pytest
from fastapi import FastAPI

from qfe.api.app import create_app
from qfe.observability import ReadinessCheck, clear_log_context, configure_logging

HEX32 = re.compile(r"^[0-9a-f]{32}$")
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACEPARENT = f"00-{TRACE_ID}-00f067aa0ba902b7-01"
HTTP_OK = 200
HTTP_UNAVAILABLE = 503
HTTP_SERVER_ERROR = 500


async def ok() -> None:
    return None


async def down() -> None:
    raise ConnectionError("nope")


def make_app(*, postgres_ok: bool = True, valkey_ok: bool = True) -> FastAPI:
    return create_app(
        [
            ReadinessCheck("postgres", ok if postgres_ok else down, critical=True),
            ReadinessCheck("valkey", ok if valkey_ok else down, critical=False),
        ]
    )


@pytest.fixture
async def client() -> AsyncIterator[httpx2.AsyncClient]:
    app = make_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("internal detail that must not reach the client")

    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture(autouse=True)
def json_logging(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("api-test")
    clear_log_context()
    capsys.readouterr()


async def test_healthz_is_ok_and_carries_a_trace_id(client: httpx2.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == HTTP_OK
    assert response.json() == {"status": "ok"}
    assert HEX32.match(response.headers["x-trace-id"])


async def test_a_valid_traceparent_is_continued(client: httpx2.AsyncClient) -> None:
    response = await client.get("/healthz", headers={"traceparent": TRACEPARENT})
    assert response.headers["x-trace-id"] == TRACE_ID


@pytest.mark.parametrize("bad", ["garbage", "00-xyz-00f067aa0ba902b7-01", ""])
async def test_a_malformed_traceparent_starts_a_new_trace_and_is_not_an_error(
    client: httpx2.AsyncClient, bad: str
) -> None:
    response = await client.get("/healthz", headers={"traceparent": bad})
    assert response.status_code == HTTP_OK
    assert HEX32.match(response.headers["x-trace-id"])
    assert response.headers["x-trace-id"] != TRACE_ID


@pytest.mark.parametrize(
    ("postgres_ok", "valkey_ok", "status", "degraded"),
    [
        (True, True, HTTP_OK, []),
        (False, True, HTTP_UNAVAILABLE, []),
        (True, False, HTTP_OK, ["valkey"]),
    ],
)
async def test_readyz(postgres_ok: bool, valkey_ok: bool, status: int, degraded: list[str]) -> None:
    transport = httpx2.ASGITransport(app=make_app(postgres_ok=postgres_ok, valkey_ok=valkey_ok))
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/readyz")
    assert response.status_code == status
    assert response.json()["degraded"] == degraded
    assert "x-trace-id" in response.headers


async def test_metrics_count_requests_by_route_template(client: httpx2.AsyncClient) -> None:
    await client.get("/healthz")
    await client.get("/does-not-exist/12345")
    text = (await client.get("/metrics")).text
    assert 'qfe_http_requests_total{method="GET",route="/healthz",status_class="2xx"}' in text
    assert 'route="unmatched",status_class="4xx"' in text
    assert "12345" not in text  # raw paths never become labels
    assert "qfe_http_request_duration_seconds_bucket" in text


async def test_an_unhandled_error_gives_a_clean_500_with_a_trace_id(
    client: httpx2.AsyncClient,
) -> None:
    response = await client.get("/boom")
    assert response.status_code == HTTP_SERVER_ERROR
    assert response.json()["error"]["code"] == "internal_error"
    assert "internal detail" not in response.text
    assert HEX32.match(response.headers["x-trace-id"])


async def test_the_access_log_line_has_the_same_trace_id_as_the_response(
    client: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    response = await client.get("/healthz", headers={"traceparent": TRACEPARENT})
    records = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    (access,) = [r for r in records if r["event"] == "request"]
    assert access["trace_id"] == response.headers["x-trace-id"] == TRACE_ID
    assert (access["method"], access["route"], access["status"]) == ("GET", "/healthz", HTTP_OK)


async def test_shutdown_callbacks_run_when_the_app_stops() -> None:
    stopped: list[str] = []

    async def close() -> None:
        stopped.append("closed")

    app = create_app([], shutdown_callbacks=[close])
    async with app.router.lifespan_context(app):
        assert stopped == []
    assert stopped == ["closed"]
