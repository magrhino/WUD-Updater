"""Placeholder command line interface for a future Python implementation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


NOT_WIRED_MESSAGE = "Python implementation not wired yet."


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base", metavar="PATH")
    parser.add_argument("--file", metavar="PATH")
    parser.add_argument("--mode", choices=("pause", "stop", "live"))
    parser.add_argument("--max-wait", metavar="SECONDS")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-y", "--yes", action="store_true")
    parser.add_argument("--allow-tag-updates", action="store_true")


def _add_update_from_wud_options(parser: argparse.ArgumentParser) -> None:
    _add_common_options(parser)
    parser.add_argument("--log-dir", metavar="PATH")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--only-lines", metavar="SPEC")
    parser.add_argument("--remove-lines-before-run", metavar="SPEC")


def _placeholder_exit(command: str, shell_command: str, mutating_path: bool) -> int:
    print(f"wud-updater {command}: {NOT_WIRED_MESSAGE}", file=sys.stderr)
    print(f"Use the existing shell command instead: {shell_command}", file=sys.stderr)
    if mutating_path:
        print("Refusing to continue because this path may mutate Docker state.", file=sys.stderr)
        return 1
    print("No changes were made.", file=sys.stderr)
    return 0


def _run_update_from_wud(args: argparse.Namespace) -> int:
    return _placeholder_exit(
        "update-from-wud",
        "bin/docker-update-from-wud",
        mutating_path=not args.dry_run,
    )


def _run_updates(args: argparse.Namespace) -> int:
    return _placeholder_exit(
        "updates",
        "bin/updates",
        mutating_path=not args.dry_run,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wud-updater",
        description="Placeholder CLI for a future Python WUD updater implementation.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    update_from_wud = subcommands.add_parser(
        "update-from-wud",
        help="placeholder for docker-update-from-wud",
    )
    _add_update_from_wud_options(update_from_wud)
    update_from_wud.set_defaults(handler=_run_update_from_wud)

    updates = subcommands.add_parser(
        "updates",
        help="placeholder for updates",
    )
    _add_common_options(updates)
    updates.set_defaults(handler=_run_updates)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
