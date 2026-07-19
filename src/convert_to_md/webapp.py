from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from convert_to_md import __version__
from convert_to_md.converters import supported_kinds
from convert_to_md.detect import sniff
from convert_to_md.pipeline import UnsupportedFormatError, convert_file

app = FastAPI(title="convert-to-md", version=__version__)

_WEB_DIR = Path(__file__).resolve().parent / "web"
_MAX_FILE_BYTES = 80 * 1024 * 1024
_MAX_BATCH_FILES = 30
_MAX_BATCH_BYTES = 200 * 1024 * 1024

if _WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_WEB_DIR)), name="static")


class _Cleanup:
    def __init__(self, *paths: Path):
        self.paths = paths

    async def __call__(self) -> None:
        for p in self.paths:
            try:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                elif p.exists():
                    p.unlink(missing_ok=True)
            except Exception:
                pass


def _validate_options(pdf_ocr: str, pdf_formula_ocr: str, formula_ocr_engine: str) -> tuple[str, str, str]:
    pdf_ocr = (pdf_ocr or "auto").lower().strip()
    pdf_formula_ocr = (pdf_formula_ocr or "auto").lower().strip()
    formula_ocr_engine = (formula_ocr_engine or "auto").lower().strip()
    for label, val, allowed in (
        ("pdf_ocr", pdf_ocr, {"auto", "off", "force"}),
        ("pdf_formula_ocr", pdf_formula_ocr, {"auto", "off", "force"}),
        ("formula_ocr_engine", formula_ocr_engine, {"auto", "pix2tex", "tesseract"}),
    ):
        if val not in allowed:
            raise HTTPException(status_code=400, detail=f"invalid {label}: {val}")
    return pdf_ocr, pdf_formula_ocr, formula_ocr_engine


def _safe_name(name: str | None) -> str:
    filename = Path(name or "upload.bin").name
    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid filename")
    return filename


def _convert_one(
    src: Path,
    out_dir: Path,
    *,
    pdf_ocr: str,
    pdf_formula_ocr: str,
    formula_ocr_engine: str,
    pdf_page_headings: bool,
    html_keep_infobox: bool,
    use_cache: bool,
) -> dict:
    sn = sniff(src)
    out_md = out_dir / f"{src.name}.md"
    result = convert_file(
        src,
        out_md,
        overwrite=True,
        use_cache=use_cache,
        pdf_ocr=pdf_ocr,
        pdf_formula_ocr=pdf_formula_ocr,
        formula_ocr_engine=formula_ocr_engine,
        pdf_page_headings=pdf_page_headings,
        html_keep_infobox=html_keep_infobox,
    )
    assets = result.with_name(result.stem + "_assets")
    text = result.read_text(encoding="utf-8", errors="replace")
    asset_count = len([p for p in assets.rglob("*") if p.is_file()]) if assets.is_dir() else 0
    return {
        "ok": True,
        "filename": src.name,
        "kind": sn.kind,
        "markdown_name": result.name,
        "markdown_path": result,
        "assets_dir": assets if assets.is_dir() else None,
        "chars": len(text),
        "lines": text.count("\n") + 1,
        "assets": asset_count,
        "preview": text if len(text) <= 8000 else text[:8000] + "\n\n…(preview truncated)…",
        "error": None,
    }


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    index_path = _WEB_DIR / "index.html"
    if not index_path.is_file():
        return HTMLResponse("<h1>convert-to-md web UI missing</h1>", status_code=500)
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict:
    from convert_to_md.formula_ocr import available_formula_engines
    from convert_to_md.ocr import available_engines

    return {
        "ok": True,
        "version": __version__,
        "formats": [{"name": n, "kinds": list(k)} for n, k in supported_kinds()],
        "page_ocr": available_engines(),
        "formula_ocr": available_formula_engines(),
        "limits": {
            "max_file_mb": _MAX_FILE_BYTES // (1024 * 1024),
            "max_batch_files": _MAX_BATCH_FILES,
            "max_batch_mb": _MAX_BATCH_BYTES // (1024 * 1024),
        },
    }


