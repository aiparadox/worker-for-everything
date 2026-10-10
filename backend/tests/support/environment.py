"""Reading the .env style files the tests and Compose share.

A file is read top to bottom; ``${NAME}`` is filled in from names defined earlier (the same rule
Compose uses), so a URL can reuse a password defined above it.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"

_LINE = re.compile(r"^(?:#\s*)?(?P<name>[A-Z][A-Z0-9_]*)=(?P<value>.*)$")
_REFERENCE = re.compile(r"\$\{(\w+)\}")


def read_env_file(
    path: Path, *, include_commented: bool = False, base: dict[str, str] | None = None
) -> dict[str, str]:
    """Parse KEY=VALUE lines. Commented lines are ignored unless ``include_commented``."""
    values: dict[str, str] = dict(base or {})
    parsed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _LINE.match(line)
        if not match or (line.startswith("#") and not include_commented):
            continue
        value = _REFERENCE.sub(lambda m: values[m.group(1)], match.group("value"))
        values[match.group("name")] = value
        parsed[match.group("name")] = value
    return parsed


def load_test_environment() -> dict[str, str]:
    """Settings for tests that run on this machine: ``.env`` with ``.env.test`` on top."""
    env_path = REPO_ROOT / ".env"
    test_path = REPO_ROOT / ".env.test"
    missing = [p.name for p in (env_path, test_path) if not p.exists()]
    if missing:
        raise RuntimeError(
            f"missing {', '.join(missing)} in the repository root; copy .env.example to .env and "
            ".env.test.example to .env.test"
        )
    base = read_env_file(env_path)
    return {**base, **read_env_file(test_path, base=base)}
