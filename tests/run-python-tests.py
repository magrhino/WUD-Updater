#!/usr/bin/env python3
"""No-dependency Python test runner for the package."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))

    suite = unittest.defaultTestLoader.discover(
        str(repo_root / "tests"),
        pattern="test_python_*.py",
    )
    if suite.countTestCases() == 0:
        print("No Python tests were discovered.", file=sys.stderr)
        return 1

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