@app.post("/api/convert")
async def api_convert(
    file: UploadFile = File(...),
    pdf_ocr: str = Form("auto"),
    pdf_formula_ocr: str = Form("auto"),
    formula_ocr_engine: str = Form("auto"),
    pdf_page_headings: bool = Form(False),
    html_keep_infobox: bool = Form(False),
    use_cache: bool = Form(False),
):
    pdf_ocr, pdf_formula_ocr, formula_ocr_engine = _validate_options(
        pdf_ocr, pdf_formula_ocr, formula_ocr_engine
    )
    filename = _safe_name(file.filename)
    tmp_root = Path(tempfile.mkdtemp(prefix="convert_to_md_web_"))
    try:
        src = tmp_root / filename
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty file")
        if len(data) > _MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail="file too large (max 80MB)")
        src.write_bytes(data)

        out_dir = tmp_root / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            item = _convert_one(
                src,
                out_dir,
                pdf_ocr=pdf_ocr,
                pdf_formula_ocr=pdf_formula_ocr,
                formula_ocr_engine=formula_ocr_engine,
                pdf_page_headings=pdf_page_headings,
                html_keep_infobox=html_keep_infobox,
                use_cache=use_cache,
            )
        except UnsupportedFormatError as e:
            raise HTTPException(status_code=415, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"conversion failed: {e}") from e

        result: Path = item["markdown_path"]
        assets = item["assets_dir"]
        if assets is not None and any(assets.iterdir()):
            zip_path = tmp_root / f"{src.stem}.zip"
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(result, arcname=result.name)
                for p in assets.rglob("*"):
                    if p.is_file():
                        zf.write(p, arcname=str(Path(assets.name) / p.relative_to(assets)))
            download_name = zip_path.name
            media = "application/zip"
            download_path = zip_path
        else:
            download_name = result.name
            media = "text/markdown; charset=utf-8"
            download_path = result

        final = Path(tempfile.mkstemp(prefix="ctm_", suffix=Path(download_name).suffix)[1])
        shutil.copy2(download_path, final)
        return FileResponse(
            path=str(final),
            media_type=media,
            filename=download_name,
            headers={
                "X-Convert-Kind": str(item["kind"]),
                "X-Output-Name": download_name,
                "X-Convert-Ok": "1",
                "X-Convert-Failed": "0",
            },
            background=_Cleanup(tmp_root, final),
        )
    except HTTPException:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise


@app.post("/api/convert-preview")
async def api_convert_preview(
    file: UploadFile = File(...),
    pdf_ocr: str = Form("auto"),
    pdf_formula_ocr: str = Form("auto"),
    formula_ocr_engine: str = Form("auto"),
    pdf_page_headings: bool = Form(False),
    html_keep_infobox: bool = Form(False),
):
    pdf_ocr, pdf_formula_ocr, formula_ocr_engine = _validate_options(
        pdf_ocr, pdf_formula_ocr, formula_ocr_engine
    )
    filename = _safe_name(file.filename)
    tmp_root = Path(tempfile.mkdtemp(prefix="convert_to_md_prev_"))
    try:
        src = tmp_root / filename
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty file")
        if len(data) > _MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail="file too large (max 80MB)")
        src.write_bytes(data)
        out_dir = tmp_root / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            item = _convert_one(
                src,
                out_dir,
                pdf_ocr=pdf_ocr,
                pdf_formula_ocr=pdf_formula_ocr,
                formula_ocr_engine=formula_ocr_engine,
                pdf_page_headings=pdf_page_headings,
                html_keep_infobox=html_keep_infobox,
                use_cache=False,
            )
        except UnsupportedFormatError as e:
            raise HTTPException(status_code=415, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"conversion failed: {e}") from e

        return JSONResponse(
            {
                "ok": True,
                "kind": item["kind"],
                "filename": item["filename"],
                "markdown_name": item["markdown_name"],
                "chars": item["chars"],
                "lines": item["lines"],
                "assets": item["assets"],
                "preview": item["preview"],
            }
        )
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


