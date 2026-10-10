# Queue for everything

A generic queue-based job server: clients submit jobs through an HTTP API, workers run them with handler plugins (document processing, OCR, content generation, scraping, email, data pipelines), and the result is fetched by polling. Everything runs in Docker Compose.

**Status:** Phase 0 (foundation) is in progress. Nothing is runnable yet except the checks below.

## Where things are

| Path | What |
|---|---|
| `backend/` | Python 3.12 project, managed with [uv](https://docs.astral.sh/uv/). Code is in `backend/src/qfe/`, tests in `backend/tests/` |
| `frontend/` | Next.js app (code in `frontend/src/`) |
| `docs/ARCHITECTURE.md`, `docs/DATABASE.md` | The design |
| `docs/specs/` | One spec per task, approved before the task starts |
| `docs/discussion/NOTEPAD.md` | Every decision and why |
| `TODO.md` | The task list |

## Commands

Run from the folder shown. There is no task runner (decision D45); CI will call these directly.

Backend (`backend/`):

```
uv sync                              # create .venv and install the locked packages
uv run pytest tests/unit tests/contract
uv run ruff check
uv run ruff format --check
uv run mypy
```

Frontend (`frontend/`):

```
npm install
npm run lint
npm run build
npm run dev
```

## Docker Compose stack

Needs Docker with Compose. Settings come from `.env`; start from the example (all values are fake, for development only):

```
cp .env.example .env
docker compose up -d --wait                    # postgres, rabbitmq, valkey, storage, frontend
docker compose --profile observability up -d   # adds Grafana, traces, logs and metrics
docker compose down                            # stop; add -v to also delete the data
```

Everything is published on `127.0.0.1` only. Host ports: Postgres 5433, RabbitMQ 5672 (management page 15672), Valkey 6379, storage S3 8333, frontend 3100, Grafana 3001, OTLP 4317 and 4318. They differ from the usual defaults for Postgres (5432) and the frontend (3000) because those are often taken on a development machine; every port can be changed in `.env`.

Separate, empty services for the tests (data in memory, other ports; D48):

```
docker compose --profile test up -d --wait postgres-test rabbitmq-test valkey-test storage-test
```

The application services (migrate, api, relay, worker, maintenance) are added to `compose.yaml` by the tasks that create them. The database migrations and the integration tests are described here as they are added.
