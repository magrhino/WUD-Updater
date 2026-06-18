from __future__ import annotations

import ast
import importlib.metadata
import re
import sys
from pathlib import Path


def read_dependencies_with_tomllib(pyproject_path: Path) -> list[str] | None:
    try:
        import tomllib
    except ModuleNotFoundError:
        return None

    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    optional = project.get("optional-dependencies", {})
    return [*project.get("dependencies", []), *optional.get("dev", [])]


def read_dependencies_fallback(pyproject_path: Path) -> list[str]:
    dependencies: list[str] = []
    dev_dependencies: list[str] = []
    section = ""
    target: list[str] | None = None

    for raw_line in pyproject_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            target = None
            continue
        if target is not None:
            if line == "]":
                target = None
                continue
            target.append(ast.literal_eval(line.rstrip(",")))
            continue
        if section == "project" and line == "dependencies = [":
            target = dependencies
            continue
        if section == "project.optional-dependencies" and line == "dev = [":
            target = dev_dependencies
            continue

    return [*dependencies, *dev_dependencies]


def read_dependencies(pyproject_path: Path) -> list[str]:
    dependencies = read_dependencies_with_tomllib(pyproject_path)
    if dependencies is not None:
        return dependencies
    return read_dependencies_fallback(pyproject_path)


def compare_versions(actual: str, expected: str) -> int:
    actual_parts = [int(part) for part in re.findall(r"\d+", actual.split("+", 1)[0])]
    expected_parts = [int(part) for part in re.findall(r"\d+", expected.split("+", 1)[0])]
    length = max(len(actual_parts), len(expected_parts))
    actual_parts.extend([0] * (length - len(actual_parts)))
    expected_parts.extend([0] * (length - len(expected_parts)))
    return (actual_parts > expected_parts) - (actual_parts < expected_parts)


def fallback_requirement_error(requirement: str) -> str | None:
    match = re.match(r"^([A-Za-z0-9_.-]+)\s*(.*)$", requirement)
    if not match:
        return f"unsupported requirement format: {requirement}"

    name = match.group(1)
    specifier = match.group(2).strip()
    try:
        actual = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return f"missing {name} (required: {specifier or 'installed'})"

    for clause in filter(None, (part.strip() for part in specifier.split(","))):
        clause_match = re.match(r"^(==|>=|<=|>|<)\s*([A-Za-z0-9_.!+-]+)$", clause)
        if not clause_match:
            return f"unsupported version specifier for {name}: {clause}"
        operator, expected = clause_match.groups()
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

    errors = [
        error
        for requirement in read_dependencies(Path(sys.argv[1]))
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
