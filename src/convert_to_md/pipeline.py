from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from convert_to_md.cache import cache_key, is_fresh, remember
from convert_to_md.context import ConvertContext
from convert_to_md.converters import find_converter
from convert_to_md.detect import sniff
from convert_to_md.ir import DocumentIR
from convert_to_md.naming import default_output_md
from convert_to_md.render import write_markdown


class UnsupportedFormatError(ValueError):
    pass


def convert_file(
    source: Path | str,
    output: Path | str | None = None,
    *,
    assets_dir: Path | str | None = None,
    overwrite: bool = True,
    max_table_rows: int = 5000,
    pdf_max_pages: int | None = None,
    pdf_page_headings: bool = False,
    pdf_ocr: str = "auto",
    pdf_formula_ocr: str = "auto",
    formula_ocr_engine: str = "auto",
    html_keep_infobox: bool = False,
    use_cache: bool = True,
) -> Path:
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Not a file: {source}")

    sn = sniff(source)
    conv = find_converter(source, sn)
    if conv is None:
        raise UnsupportedFormatError(
            f"Unsupported format for {source.name} (kind={sn.kind}, ext={sn.ext}). "
            f"Run `convert-to-md formats` to list supported kinds."
        )

    output_md = _resolve_output_md(source, output)

    if output_md.exists() and not overwrite and not use_cache:
        raise FileExistsError(f"Output exists: {output_md}")

    key = cache_key(
        source,
        converter_name=conv.name,
        max_table_rows=max_table_rows,
        pdf_max_pages=pdf_max_pages,
        pdf_page_headings=pdf_page_headings,
        pdf_ocr=pdf_ocr,
        pdf_formula_ocr=pdf_formula_ocr,
        html_keep_infobox=html_keep_infobox,
    )
    # include formula engine in cache identity via extra hash field through converter name suffix
    # (keeps cache.py signature stable while still invalidating on engine change)
    if formula_ocr_engine and formula_ocr_engine != "auto":
        import hashlib
        import json

        payload = {
            "base": key,
            "formula_ocr_engine": formula_ocr_engine,
        }
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    if use_cache and is_fresh(output_md, key):
        return output_md

    if output_md.exists() and not overwrite:
        raise FileExistsError(f"Output exists: {output_md}")

    assets = (
        Path(assets_dir).expanduser().resolve()
        if assets_dir
        else output_md.with_name(output_md.stem + "_assets")
    )

    ctx = ConvertContext(
        source=source,
        output_md=output_md,
        assets_dir=assets,
        overwrite=overwrite,
        max_table_rows=max_table_rows,
        pdf_max_pages=pdf_max_pages,
        pdf_page_headings=pdf_page_headings,
        pdf_ocr=pdf_ocr,
        pdf_formula_ocr=pdf_formula_ocr,
        formula_ocr_engine=formula_ocr_engine,
        html_keep_infobox=html_keep_infobox,
        extra={"kind": sn.kind},
    )
    ctx.ensure_dirs()

    ir: DocumentIR = conv.convert(source, ctx)
    if ir.source is None:
        ir.source = source
    write_markdown(ir, output_md, assets_dir=assets)
    if use_cache:
        remember(output_md, source, key)
    return output_md


def convert_path(
    source: Path | str,
    output_dir: Path | str | None = None,
    *,
    recursive: bool = False,
    overwrite: bool = True,
    max_table_rows: int = 5000,
    pdf_max_pages: int | None = None,
    pdf_page_headings: bool = False,
    pdf_ocr: str = "auto",
    pdf_formula_ocr: str = "auto",
    formula_ocr_engine: str = "auto",
    html_keep_infobox: bool = False,
    use_cache: bool = True,
    workers: int = 1,
    on_item=None,
) -> list[Path]:
    source = Path(source).expanduser().resolve()
    common = dict(
        overwrite=overwrite,
        max_table_rows=max_table_rows,
        pdf_max_pages=pdf_max_pages,
        pdf_page_headings=pdf_page_headings,
        pdf_ocr=pdf_ocr,
        pdf_formula_ocr=pdf_formula_ocr,
        formula_ocr_engine=formula_ocr_engine,
        html_keep_infobox=html_keep_infobox,
        use_cache=use_cache,
    )

    if source.is_file():
        out = None if output_dir is None else Path(output_dir)
        result = convert_file(source, out, **common)
        if on_item is not None:
            on_item(source, result, True, None)
        return [result]

    if not source.is_dir():
        raise FileNotFoundError(f"Path not found: {source}")

    out_root = Path(output_dir).expanduser().resolve() if output_dir else source
    pattern_iter = source.rglob("*") if recursive else source.glob("*")
    files = sorted(p for p in pattern_iter if p.is_file() and not p.name.startswith("."))

    jobs: list[tuple[Path, Path]] = []
    for f in files:
        sn = sniff(f)
        if find_converter(f, sn) is None:
            continue
        rel = f.relative_to(source)
        target_dir = out_root / rel.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        jobs.append((f, default_output_md(f, target_dir)))

    if not jobs:
        return []

    workers = max(1, int(workers or 1))
    results: list[Path] = []

    def run_one(pair: tuple[Path, Path]):
        f, dest = pair
        try:
            out = convert_file(f, dest, **common)
            return f, out, None
        except Exception as e:  # noqa: BLE001 - surface to caller/on_item
            return f, None, e

    if workers == 1:
        for pair in jobs:
            f, out, err = run_one(pair)
            if err is None and out is not None:
                results.append(out)
                if on_item is not None:
                    on_item(f, out, True, None)
            elif on_item is not None:
                on_item(f, None, False, err)
            elif err is not None and not isinstance(err, UnsupportedFormatError):
                raise err
        return results

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_one, pair) for pair in jobs]
        for fut in as_completed(futures):
            f, out, err = fut.result()
            if err is None and out is not None:
                results.append(out)
                if on_item is not None:
                    on_item(f, out, True, None)
            elif on_item is not None:
                on_item(f, None, False, err)
            elif err is not None and not isinstance(err, UnsupportedFormatError):
                raise err
    return results


def _resolve_output_md(source: Path, output: Path | str | None) -> Path:
    if output is None:
        return default_output_md(source)

    output = Path(output).expanduser()
    suffix = output.suffix.lower()

    if suffix == ".md":
        return output.resolve()

    if output.exists() and output.is_dir():
        return default_output_md(source, output.resolve())

    if suffix == "" or str(output).endswith(("/", "\\")):
        output.mkdir(parents=True, exist_ok=True)
        return default_output_md(source, output.resolve())

    output.mkdir(parents=True, exist_ok=True)
    return default_output_md(source, output.resolve())
