import typer
from pathlib import Path
from typing import Optional, List
from rich.console import Console
import pyperclip
from enum import Enum
from importlib.metadata import version as get_version

from .core import (
    scan_directory,
    DiffMode,
    get_file_content,
)
from .format import (
    format_files as format_files_xml,
    create_display_header,
)
from .sources import GitHubSource


class SourceType(Enum):
    """Type of source to scan."""

    FILESYSTEM = "filesystem"  # Default
    GITHUB = "github"
    WEB = "web"  # For future use


def parse_source(source: str) -> tuple[SourceType, str]:
    """Parse source string into type and location."""
    if source.startswith(("github:", "gh:")):
        return SourceType.GITHUB, source.split(":", 1)[1]
    if source.startswith(("http://", "https://")):
        return SourceType.WEB, source
    if "github.com" in source:
        # Handle raw GitHub URLs
        parts = source.split("github.com/", 1)
        if len(parts) == 2:
            return SourceType.GITHUB, parts[1]
    return SourceType.FILESYSTEM, source


def diff_mode_callback(value: str) -> DiffMode:
    """Convert string value to DiffMode enum."""
    try:
        if isinstance(value, DiffMode):
            return value
        return DiffMode(value)
    except ValueError:
        valid_values = [mode.value for mode in DiffMode]
        raise typer.BadParameter(f"Must be one of: {', '.join(valid_values)}")


app = typer.Typer(
    no_args_is_help=True,  # Show help when no args provided
    add_completion=False,  # Disable shell completion for simplicity
)
console = Console()
error_console = Console(stderr=True)


@app.command()
def main(
    paths: list[str] = typer.Argument(
        None,
        help="Paths to process within the source (defaults to current directory)",
    ),
    version: bool = typer.Option(
        None,
        "--version",
        help="Show version and exit.",
        is_eager=True,
    ),
    source: Optional[str] = typer.Option(
        None,
        "--source",
        "-s",
        help="Source to scan (filesystem path, github:owner/repo, or URL)",
    ),
    outfile: Optional[Path] = typer.Option(
        None,
        "--out",
        "-o",
        help="Write output to file",
    ),
    append: bool = typer.Option(
        False,
        "--append",
        "-a",
        help="Append output instead of overwriting",
    ),
    print_output: bool = typer.Option(
        False,
        "--print",
        "-p",
        help="Print output to screen",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed file information in output",
    ),
    include: Optional[str] = typer.Option(
        None,
        "--include",
        "-i",
        help="Extensions to include (comma-separated, e.g. 'py,js,ts')",
    ),
    exclude: Optional[List[str]] = typer.Option(
        None,
        "--exclude",
        "-x",
        help="Glob patterns to exclude",
    ),
    diff_mode: str = typer.Option(
        "full",  # Pass the string value instead of enum
        "--diff-mode",
        help="How to handle git diffs",
        callback=diff_mode_callback,
    ),
    depth: Optional[int] = typer.Option(
        None,
        "--depth",
        "-d",
        help="Maximum directory depth to scan (0 = current dir only)",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Debug mode for development",
    ),
) -> None:
    """Convert source code files to markdown format for LLM context."""
    if version:
        console.print(f"copychat version {get_version('copychat')}")
        raise typer.Exit()

    try:
        # Parse source type and location
        source_type, source_loc = (
            parse_source(source) if source else (SourceType.FILESYSTEM, ".")
        )

        # Handle different source types
        if source_type == SourceType.GITHUB:
            try:
                github_source = GitHubSource(source_loc)
                source_dir = github_source.fetch()
            except Exception as e:
                if debug:
                    raise
                error_console.print(
                    f"[red]Error fetching GitHub repository:[/] {str(e)}"
                )
                raise typer.Exit(1)
        elif source_type == SourceType.WEB:
            error_console.print("[red]Web sources not yet implemented[/]")
            raise typer.Exit(1)
        else:
            source_dir = Path(source_loc)

        # Handle file vs directory source
        if source_dir.is_file():
            content = get_file_content(source_dir, diff_mode)
            all_files = {source_dir: content} if content is not None else {}
        else:
            # For directories, scan all paths
            if not paths:
                paths = ["."]

            # Handle paths
            all_files = {}
            for path in paths:
                target = Path(path)
                if target.is_absolute():
                    # Use absolute paths as-is
                    if target.is_file():
                        content = get_file_content(target, diff_mode)
                        if content is not None:
                            all_files[target] = content
                    else:
                        files = scan_directory(
                            target,
                            include=include.split(",") if include else None,
                            exclude_patterns=exclude,
                            diff_mode=diff_mode,
                            max_depth=depth,
                        )
                        all_files.update(files)
                else:
                    # For relative paths, try both relative to current dir and source dir
                    targets = [Path.cwd() / path]
                    if source_dir != Path("."):
                        targets.append(source_dir / path)

                    for target in targets:
                        if target.exists():
                            if target.is_file():
                                content = get_file_content(target, diff_mode)
                                if content is not None:
                                    all_files[target] = content
                                break
                            else:
                                files = scan_directory(
                                    target,
                                    include=include.split(",") if include else None,
                                    exclude_patterns=exclude,
                                    diff_mode=diff_mode,
                                    max_depth=depth,
                                )
                                all_files.update(files)
                                break
        if not all_files:
            error_console.print("Found [red]0[/] matching files")
            raise typer.Exit(1)  # Exit with code 1 to indicate no files found

        # Format files - pass both paths and content
        format_result = format_files_xml(
            [(path, content) for path, content in all_files.items()]
        )

        # Get the formatted content, conditionally including header
        if verbose:
            result = str(format_result)
            # Print the display header to stderr for visibility
            error_console.print(
                "\nFile summary:",
                style="bold blue",
            )
            # Use the display-friendly header
            error_console.print(create_display_header(format_result))
            error_console.print()  # Add blank line after header
        else:
            # Skip the header by taking only the formatted files
            result = "\n".join(f.formatted_content for f in format_result.files)

        error_console.print(
            f"Found [green]{len(format_result.files)}[/] matching files"
        )

        # Handle outputs
        if outfile:
            if append and outfile.exists():
                existing_content = outfile.read_text()
                result = existing_content + "\n\n" + result
            outfile.write_text(result)
            error_console.print(
                f"Output {'appended' if append else 'written'} to [green]{outfile}[/]"
            )

        # Handle clipboard
        if append:
            try:
                existing_clipboard = pyperclip.paste()
                result = existing_clipboard + "\n\n" + result
            except Exception:
                error_console.print(
                    "[yellow]Warning: Could not read clipboard for append[/]"
                )

        pyperclip.copy(result)
        # Calculate total lines outside the f-string
        total_lines = sum(f.content.count("\n") + 1 for f in format_result.files)
        error_console.print(
            f"{'Appended' if append else 'Copied'} to clipboard "
            f"(~{format_result.total_tokens:,} tokens, {total_lines:,} lines)"
        )

        # Print to stdout only if explicitly requested
        if print_output:
            print(result)

    except Exception as e:
        if debug:
            raise
        error_console.print(f"[red]Error:[/] {str(e)}")
        raise typer.Exit(1)
