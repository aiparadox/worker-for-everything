# FEAT-20261010-1319: GitHub Actions workflow

Status: **approved by the user on 2026-10-10** (both questions answered yes; one small change at implementation: the stack job starts only the api service of the development stack, not the frontend, which the frontend job builds anyway). Working branch: `feat-20261010-1319-github-actions`, from `master`. Depends on: `FEAT-20261010-1207` (merged). Found while writing the spec for `FEAT-20261010-1207`: `ARCHITECTURE.md` section 17 puts CI in Phase 0 and D45 chose GitHub Actions, but no task built it.

## 1. What this builds and why

One workflow file that runs, on every push to `master` and on every pull request, the same checks you run by hand (README "Commands"): lint, format, types, the fast tests, the docs check, the Docker-based tests and the frontend build. A failing check then shows up before a merge, not after.

## 2. Verified facts and what is not verified

| Fact | Source |
|---|---|
| Every command the workflow runs works on this machine: `uv sync --frozen`, ruff, mypy, pytest at each level, `docker compose` with the `test` profile, `npm ci`, `npm run lint`, `npm run build` | run during Phase 0 |
| Current versions of the actions: `actions/checkout` v7.0.1, `astral-sh/setup-uv` v10.3.0, `actions/setup-node` v7.1.0 | GitHub API, 2026-10-10 |
| GitHub's `ubuntu-latest` runners have Docker and Docker Compose | GitHub documentation, from memory; **not re-checked today** |
| **Not verifiable from here:** a real run. The workflow only runs after you push it to GitHub, and this session cannot reach GitHub. I can check the file's syntax and logic with `actionlint` (run as a Docker container, nothing installed), and run each step's commands locally, but not the run itself | – |

## 3. Proposal

File: `.github/workflows/ci.yml`. Triggers: `push` to `master`, `pull_request`, and `workflow_dispatch` (a manual "Run workflow" button, added after the first push produced no run). Permissions: `contents: read` only. A `concurrency` group cancels an older run of the same branch when a newer push arrives.

Three jobs run in parallel:

| Job | Steps |
|---|---|
| `backend-checks` | checkout; set up uv 0.13.0 (the version we use) with its cache; `uv sync --frozen` in `backend/`; `uv run ruff check`; `uv run ruff format --check`; `uv run mypy`; `uv run pytest tests/unit tests/contract` (this includes the API docs check) |
| `backend-stack-tests` | checkout; set up uv; `uv sync --frozen`; copy `.env.example` to `.env` and `.env.test.example` to `.env.test`; `docker compose --profile test up -d --wait postgres-test rabbitmq-test valkey-test storage-test`; `docker compose up -d --wait` (the development stack, for the end-to-end smoke test); `uv run pytest tests/integration tests/e2e`; on failure print `docker compose logs`; always `docker compose down -v` |
| `frontend` | checkout; set up Node 22 with the npm cache; `npm ci`; `npm run lint`; `npm run build` in `frontend/` |

The fake values in the `.example` files are used as they are: they are development values with no meaning outside the runner (D43).

**Security choices:** actions are pinned by **major version tag** (for example `actions/checkout@v7`), the usual compromise. Pinning to a full commit hash is stricter and protects against a moved tag; it is not done now because nothing in this project is deployed yet (D43), and it can be added with a dependency-update bot later. No secrets are used, so no secret can leak.

## 4. Tests and checks

- `actionlint` (Docker image `rhysd/actionlint`) passes on the file.
- Each job's commands are run locally in the same order and pass.
- The YAML parses and each job has the steps listed above (a small unit test reads the file and checks the job names and that every `run:` command that mentions a test level uses a path that exists). This keeps the workflow from drifting from the README commands.
- The first real run happens when you push; if it fails there, the cause is fixed in a follow-up commit and recorded.

## 5. Check for the same problem elsewhere

Lateral: the README commands, the workflow and the test levels now describe the same steps in three places; the small test above ties the workflow to the paths that exist. Causal depth: CI can fail for the code being wrong or for the environment being different (Linux against this Windows machine: line endings are handled by `.gitattributes`; localhost slowness does not apply). Both are separate, and a failure message should make clear which.

## 6. Out of scope

Deployment, image publishing, caching Docker layers, dependency-update bot, coverage upload, running on a schedule. The frontend has no tests yet beyond lint and build (`FEAT-1222`).

## 7. Questions for you

1. Approve the three jobs and the triggers (push to `master` and pull requests)?
2. Approve tag pinning (major version) for now?
