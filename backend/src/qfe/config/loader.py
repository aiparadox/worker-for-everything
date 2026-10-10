"""Loading settings at process start: all problems at once, never a value, exit code 2."""

import sys
from typing import NoReturn, TextIO

from pydantic import ValidationError

from qfe.config.base import QfeSettings

EXIT_CODE_BAD_CONFIG = 2


def describe_problems(error: ValidationError, env_prefix: str = "QFE_") -> list[str]:
    """One line per problem: the variable name and the reason. The offending value is never
    included, because it may be a secret."""
    lines: list[str] = []
    for item in error.errors(include_input=False, include_url=False):
        location = [str(part) for part in item["loc"]]
        name = (env_prefix + location[-1]).upper() if location else ""
        if item["type"] == "missing":
            lines.append(f"  {name}: is required but missing")
        elif not location:
            # A rule that spans several settings; its message already names the variables.
            lines.append(f"  {item['msg'].removeprefix('Value error, ')}")
        else:
            lines.append(f"  {name}: {item['msg'].removeprefix('Value error, ')}")
    return lines


def fail(error: ValidationError, stream: TextIO | None = None) -> NoReturn:
    out = stream if stream is not None else sys.stderr
    problems = describe_problems(error)
    print("Invalid configuration, the process will not start:", file=out)
    print("\n".join(problems), file=out)
    raise SystemExit(EXIT_CODE_BAD_CONFIG)


def load_or_exit[S: QfeSettings](settings_class: type[S]) -> S:
    """Build the settings for this process, or print every problem and exit with code 2."""
    try:
        return settings_class()
    except ValidationError as error:
        fail(error)
