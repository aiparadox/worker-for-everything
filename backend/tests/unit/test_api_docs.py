"""Every route has a documentation file (docs/ARCHITECTURE.md sections 13 and 14)."""

from pathlib import Path

import pytest

from qfe.api.app import create_app
from tests.support.api_docs import REQUIRED_HEADINGS, check_api_docs, doc_file_name
from tests.support.environment import REPO_ROOT

DOCS_DIR = REPO_ROOT / "docs" / "apis"
ROUTES = ("get-healthz.md", "get-readyz.md", "get-metrics.md")


def test_every_route_of_the_application_is_documented() -> None:
    assert check_api_docs(create_app([]), DOCS_DIR) == []


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/healthz", "get-healthz.md"),
        ("POST", "/v1/jobs", "post-v1-jobs.md"),
        ("GET", "/v1/jobs/{id}/attempts", "get-v1-jobs-id-attempts.md"),
        ("DELETE", "/v1/api-keys/{key_id}", "delete-v1-api-keys-key_id.md"),
    ],
)
def test_the_file_name_rule(method: str, path: str, expected: str) -> None:
    assert doc_file_name(method, path) == expected


# --- The check can fail ------------------------------------------------------------------------


def complete_doc() -> str:
    return "\n".join(f"## {heading}\n\ntext\n" for heading in REQUIRED_HEADINGS)


def write_docs(directory: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")


def readme_for(*names: str) -> str:
    return "\n".join(f"- [{name}]({name})" for name in names)


def all_good() -> dict[str, str]:
    return {**dict.fromkeys(ROUTES, complete_doc()), "README.md": readme_for(*ROUTES)}


def problems_for(directory: Path) -> list[str]:
    return check_api_docs(create_app([]), directory)


def test_a_complete_docs_folder_passes(tmp_path: Path) -> None:
    write_docs(tmp_path, all_good())
    assert problems_for(tmp_path) == []


def test_a_route_without_a_file_fails(tmp_path: Path) -> None:
    files = all_good()
    del files["get-readyz.md"]
    write_docs(tmp_path, files)
    assert any("no doc file for a route: get-readyz.md" in p for p in problems_for(tmp_path))


def test_a_file_without_a_route_fails(tmp_path: Path) -> None:
    write_docs(tmp_path, {**all_good(), "get-old-thing.md": complete_doc()})
    assert any("no matching route" in p for p in problems_for(tmp_path))


def test_a_missing_heading_fails(tmp_path: Path) -> None:
    files = all_good()
    files["get-healthz.md"] = complete_doc().replace("## Rate limits", "## Something else")
    write_docs(tmp_path, files)
    assert any("get-healthz.md has no 'Rate limits' heading" in p for p in problems_for(tmp_path))


def test_a_file_missing_from_the_readme_fails(tmp_path: Path) -> None:
    files = all_good()
    files["README.md"] = readme_for("get-healthz.md", "get-readyz.md")
    write_docs(tmp_path, files)
    assert any("README.md does not list get-metrics.md" in p for p in problems_for(tmp_path))


def test_a_missing_readme_fails(tmp_path: Path) -> None:
    files = all_good()
    del files["README.md"]
    write_docs(tmp_path, files)
    assert any("README.md is missing" in p for p in problems_for(tmp_path))
