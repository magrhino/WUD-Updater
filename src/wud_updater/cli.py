"""Command line interface for WUD-Updater Python entrypoints."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .updater import UpdaterError, options_from_namespace, run_update_from_wud
from .updates import (
    run_truenas_status_export_from_namespace,
    run_updates_from_namespace,
)


class WudArgumentParser(argparse.ArgumentParser):
    def format_help(self) -> str:
        return _capitalized_usage(super().format_help())

    def format_usage(self) -> str:
        return _capitalized_usage(super().format_usage())


def _capitalized_usage(value: str) -> str:
    if value.startswith("usage:"):
        return "Usage:" + value[len("usage:") :]
    return value


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base", metavar="PATH")
    parser.add_argument("--file", metavar="PATH")
    parser.add_argument("--mode", choices=("pause", "stop", "live"))
    parser.add_argument("--max-wait", metavar="SECONDS")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-y", "--yes", "--no-confirm", action="store_true")
    parser.add_argument("--allow-tag-updates", action="store_true")


def _add_update_from_wud_options(parser: argparse.ArgumentParser) -> None:
    _add_common_options(parser)
    parser.add_argument("--log-dir", metavar="PATH")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--only-lines", metavar="SPEC")
    parser.add_argument("--remove-lines-before-run", metavar="SPEC")


def _add_updates_options(parser: argparse.ArgumentParser) -> None:
    _add_common_options(parser)
    parser.add_argument("--log-dir", metavar="PATH")
    parser.add_argument(
        "--no-updater-sudo",
        action="store_true",
        help="run the configured updater directly and disable sudo file fallbacks",
    )


def _run_update_from_wud(args: argparse.Namespace) -> int:
    try:
        options = options_from_namespace(args)
    except UpdaterError as exc:
        print(exc, file=sys.stderr)
        return 1
    return run_update_from_wud(options)


def _run_updates(args: argparse.Namespace) -> int:
    return run_updates_from_namespace(
        args,
        repo_root=Path(__file__).resolve().parents[2],
    )


def _run_truenas_status_export(args: argparse.Namespace) -> int:
    return run_truenas_status_export_from_namespace(args)


def build_parser() -> argparse.ArgumentParser:
    parser = WudArgumentParser(
        prog="wud-updater",
        description="WUD updater command line tools.",
    )
    subcommands = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=WudArgumentParser,
    )

    update_from_wud = subcommands.add_parser(
        "update-from-wud",
        help="run the Python docker-update-from-wud implementation",
    )
    _add_update_from_wud_options(update_from_wud)
    update_from_wud.set_defaults(handler=_run_update_from_wud)

    updates = subcommands.add_parser(
        "updates",
        help="show WUD updates and optionally run the updater",
    )
    _add_updates_options(updates)
    updates.set_defaults(handler=_run_updates)

    truenas_status_export = subcommands.add_parser(
        "truenas-status-export",
        help=argparse.SUPPRESS,
    )
    truenas_status_export.set_defaults(handler=_run_truenas_status_export)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
