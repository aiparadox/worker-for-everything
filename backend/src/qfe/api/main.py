"""Entry point of the ``api`` process: reads settings, wires adapters, builds the app.

Run with: ``uvicorn qfe.api.main:create_app_from_environment --factory --no-access-log``
(the access log line comes from our own middleware, with the trace id).
"""

from fastapi import FastAPI
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from qfe.adapters.postgres.health import postgres_check
from qfe.adapters.valkey.health import valkey_check
from qfe.api.app import create_app
from qfe.config import ApiSettings, load_or_exit
from qfe.observability import configure_logging, get_logger, setup_tracing


def create_app_from_environment() -> FastAPI:
    settings = load_or_exit(ApiSettings)
    configure_logging(settings.service_name)
    setup_tracing(settings.service_name, settings.telemetry, settings.otlp_endpoint)

    engine = create_async_engine(settings.database_url.get_secret_value())
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    AsyncPGInstrumentor().instrument()  # type: ignore[no-untyped-call]
    valkey = Redis.from_url(settings.valkey_url.get_secret_value())

    async def close_connections() -> None:
        await valkey.aclose()
        await engine.dispose()

    get_logger(__name__).info("api starting", service=settings.service_name)
    return create_app(
        readiness_checks=[postgres_check(engine), valkey_check(valkey)],
        shutdown_callbacks=[close_connections],
    )
