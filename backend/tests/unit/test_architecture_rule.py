"""The adapter rule from docs/ARCHITECTURE.md section 6: domain, application and ports never
import from adapters. Checked by reading the source with the ast module (no extra package)."""

import ast
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "qfe"
FORBIDDEN_PREFIX = "qfe.adapters"
PROTECTED_PACKAGES = ["domain", "application", "ports"]


def imported_modules(source: str) -> list[str]:
    """Every module name imported by ``source``, absolute and fully spelled out."""
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # a relative import such as "from ..adapters import x"
                modules.append("." * node.level + (node.module or ""))
            elif node.module:
                modules.append(node.module)
                modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def find_violations(package_dir: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(package_dir.rglob("*.py")):
        for module in imported_modules(path.read_text(encoding="utf-8")):
            relative_adapter_import = module.startswith(".") and "adapters" in module
            if module.startswith(FORBIDDEN_PREFIX) or relative_adapter_import:
                violations.append(f"{path.name} imports {module}")
    return violations


@pytest.mark.parametrize("package", PROTECTED_PACKAGES)
def test_protected_packages_do_not_import_adapters(package: str) -> None:
    assert find_violations(SOURCE_ROOT / package) == []


@pytest.mark.parametrize(
    "bad_line",
    [
        "import qfe.adapters.postgres",
        "from qfe.adapters.postgres import tables",
        "from qfe.adapters import postgres",
        "from ..adapters import postgres",
    ],
)
def test_the_check_can_fail(tmp_path: Path, bad_line: str) -> None:
    (tmp_path / "offender.py").write_text(bad_line + "\n", encoding="utf-8")
    assert find_violations(tmp_path) != []


def test_the_check_ignores_other_imports(tmp_path: Path) -> None:
    (tmp_path / "fine.py").write_text(
        "import qfe.ports\nfrom qfe.domain import x\n", encoding="utf-8"
    )
    assert find_violations(tmp_path) == []
