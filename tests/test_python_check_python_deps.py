from __future__ import annotations

import unittest
from unittest import mock

import check_python_deps


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
