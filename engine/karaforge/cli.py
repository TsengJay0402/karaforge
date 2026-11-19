"""The ``kf`` command line interface.

Commands are thin wrappers around the engine; see ``docs/cli.md`` for the full reference.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer
from rich.console import Console

from karaforge import __version__
from karaforge.errors import KaraForgeError
from karaforge.i18n import current_lang

app = typer.Typer(
    name="kf",
    help="KaraForge:把歌曲與歌詞變成 KTV 影片 / turn a song and its lyrics into a karaoke video.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"KaraForge {__version__}")
        raise typer.Exit


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="顯示版本 / show the version and exit.",
        ),
    ] = False,
) -> None:
    """Global options."""


def report_error(error: KaraForgeError, *, verbose: bool = False) -> None:
    """Print a user-facing error message to stderr."""
    lang = current_lang()
    label = "錯誤" if lang == "zh" else "Error"
    err_console.print(f"[bold red]{label}:[/bold red] {error.user_message(lang)}", highlight=False)
    if verbose and error.detail:
        err_console.print(f"[dim]{error.detail}[/dim]", highlight=False)


def main() -> None:
    """Entry point for the ``kf`` console script."""
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    try:
        app()
    except KaraForgeError as error:
        report_error(error, verbose=verbose)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
