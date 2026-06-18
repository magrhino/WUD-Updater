from __future__ import annotations

import ast
import importlib.metadata
import re
import sys
from pathlib import Path

_REQUIREMENT_NAME_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"
)
_VERSION_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.!+-"
)
_SPECIFIER_OPERATORS = ("==", ">=", "<=", ">", "<")


def read_cli_file(path_arg: str) -> str:
    base_dir = Path.cwd().resolve()
    candidate = Path(path_arg)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    # Canonicalize before validating so CLI input cannot escape this checkout.
    canonical_path = candidate.resolve()

    try:
        canonical_path.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(
            "pyproject path must stay within the current working directory"
        ) from exc

    return canonical_path.read_text(encoding="utf-8")


def read_dependencies_with_tomllib(pyproject_content: str) -> list[str] | None:
    try:
        import tomllib
    except ModuleNotFoundError:
        return None

    data = tomllib.loads(pyproject_content)
    project = data.get("project", {})
    optional = project.get("optional-dependencies", {})
    return [*project.get("dependencies", []), *optional.get("dev", [])]


def read_fallback_list(
    pyproject_content: str,
    section_name: str,
    field_name: str,
) -> list[str]:
    values: list[str] = []
    in_section = False
    in_list = False
    list_header = f"{field_name} = ["

    for raw_line in pyproject_content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = line[1:-1] == section_name
            in_list = False
        elif not in_section:
            continue
        elif in_list:
            if line == "]":
                in_list = False
            else:
                values.append(ast.literal_eval(line.rstrip(",")))
        elif line == list_header:
            in_list = True

    return values


def read_dependencies_fallback(pyproject_content: str) -> list[str]:
    return [
        *read_fallback_list(pyproject_content, "project", "dependencies"),
        *read_fallback_list(pyproject_content, "project.optional-dependencies", "dev"),
    ]


def read_dependencies(pyproject_content: str) -> list[str]:
    dependencies = read_dependencies_with_tomllib(pyproject_content)
    if dependencies is not None:
        return dependencies
    return read_dependencies_fallback(pyproject_content)


def compare_versions(actual: str, expected: str) -> int:
    actual_parts = [int(part) for part in re.findall(r"\d+", actual.split("+", 1)[0])]
    expected_parts = [int(part) for part in re.findall(r"\d+", expected.split("+", 1)[0])]
    length = max(len(actual_parts), len(expected_parts))
    actual_parts.extend([0] * (length - len(actual_parts)))
    expected_parts.extend([0] * (length - len(expected_parts)))
    return (actual_parts > expected_parts) - (actual_parts < expected_parts)


def split_fallback_requirement(requirement: str) -> tuple[str, str] | None:
    name_end = 0
    while (
        name_end < len(requirement)
        and requirement[name_end] in _REQUIREMENT_NAME_CHARS
    ):
        name_end += 1

    if name_end == 0:
        return None

    return requirement[:name_end], requirement[name_end:].strip()


def split_fallback_clause(clause: str) -> tuple[str, str] | None:
    for operator in _SPECIFIER_OPERATORS:
        if clause.startswith(operator):
            expected = clause[len(operator) :].strip()
            if expected and all(char in _VERSION_CHARS for char in expected):
                return operator, expected
            return None
    return None


def fallback_requirement_error(requirement: str) -> str | None:
    parsed = split_fallback_requirement(requirement)
    if not parsed:
        return f"unsupported requirement format: {requirement}"

    name, specifier = parsed
    try:
        actual = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return f"missing {name} (required: {specifier or 'installed'})"

    for clause in filter(None, (part.strip() for part in specifier.split(","))):
        parsed_clause = split_fallback_clause(clause)
        if not parsed_clause:
            return f"unsupported version specifier for {name}: {clause}"
        operator, expected = parsed_clause
        comparison = compare_versions(actual, expected)
        satisfied = (
            (operator == "==" and actual == expected)
            or (operator == ">=" and comparison >= 0)
            or (operator == "<=" and comparison <= 0)
            or (operator == ">" and comparison > 0)
            or (operator == "<" and comparison < 0)
        )
        if not satisfied:
            return f"{name} {actual} does not satisfy {specifier}"

    return None


def requirement_error(requirement: str) -> str | None:
    try:
        from packaging.requirements import InvalidRequirement, Requirement
        from packaging.version import Version
    except ModuleNotFoundError:
        return fallback_requirement_error(requirement)

    try:
        parsed = Requirement(requirement)
    except InvalidRequirement as exc:
        return f"unsupported requirement format: {requirement} ({exc})"

    if parsed.marker is not None and not parsed.marker.evaluate():
        return None

    try:
        actual = importlib.metadata.version(parsed.name)
    except importlib.metadata.PackageNotFoundError:
        return f"missing {parsed.name} (required: {parsed.specifier or 'installed'})"

    if parsed.specifier and Version(actual) not in parsed.specifier:
        return f"{parsed.name} {actual} does not satisfy {parsed.specifier}"

    return None


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: check_python_deps.py pyproject.toml", file=sys.stderr)
        return 2

    try:
        pyproject_content = read_cli_file(sys.argv[1])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    errors = [
        error
        for requirement in read_dependencies(pyproject_content)
        if (error := requirement_error(requirement))
    ]
    if not errors:
        return 0

    print("Python dependency preflight failed:", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    print(
        "Install/update the Python development dependencies with: "
        f"{sys.executable} -m pip install -e '.[dev]'",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