@app.post("/api/convert-batch")
async def api_convert_batch(
    files: list[UploadFile] = File(...),
    pdf_ocr: str = Form("auto"),
    pdf_formula_ocr: str = Form("auto"),
    formula_ocr_engine: str = Form("auto"),
    pdf_page_headings: bool = Form(False),
    html_keep_infobox: bool = Form(False),
    use_cache: bool = Form(False),
):
    """Convert multiple files and return a zip package + JSON summary header."""
    pdf_ocr, pdf_formula_ocr, formula_ocr_engine = _validate_options(
        pdf_ocr, pdf_formula_ocr, formula_ocr_engine
    )
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")
    if len(files) > _MAX_BATCH_FILES:
        raise HTTPException(status_code=400, detail=f"too many files (max {_MAX_BATCH_FILES})")

    tmp_root = Path(tempfile.mkdtemp(prefix="convert_to_md_batch_"))
    in_dir = tmp_root / "in"
    out_dir = tmp_root / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    total_bytes = 0
    try:
        for upload in files:
            filename = _safe_name(upload.filename)
            data = await upload.read()
            total_bytes += len(data or b"")
            if total_bytes > _MAX_BATCH_BYTES:
                raise HTTPException(status_code=400, detail="batch too large (max 200MB)")
            if not data:
                results.append(
                    {
                        "ok": False,
                        "filename": filename,
                        "kind": None,
                        "error": "empty file",
                        "markdown_name": None,
                        "chars": 0,
                        "lines": 0,
                        "assets": 0,
                        "preview": "",
                    }
                )
                continue
            if len(data) > _MAX_FILE_BYTES:
                results.append(
                    {
                        "ok": False,
                        "filename": filename,
                        "kind": None,
                        "error": "file too large (max 80MB)",
                        "markdown_name": None,
                        "chars": 0,
                        "lines": 0,
                        "assets": 0,
                        "preview": "",
                    }
                )
                continue

            # avoid overwrite collisions in batch
            src = in_dir / filename
            if src.exists():
                stem, suf = src.stem, src.suffix
                n = 2
                while True:
                    cand = in_dir / f"{stem}_{n}{suf}"
                    if not cand.exists():
                        src = cand
                        break
                    n += 1
            src.write_bytes(data)
            try:
                item = _convert_one(
                    src,
                    out_dir,
                    pdf_ocr=pdf_ocr,
                    pdf_formula_ocr=pdf_formula_ocr,
                    formula_ocr_engine=formula_ocr_engine,
                    pdf_page_headings=pdf_page_headings,
                    html_keep_infobox=html_keep_infobox,
                    use_cache=use_cache,
                )
                results.append(
                    {
                        "ok": True,
                        "filename": item["filename"],
                        "kind": item["kind"],
                        "error": None,
                        "markdown_name": item["markdown_name"],
                        "chars": item["chars"],
                        "lines": item["lines"],
                        "assets": item["assets"],
                        "preview": item["preview"],
                        "_md": item["markdown_path"],
                        "_assets": item["assets_dir"],
                    }
                )
            except UnsupportedFormatError as e:
                results.append(
                    {
                        "ok": False,
                        "filename": src.name,
                        "kind": sniff(src).kind,
                        "error": str(e),
                        "markdown_name": None,
                        "chars": 0,
                        "lines": 0,
                        "assets": 0,
                        "preview": "",
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "ok": False,
                        "filename": src.name,
                        "kind": None,
                        "error": f"conversion failed: {e}",
                        "markdown_name": None,
                        "chars": 0,
                        "lines": 0,
                        "assets": 0,
                        "preview": "",
                    }
                )

        ok_items = [r for r in results if r.get("ok")]
        if not ok_items:
            # still return JSON error summary rather than empty zip
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "all files failed",
                    "results": [
                        {k: v for k, v in r.items() if not str(k).startswith("_")} for r in results
                    ],
                },
            )

        zip_path = tmp_root / "convert_to_md_batch.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # summary
            summary_lines = ["# convert-to-md batch summary", ""]
            for r in results:
                if r["ok"]:
                    summary_lines.append(
                        f"- OK `{r['filename']}` -> `{r['markdown_name']}` "
                        f"(kind={r['kind']}, lines={r['lines']}, assets={r['assets']})"
                    )
                else:
                    summary_lines.append(f"- FAIL `{r['filename']}`: {r['error']}")
            zf.writestr("SUMMARY.md", "\n".join(summary_lines) + "\n")

            for r in ok_items:
                md_path: Path = r["_md"]
                zf.write(md_path, arcname=md_path.name)
                assets = r.get("_assets")
                if assets is not None and Path(assets).is_dir():
                    for p in Path(assets).rglob("*"):
                        if p.is_file():
                            zf.write(
                                p,
                                arcname=str(Path(Path(assets).name) / p.relative_to(assets)),
                            )

        final = Path(tempfile.mkstemp(prefix="ctm_batch_", suffix=".zip")[1])
        shutil.copy2(zip_path, final)
        ok_n = len(ok_items)
        fail_n = len(results) - ok_n
        # public JSON-ish summary without private paths
        public_results = [{k: v for k, v in r.items() if not str(k).startswith("_")} for r in results]
        return FileResponse(
            path=str(final),
            media_type="application/zip",
            filename="convert_to_md_batch.zip",
            headers={
                "X-Output-Name": "convert_to_md_batch.zip",
                "X-Convert-Ok": str(ok_n),
                "X-Convert-Failed": str(fail_n),
                "X-Convert-Total": str(len(results)),
            },
            background=_Cleanup(tmp_root, final),
        )
    except HTTPException:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise
