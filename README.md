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

The Docker Compose stack, the database migrations and the integration tests are described here as they are added.
