from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from convert_to_md import __version__
from convert_to_md.config import load_config
from convert_to_md.converters import supported_kinds
from convert_to_md.pipeline import UnsupportedFormatError, convert_file, convert_path

console = Console(stderr=True)

app = typer.Typer(
    name="convert-to-md",
    help="Convert common document formats to Markdown (no LLM required).",
    add_completion=False,
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"convert-to-md {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Local multi-format → Markdown converter."""


@app.command("convert")
def convert_cmd(
    source: Path = typer.Argument(..., exists=True, help="File or directory to convert."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output .md file or directory."),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Recurse into directories."),
    overwrite: bool = typer.Option(True, "--overwrite/--no-overwrite", help="Overwrite existing .md."),
    max_table_rows: Optional[int] = typer.Option(None, "--max-table-rows", help="Cap rows per table."),
    pdf_max_pages: Optional[int] = typer.Option(None, "--pdf-max-pages", help="Limit PDF pages."),
    pdf_page_headings: Optional[bool] = typer.Option(
        None,
        "--pdf-page-headings/--no-pdf-page-headings",
        help="Insert '## Page N' separators for multi-page PDFs.",
    ),
    pdf_ocr: Optional[str] = typer.Option(
        None,
        "--pdf-ocr",
        help="Full-page OCR for scanned PDFs: auto | off | force.",
    ),
    pdf_formula_ocr: Optional[str] = typer.Option(
        None,
        "--pdf-formula-ocr",
        help="OCR formula-like PDF image regions: auto | off | force.",
    ),
    formula_ocr_engine: Optional[str] = typer.Option(
        None,
        "--formula-ocr-engine",
        help="Formula OCR backend: auto | pix2tex | tesseract.",
    ),
    html_keep_infobox: Optional[bool] = typer.Option(
        None,
        "--html-keep-infobox/--html-drop-infobox",
        help="Keep Wikipedia-style infobox tables in HTML output.",
    ),
    workers: Optional[int] = typer.Option(None, "--workers", "-j", help="Parallel workers for directory batch."),
    cache: Optional[bool] = typer.Option(None, "--cache/--no-cache", help="Skip unchanged files via content hash."),
) -> None:
    """Convert a file or directory to Markdown."""
    cfg = load_config()

    max_table_rows = cfg.max_table_rows if max_table_rows is None else max_table_rows
    pdf_page_headings = cfg.pdf_page_headings if pdf_page_headings is None else pdf_page_headings
    pdf_ocr = (cfg.pdf_ocr if pdf_ocr is None else pdf_ocr).lower().strip()
    pdf_formula_ocr = (cfg.pdf_formula_ocr if pdf_formula_ocr is None else pdf_formula_ocr).lower().strip()
    formula_ocr_engine = (
        cfg.formula_ocr_engine if formula_ocr_engine is None else formula_ocr_engine
    ).lower().strip()
    html_keep_infobox = cfg.html_keep_infobox if html_keep_infobox is None else html_keep_infobox
    workers = cfg.workers if workers is None else workers
    cache = cfg.use_cache if cache is None else cache
    if pdf_max_pages is None:
        pdf_max_pages = cfg.pdf_max_pages

    if pdf_ocr not in {"auto", "off", "force"}:
        console.print("[red]Error:[/red] --pdf-ocr must be one of: auto, off, force")
        raise typer.Exit(code=2)
    if pdf_formula_ocr not in {"auto", "off", "force"}:
        console.print("[red]Error:[/red] --pdf-formula-ocr must be one of: auto, off, force")
        raise typer.Exit(code=2)
    if formula_ocr_engine not in {"auto", "pix2tex", "tesseract"}:
        console.print("[red]Error:[/red] --formula-ocr-engine must be one of: auto, pix2tex, tesseract")
        raise typer.Exit(code=2)
    if workers < 1:
        console.print("[red]Error:[/red] --workers must be >= 1")
        raise typer.Exit(code=2)

    opts = dict(
        overwrite=overwrite,
        max_table_rows=max_table_rows,
        pdf_max_pages=pdf_max_pages,
        pdf_page_headings=pdf_page_headings,
        pdf_ocr=pdf_ocr,
        pdf_formula_ocr=pdf_formula_ocr,
        formula_ocr_engine=formula_ocr_engine,
        html_keep_infobox=html_keep_infobox,
        use_cache=cache,
    )

    try:
        source = source.expanduser().resolve()
        if source.is_dir():
            from convert_to_md.converters import find_converter
            from convert_to_md.detect import sniff

            pattern = source.rglob("*") if recursive else source.glob("*")
            files = [p.resolve() for p in pattern if p.is_file() and not p.name.startswith(".")]
            supported = [p for p in files if find_converter(p, sniff(p)) is not None]
            if not supported:
                console.print("[yellow]No supported files found.[/yellow]")
                raise typer.Exit(code=1)

            out_root = Path(output).expanduser().resolve() if output else source
            ok = 0
            failed = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Converting", total=len(supported))

                def on_item(src, out, success, err):
                    nonlocal ok, failed
                    progress.advance(task)
                    if success:
                        ok += 1
                        console.print(f"[green]OK[/green] {Path(src).name} -> {Path(out).name}")
                    else:
                        failed += 1
                        console.print(f"[red]FAIL[/red] {Path(src).name}: {err}")

                convert_path(
                    source,
                    out_root,
                    recursive=recursive,
                    workers=workers,
                    on_item=on_item,
                    **opts,
                )

            console.print(f"Done. ok={ok} failed={failed} workers={workers}")
            if failed and ok == 0:
                raise typer.Exit(code=1)
        else:
            out = convert_file(source, output, **opts)
            console.print(f"[green]OK[/green] {out}")
    except UnsupportedFormatError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=2)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command("formats")
