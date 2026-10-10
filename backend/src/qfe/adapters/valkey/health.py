"""Readiness check for Valkey (used through the ``redis`` client, D42)."""

from redis.asyncio import Redis

from qfe.observability.health import ReadinessCheck


def valkey_check(client: Redis) -> ReadinessCheck:
    """Not critical: most rate limits fail open, so a Valkey outage degrades the API but does not
    stop it (docs/ARCHITECTURE.md section 9)."""

    async def check() -> None:
        await client.ping()

    return ReadinessCheck(name="valkey", check=check, critical=False)
