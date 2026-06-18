from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import check_python_deps


class DependencyPreflightPathTests(unittest.TestCase):
    def test_read_cli_file_allows_file_inside_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            pyproject_path = repo_root / "pyproject.toml"
            pyproject_path.write_text("[project]\ndependencies = []\n", encoding="utf-8")

            with mock.patch.object(check_python_deps.Path, "cwd", return_value=repo_root):
                self.assertEqual(
                    check_python_deps.read_cli_file("pyproject.toml"),
                    "[project]\ndependencies = []\n",
                )
                self.assertEqual(
                    check_python_deps.read_cli_file(str(pyproject_path)),
                    "[project]\ndependencies = []\n",
                )

    def test_read_cli_file_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            repo_root = temp_path / "repo"
            repo_root.mkdir()
            (temp_path / "pyproject.toml").write_text(
                "[project]\ndependencies = []\n",
                encoding="utf-8",
            )

            with mock.patch.object(check_python_deps.Path, "cwd", return_value=repo_root):
                with self.assertRaisesRegex(ValueError, "current working directory"):
                    check_python_deps.read_cli_file("../pyproject.toml")


class DependencyPreflightFallbackTests(unittest.TestCase):
    def test_fallback_requirement_accepts_supported_specifiers(self) -> None:
        with mock.patch.object(
            check_python_deps.importlib.metadata,
            "version",
            return_value="1.4.0",
        ) as version:
            self.assertIsNone(
                check_python_deps.fallback_requirement_error(
                    "demo-package   >= 1.2,<2"
                )
            )

        version.assert_called_once_with("demo-package")

    def test_fallback_requirement_rejects_unsupported_name_format(self) -> None:
        self.assertEqual(
            check_python_deps.fallback_requirement_error(" demo-package>=1.2"),
            "unsupported requirement format:  demo-package>=1.2",
        )

    def test_fallback_requirement_rejects_unsupported_specifier(self) -> None:
        with mock.patch.object(
            check_python_deps.importlib.metadata,
            "version",
            return_value="1.4.0",
        ):
            self.assertEqual(
                check_python_deps.fallback_requirement_error("demo-package~=1.2"),
                "unsupported version specifier for demo-package: ~=1.2",
            )


if __name__ == "__main__":
    unittest.main()