def formats_cmd() -> None:
    """List supported format kinds and OCR engines."""
    table = Table(title="Supported formats")
    table.add_column("Converter")
    table.add_column("Kinds")
    for name, kinds in supported_kinds():
        table.add_row(name, ", ".join(kinds))
    console.print(table)

    from convert_to_md.formula_ocr import available_formula_engines
    from convert_to_md.ocr import available_engines

    page_engines = available_engines()
    formula_engines = available_formula_engines()
    console.print(
        "Page OCR engines: "
        + (", ".join(page_engines) if page_engines else "none (install optional ocr extra + Tesseract)")
    )
    console.print(
        "Formula OCR engines: "
        + (
            ", ".join(formula_engines)
            if formula_engines
            else "none (install optional formula/ocr extras)"
        )
    )


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
    port: int = typer.Option(8765, "--port", "-p", help="Bind port."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload (dev only)."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser automatically."),
) -> None:
    """Start local web UI (requires optional web extra)."""
    try:
        import uvicorn
    except ImportError as e:
        console.print(
            "[red]Web UI dependencies missing.[/red] Install with: "
            "[bold]pip install -e \".[web]\"[/bold]"
        )
        raise typer.Exit(code=1) from e

    bind_host = "127.0.0.1" if host == "0.0.0.0" else host
    chosen = _pick_port(bind_host, port)
    if chosen != port:
        console.print(f"[yellow]Port {port} is busy, using {chosen} instead.[/yellow]")
    url = f"http://{('127.0.0.1' if host == '0.0.0.0' else host)}:{chosen}/"
    console.print(f"[green]convert-to-md web UI[/green]  {url}")
    console.print("Drag & drop files, preview, batch convert with progress. Ctrl+C to stop.")
    if open_browser and host in {"127.0.0.1", "localhost", "0.0.0.0"}:
        import threading
        import time
        import webbrowser

        def _open() -> None:
            time.sleep(0.8)
            try:
                webbrowser.open(url)
            except Exception:
                pass

        threading.Thread(target=_open, daemon=True).start()
    uvicorn.run("convert_to_md.webapp:app", host=host, port=chosen, reload=reload)


@app.command("doctor")
def doctor_cmd() -> None:
    """Show environment/diagnostics for convert-to-md."""
    import importlib.util
    import platform
    import shutil
    import sys as _sys

    from convert_to_md.converters import supported_kinds
    from convert_to_md.formula_ocr import available_formula_engines
    from convert_to_md.ocr import available_engines

    console.print(f"[bold]convert-to-md[/bold] {__version__}")
    console.print(f"Python: {_sys.version.split()[0]} ({platform.system()} {platform.machine()})")
    console.print(f"Executable: {_sys.executable}")

    table = Table(title="Optional components")
    table.add_column("Component")
    table.add_column("Status")
    checks = [
        ("fastapi", "web UI"),
        ("uvicorn", "web server"),
        ("pytesseract", "page/image OCR"),
        ("PIL", "image support"),
        ("pix2tex", "formula OCR model"),
        ("torch", "formula OCR backend"),
    ]
    for mod, label in checks:
        ok = importlib.util.find_spec(mod if mod != "PIL" else "PIL") is not None
        table.add_row(f"{label} ({mod})", "[green]installed[/green]" if ok else "[yellow]missing[/yellow]")
    console.print(table)

    tess = shutil.which("tesseract")
    console.print(f"Tesseract binary: {tess or 'not found on PATH'}")
    console.print("Page OCR engines: " + (", ".join(available_engines()) or "none"))
    console.print("Formula OCR engines: " + (", ".join(available_formula_engines()) or "none"))
    kinds = ", ".join(sorted({k for _, ks in supported_kinds() for k in ks}))
    console.print(f"Supported kinds: {kinds}")
    console.print("Tip: install extras with [bold]pip install -e \".[web,ocr]\"[/bold]")


def _pick_port(host: str, preferred: int) -> int:
    import socket

    def _can_bind(p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, p))
                return True
            except OSError:
                return False

    if _can_bind(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


_COMMANDS = {"convert", "formats", "serve", "doctor"}
_ROOT_FLAGS = {"-h", "--help", "-V", "--version"}


def main() -> None:
    """Entry point: allow `convert-to-md file.docx` as sugar for `convert-to-md convert file.docx`."""
    if len(sys.argv) > 1:
        first = sys.argv[1]
        if first not in _COMMANDS and first not in _ROOT_FLAGS and not first.startswith("-"):
            sys.argv.insert(1, "convert")
    app()


if __name__ == "__main__":
    main()
