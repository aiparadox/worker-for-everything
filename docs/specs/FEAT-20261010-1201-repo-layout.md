# FEAT-20261010-1201: repository layout

Status: **draft for approval**. Working branch: `feat-20261010-1201-repo-layout`, from `master`. Depends on: nothing (the tooling is decided in D45).

## 1. What this builds and why

The empty skeleton every later task fills in: the backend Python project, the frontend Next.js project, the shared repository files and the docs folders. No behaviour yet. Later tasks put code in the folders this one creates, so the names chosen here are hard to change later.

## 2. What I checked (2026-10-10)

| Fact | Result |
|---|---|
| Docker, Compose | Docker 29.5.2, Compose 5.1.3 (works) |
| Node, npm | Node 22.18.0, npm 11.19.1; Next.js 16.4.0 needs Node 20.9 or newer |
| Python on this machine | `python` is 3.13.0a5 (an alpha) and `py` is 3.11.6. **Neither is 3.12.** uv can install and use its own 3.12 without touching these |
| uv | **Not installed** |
| Repository | git on `master`, no `.gitignore`, no `.gitattributes`, `core.autocrlf` is `false` |

Not checked yet: the exact flags of `uv init` and `create-next-app`. They are read from each tool's `--help` as the first step of the work, because Module 8 says to use the generator and not to write from memory.

## 3. Proposal

### 3.1 Install uv (needs your approval, Module 5)

Install uv with its official standalone installer for the current user only. It goes into the user's folder, not system-wide, and is removed by deleting that folder. Python 3.12 is then installed and used by uv for this project only (`.python-version` pins it).

### 3.2 Backend

- Generated with `uv init --package` in `backend/`. Project name `qfe` (the same short name as the `qfe_` key prefix and the `qfe_app` database role).
- **One change from ARCHITECTURE.md section 6, please confirm:** the code folders go under one package, `backend/src/qfe/`, not directly in `backend/src/`. Reason: with `backend/src/domain/` the importable names would be `domain`, `ports`, `config`, `api`. Names that generic collide with other packages and tools. With one package they are `qfe.domain`, `qfe.ports` and so on. It is still `backend/src` as you asked.
- Folders under `backend/src/qfe/`, each an empty package (`__init__.py` only; no generator makes empty packages, so these are hand-written, Module 8): `domain`, `ports`, `adapters/{postgres,rabbitmq,s3,valkey,password_auth}`, `application`, `job_types`, `handlers`, `api`, `worker`, `relay`, `maintenance`, `observability`, `config`.
- Tests: `backend/tests/{unit,integration,contract,e2e}`, each with a placeholder that proves the test runner finds it.
- `backend/migrations/` is created by Alembic's own generator in `FEAT-1204`, not here.
- `backend/pyproject.toml`: the generator's output plus configuration sections for ruff, mypy (strict) and pytest (D45). **No dependency is added by this task**; dependencies are added in `FEAT-1208` after one approval.
- `requires-python = ">=3.12,<3.13"`, so nothing newer sneaks in.

### 3.3 Frontend

- Generated with `npx create-next-app@latest frontend` with TypeScript, the App Router and the `src/` folder (so the code is in `frontend/src`). `npx` runs the generator from the npm cache; nothing is installed globally.
- The generator installs its own packages into `frontend/node_modules` (project-local). **Approving this spec approves that generator package set**, and I will list the exact packages and versions it chose in the commit message and in the notepad for review.
- **Open choice:** the generator offers Tailwind CSS. The UI libraries are decided in `FEAT-1222`. My suggestion: say no to Tailwind here and decide it in `FEAT-1222`, so that this task adds nothing we have not chosen. Adding it later is one command.

### 3.4 Repository files at the root

- `.gitignore`: Python (`.venv`, caches), Node (`node_modules`, `.next`), `.env` files (but not `.env.example`), editor files. `CLAUDE.md` stays excluded through `.git/info/exclude`, not here, since the file is meant to stay local.
- `.gitattributes` with `* text=auto eol=lf`. Reason: you are on Windows; without it, files written with Windows line endings break shell scripts and Docker entrypoints inside Linux containers.
- `README.md`: what the project is, how to start the stack, and the exact commands to lint, type-check and test (no task runner, D45). Starts short and grows as tasks land.
- `docs/specs/` already exists (this folder). `docs/adr/` and `docs/apis/` are created by their first file, because git does not track empty folders.

## 4. Tests and checks

- This task adds no Python packages, so pytest, ruff and mypy are not available yet. What it checks: every folder in 3.2 exists and is a package; `uv` reads `pyproject.toml` and resolves Python 3.12 (`uv python find 3.12`); `npm run build` in `frontend/` succeeds; `git status` shows no `.venv`, `node_modules` or `.next`.
- The checks that need the dev tools (`uv run pytest` finding the four placeholder tests, `ruff check`, `ruff format --check`, `mypy`) run in `FEAT-1208`, which is why the order of work is `1201`, then `1208` (see the order in `README.md` of this folder).

## 5. Check for the same problem elsewhere

This is new construction, so there is no earlier defect to search for. The related risk checked: whether any existing doc names a path this layout changes. `ARCHITECTURE.md` section 6 names `backend/src/<folders>`; the change in 3.2 means that section is updated in this task to say `backend/src/qfe/<folders>`.

## 6. Out of scope

Dockerfiles and Compose (`FEAT-1202`), configuration code (`FEAT-1203`), any dependency install (`FEAT-1208`), the UI library choice (`FEAT-1222`).

## 7. Questions for you

1. Approve installing uv for the current user?
2. Approve the single `qfe` package under `backend/src/`?
3. Tailwind: no for now (my suggestion), or yes?
