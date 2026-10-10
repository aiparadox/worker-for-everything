"""/readyz against the real test PostgreSQL and Valkey
(docs/specs/FEAT-20261010-1205-observability-skeleton.md, section 4)."""

import socket
from collections.abc import AsyncIterator, Iterator
from urllib.parse import urlsplit

import httpx2
import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from qfe.adapters.postgres.health import postgres_check
from qfe.adapters.valkey.health import valkey_check
from qfe.api.app import create_app
from tests.support.compose import compose, wait_until_healthy
from tests.support.environment import load_test_environment

HTTP_OK = 200
HTTP_UNAVAILABLE = 503
START_HINT = (
    "The test services are not reachable. Start them with: docker compose --profile test up -d "
    "--wait postgres-test rabbitmq-test valkey-test storage-test"
)


def _require_reachable(url: str) -> None:
    parts = urlsplit(url)
    try:
        socket.create_connection(
            (parts.hostname or "127.0.0.1", parts.port or 0), timeout=3
        ).close()
    except OSError:
        pytest.fail(START_HINT)


@pytest.fixture(scope="module")
def environment() -> dict[str, str]:
    env = load_test_environment()
    _require_reachable(env["QFE_DATABASE_URL"])
    _require_reachable(env["QFE_VALKEY_URL"])
    return env


@pytest.fixture
async def engine(environment: dict[str, str]) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(environment["QFE_DATABASE_URL"])
    yield engine
    await engine.dispose()


@pytest.fixture
async def valkey(environment: dict[str, str]) -> AsyncIterator[Redis]:
    client = Redis.from_url(environment["QFE_VALKEY_URL"])
    yield client
    await client.aclose()


def client_for(engine: AsyncEngine, valkey: Redis) -> httpx2.AsyncClient:
    app = create_app([postgres_check(engine), valkey_check(valkey)])
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test")


async def test_ready_when_postgres_and_valkey_are_up(engine: AsyncEngine, valkey: Redis) -> None:
    async with client_for(engine, valkey) as http:
        response = await http.get("/readyz")
    assert response.status_code == HTTP_OK
    body = response.json()
    assert body["status"] == "ready"
    assert body["degraded"] == []
    assert body["checks"]["postgres"]["status"] == "ok"
    assert body["checks"]["valkey"]["status"] == "ok"


async def test_wrong_postgres_credentials_make_the_api_not_ready(
    environment: dict[str, str], valkey: Redis
) -> None:
    url = environment["QFE_DATABASE_URL"]
    password = urlsplit(url).password or ""
    bad = create_async_engine(url.replace(password, "wrong-password"))
    try:
        async with client_for(bad, valkey) as http:
            response = await http.get("/readyz")
    finally:
        await bad.dispose()
    assert response.status_code == HTTP_UNAVAILABLE
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["postgres"]["status"] == "down"
    assert password not in response.text
    assert "wrong-password" not in response.text


@pytest.fixture
def valkey_stopped() -> Iterator[None]:
    stopped = compose("stop", "valkey-test")
    assert stopped.returncode == 0, stopped.stderr
    try:
        yield
    finally:
        started = compose("start", "valkey-test")
        assert started.returncode == 0, started.stderr
        wait_until_healthy("valkey-test")


async def test_valkey_down_is_degraded_but_still_ready(
    engine: AsyncEngine, valkey: Redis, valkey_stopped: None
) -> None:
    async with client_for(engine, valkey) as http:
        response = await http.get("/readyz")
    assert response.status_code == HTTP_OK
    body = response.json()
    assert body["degraded"] == ["valkey"]
    assert body["checks"]["postgres"]["status"] == "ok"
    assert body["checks"]["valkey"]["status"] == "down"


async def test_metrics_show_the_requests_made(engine: AsyncEngine, valkey: Redis) -> None:
    async with client_for(engine, valkey) as http:
        await http.get("/readyz")
        text = (await http.get("/metrics")).text
    assert 'qfe_http_requests_total{method="GET",route="/readyz",status_class="2xx"}' in text
