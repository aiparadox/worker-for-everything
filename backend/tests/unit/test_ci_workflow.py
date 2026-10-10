"""The CI workflow stays in step with the commands in the README and with the folders that exist
(docs/specs/FEAT-20261010-1319-github-actions.md)."""

import re
from pathlib import Path

from tests.support.environment import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
README = REPO_ROOT / "README.md"
TEXT = WORKFLOW.read_text(encoding="utf-8")


def run_commands() -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^\s*(?:-\s+)?run:\s+(\S.*)$", TEXT, re.M)]


def test_the_three_jobs_exist() -> None:
    for job in ("backend-checks:", "backend-stack-tests:", "frontend:"):
        assert re.search(rf"^  {re.escape(job)}", TEXT, re.M), job


def test_it_runs_on_pushes_to_master_and_on_pull_requests() -> None:
    assert re.search(r"push:\s*\n\s*branches:\s*\[master\]", TEXT)
    assert re.search(r"^  pull_request:", TEXT, re.M)


def test_it_can_be_started_by_hand() -> None:
    assert re.search(r"^  workflow_dispatch:", TEXT, re.M)


def test_it_only_needs_read_access() -> None:
    assert re.search(r"^permissions:\s*\n\s+contents: read\s*$", TEXT, re.M)


def test_every_test_path_the_workflow_runs_exists() -> None:
    paths = {path for command in run_commands() for path in re.findall(r"\btests/\w+", command)}
    assert paths, "the workflow should run tests"
    for path in paths:
        assert (REPO_ROOT / "backend" / path).is_dir(), path


def test_the_workflow_runs_the_same_checks_as_the_readme() -> None:
    readme = README.read_text(encoding="utf-8")
    for command in (
        "uv run ruff check",
        "uv run ruff format --check",
        "uv run mypy",
        "npm run lint",
        "npm run build",
    ):
        assert command in readme, f"README lacks: {command}"
        assert command in TEXT, f"workflow lacks: {command}"


def test_the_uv_version_matches_the_one_the_image_uses() -> None:
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    image = re.search(r"astral-sh/uv:([\d.]+)", dockerfile)
    workflow = re.search(r'version: "([\d.]+)"', TEXT)
    assert image and workflow
    assert image.group(1) == workflow.group(1)


def test_the_example_files_the_workflow_copies_exist() -> None:
    for name in re.findall(r"\bcp (\.env[\w.]*) ", TEXT):
        assert (REPO_ROOT / name).is_file(), name
    assert Path(REPO_ROOT / ".env.test.example").is_file()
