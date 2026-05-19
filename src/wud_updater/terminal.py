"""Terminal rendering helpers with optional Rich support."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from typing import Any, TextIO


try:  # pragma: no cover - exercised by Rich-specific tests when installed.
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:  # pragma: no cover - plain fallback is tested directly.
    box = None
    Console = None
    Panel = None
    Table = None
    Text = None

RICH_AVAILABLE = Console is not None


class TerminalRenderer:
    """Render terminal output with Rich when appropriate, otherwise plain text."""

    def __init__(
        self,
        *,
        no_color: bool = False,
        environ: Mapping[str, str] | None = None,
        stream: TextIO | None = None,
        force_rich: bool = False,
        width: int | None = None,
    ) -> None:
        self.environ = dict(environ or {})
        self.stream = sys.stdout if stream is None else stream
        self.no_color = no_color or "NO_COLOR" in self.environ
        self.force_rich = force_rich
        self.width = width
        self._consoles: dict[int, Any] = {}

    def rich_enabled(self, stream: TextIO | None = None) -> bool:
        target = self.stream if stream is None else stream
        return RICH_AVAILABLE and not self.no_color and (
            self.force_rich or _stream_is_tty(target)
        )

    def line(
        self,
        message: str = "",
        *,
        style: str | None = None,
        stream: TextIO | None = None,
    ) -> None:
        target = self.stream if stream is None else stream
        if self.rich_enabled(target):
            self._console(target).print(message, style=style)
        else:
            print(message, file=target)

    def blank(self, *, stream: TextIO | None = None) -> None:
        self.line("", stream=stream)

    def log_line(
        self,
        *,
        timestamp: str,
        level: str,
        message: str,
        stream: TextIO | None = None,
    ) -> None:
        target = self.stream if stream is None else stream
        if not self.rich_enabled(target) or Text is None:
            print(f"[{timestamp}] {message}", file=target)
            return

        level_style = _LEVEL_STYLES.get(level, "bold cyan")
        text = Text()
        text.append(f"[{timestamp}]", style="dim")
        text.append(" ")
        text.append(f"{level:<5}", style=level_style)
        text.append(" ")
        text.append(message)
        self._console(target).print(text)

    def status(
        self,
        message: str,
        *,
        kind: str = "info",
        plain: str | None = None,
        stream: TextIO | None = None,
    ) -> None:
        target = self.stream if stream is None else stream
        if not self.rich_enabled(target):
            print(plain or message, file=target)
            return

        style = _KIND_STYLES.get(kind, "bold cyan")
        prefix = _KIND_PREFIXES.get(kind, "")
        self._console(target).print(f"{prefix}{message}", style=style)

    def docker_updates(self, rows: Sequence[tuple[int, str]]) -> None:
        if not self.rich_enabled():
            print("=== 📦 Docker Updates ===", file=self.stream)
            if rows:
                for number, target in rows:
                    print(f"{number}\t{target}", file=self.stream)
            else:
                print("✅ No pending Docker updates!", file=self.stream)
            return

        count = len(rows)
        summary = (
            f"{count} pending image update{'s' if count != 1 else ''} from WUD"
            if count
            else "✓ No pending Docker updates!"
        )
        style = "bold yellow" if count else "bold green"
        self.panel("Docker Updates", summary, body_style=style)
        if not rows:
            return

        table = self._table()
        table.add_column("#", justify="right", style="dim", no_wrap=True)
        table.add_column("Image / container target", style="white")
        table.add_column("Status", style="bold yellow", no_wrap=True)
        for number, target in rows:
            table.add_row(str(number), target, "pending")
        self._console(self.stream).print(table)

    def truenas_panel(
        self,
        title: str,
        lines: Sequence[tuple[str, str]],
        *,
        plain_header: str,
    ) -> None:
        if not self.rich_enabled():
            print(plain_header, file=self.stream)
            for line, _kind in lines:
                print(line, file=self.stream)
            return

        if Text is None:
            return
        body = Text()
        for index, (line, kind) in enumerate(lines):
            if index:
                body.append("\n")
            body.append(line, style=_KIND_STYLES.get(kind, "white"))
        self.panel(title, body)

    def prompt_choice(self, question: str, choices: str) -> str:
        if not self.rich_enabled():
            try:
                return input(f"{question} {choices} ")
            except EOFError:
                return ""

        console = self._console(self.stream)
        console.print(question, style="bold cyan")
        console.print(f"  {choices}", style="blue")
        try:
            return input("Choice: ")
        except EOFError:
            return ""

    def panel(
        self,
        title: str,
        body: str | Any,
        *,
        body_style: str | None = None,
        stream: TextIO | None = None,
    ) -> None:
        target = self.stream if stream is None else stream
        if not self.rich_enabled(target) or Panel is None:
            print(str(body), file=target)
            return
        self._console(target).print(
            Panel(
                body,
                title=f" {title} ",
                title_align="left",
                border_style="bold cyan",
                style=body_style,
            )
        )

    def updater_targets(self, rows: Sequence[tuple[int, str, str, str]]) -> None:
        if not self.rich_enabled():
            return

        table = self._table(title="Targets")
        table.add_column("Line", justify="right", style="dim", no_wrap=True)
        table.add_column("Target", style="white")
        table.add_column("Digest", style="dim")
        table.add_column("Tag", style="blue")
        for line_no, target, digest, tag in rows:
            table.add_row(str(line_no), target, digest, tag)
        self._console(self.stream).print(table)

    def updater_stack_plan(
        self,
        rows: Sequence[tuple[str, str, Sequence[str]]],
    ) -> None:
        if not self.rich_enabled():
            return

        for name, services, lines in rows:
            if Text is None:
                return
            body = Text()
            body.append("Services: ", style="dim")
            body.append(services or "stack-level fallback")
            for line in lines:
                body.append("\n")
                body.append(line, style="white")
            self.panel(f"Stack: {name}", body)

    def stack_summary(
        self,
        name: str,
        lines: Sequence[tuple[str, str]],
    ) -> None:
        if not self.rich_enabled():
            return
        if Text is None:
            return
        body = Text()
        for index, (line, kind) in enumerate(lines):
            if index:
                body.append("\n")
            body.append(line, style=_KIND_STYLES.get(kind, "white"))
        self.panel(f"Stack: {name}", body)

    def _table(self, *, title: str | None = None) -> Any:
        if Table is None:
            raise RuntimeError("Rich table requested when Rich is unavailable")
        table = Table(
            title=title,
            box=box.SIMPLE_HEAVY if box is not None else None,
            header_style="bold cyan",
            border_style="bold cyan",
        )
        return table

    def _console(self, stream: TextIO) -> Any:
        key = id(stream)
        if key not in self._consoles:
            if Console is None:
                raise RuntimeError("Rich console requested when Rich is unavailable")
            self._consoles[key] = Console(
                file=stream,
                force_terminal=True if self.force_rich else None,
                color_system="standard",
                width=self.width,
            )
        return self._consoles[key]


def _stream_is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


_LEVEL_STYLES = {
    "INFO": "bold cyan",
    "WARN": "bold yellow",
    "ERROR": "bold red",
}
_KIND_STYLES = {
    "info": "bold cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "path": "dim",
}
_KIND_PREFIXES = {
    "success": "✓ ",
    "warning": "! ",
    "error": "✗ ",
}
