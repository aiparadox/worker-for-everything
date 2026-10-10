"""The API documentation check (docs/ARCHITECTURE.md sections 13 and 14).

Every route of the application has a file in ``docs/apis/``; the file name comes from the method
and the path (``POST /v1/jobs`` is ``post-v1-jobs.md``, ``GET /v1/jobs/{id}/attempts`` is
``get-v1-jobs-id-attempts.md``); the file has the required headings; ``docs/apis/README.md`` lists
every file; and no file documents a route that no longer exists.
"""

import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute

# Framework routes that are not part of our API.
IGNORED_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}

# Every endpoint file must have a heading for each of these (case does not matter).
REQUIRED_HEADINGS = (
    "Method and path",
    "Path parameters",
    "Query parameters",
    "Headers",
    "Request body",
    "Responses",
    "Errors",
    "Authentication and scopes",
    "Rate limits",
    "Examples",
)

# Files in docs/apis/ that are not endpoint files.
NOT_ENDPOINT_FILES = {"README.md"}


def doc_file_name(method: str, path: str) -> str:
    """``POST /v1/jobs`` -> ``post-v1-jobs.md``."""
    cleaned = path.strip("/").replace("{", "").replace("}", "").replace("/", "-")
    return f"{method.lower()}-{cleaned}.md"


def documented_routes(app: FastAPI) -> set[str]:
    """The expected doc file name of every route of the app."""
    names: set[str] = set()
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path not in IGNORED_PATHS:
            names.update(doc_file_name(method, route.path) for method in route.methods or set())
    return names


def check_api_docs(app: FastAPI, docs_dir: Path) -> list[str]:
    """Return every problem found; an empty list means the docs are complete."""
    problems: list[str] = []
    expected = documented_routes(app)
    present = {
        path.name
        for path in docs_dir.glob("*.md")
        if path.name not in NOT_ENDPOINT_FILES and not path.name.startswith("_")
    }

    for name in sorted(expected - present):
        problems.append(f"no doc file for a route: {name}")
    for name in sorted(present - expected):
        problems.append(f"doc file with no matching route (stale?): {name}")

    readme = docs_dir / "README.md"
    readme_text = readme.read_text(encoding="utf-8") if readme.exists() else ""
    if not readme.exists():
        problems.append("docs/apis/README.md is missing")
    for name in sorted(expected & present):
        if f"({name})" not in readme_text:
            problems.append(f"README.md does not list {name}")
        text = (docs_dir / name).read_text(encoding="utf-8")
        headings = {
            match.group(1).strip().lower() for match in re.finditer(r"^#{1,6}\s+(.+)$", text, re.M)
        }
        problems.extend(
            f"{name} has no '{required}' heading"
            for required in REQUIRED_HEADINGS
            if required.lower() not in headings
        )
    return problems
