from __future__ import annotations

import io
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
if _WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_WEB_DIR)), name="static")


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

    filename = Path(file.filename or "upload.bin").name
    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid filename")

    tmp_root = Path(tempfile.mkdtemp(prefix="convert_to_md_web_"))
    try:
        src = tmp_root / filename
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty file")
        # soft limit ~80MB
        if len(data) > 80 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="file too large (max 80MB)")
        src.write_bytes(data)

        sn = sniff(src)
        out_md = tmp_root / "out" / f"{src.name}.md"
        out_md.parent.mkdir(parents=True, exist_ok=True)
        try:
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
        except UnsupportedFormatError as e:
            raise HTTPException(status_code=415, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"conversion failed: {e}") from e

        assets = result.with_name(result.stem + "_assets")
        preview = result.read_text(encoding="utf-8", errors="replace")
        if len(preview) > 12000:
            preview = preview[:12000] + "\n\n…(preview truncated)…"

        # package download: md only or zip with assets
        if assets.is_dir() and any(assets.iterdir()):
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

        # move packaged output to a stable temp file that FileResponse can stream,
        # then cleanup the rest after response via background would be nicer;
        # for simplicity, copy to NamedTemporaryFile delete=False and return it.
        final = Path(tempfile.mkstemp(prefix="ctm_", suffix=Path(download_name).suffix)[1])
        shutil.copy2(download_path, final)

        headers = {
            "X-Convert-Kind": sn.kind,
            "X-Output-Name": download_name,
        }
        return FileResponse(
            path=str(final),
            media_type=media,
            filename=download_name,
            headers=headers,
            background=_Cleanup(tmp_root, final),
        )
    except HTTPException:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise


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


@app.post("/api/convert-preview")
async def api_convert_preview(
    file: UploadFile = File(...),
    pdf_ocr: str = Form("auto"),
    pdf_formula_ocr: str = Form("auto"),
    formula_ocr_engine: str = Form("auto"),
    pdf_page_headings: bool = Form(False),
    html_keep_infobox: bool = Form(False),
):
    """Convert and return JSON preview (no file download)."""
    filename = Path(file.filename or "upload.bin").name
    tmp_root = Path(tempfile.mkdtemp(prefix="convert_to_md_prev_"))
    try:
        src = tmp_root / filename
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty file")
        if len(data) > 80 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="file too large (max 80MB)")
        src.write_bytes(data)
        sn = sniff(src)
        out_md = tmp_root / "out" / f"{src.name}.md"
        out_md.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = convert_file(
                src,
                out_md,
                overwrite=True,
                use_cache=False,
                pdf_ocr=(pdf_ocr or "auto").lower(),
                pdf_formula_ocr=(pdf_formula_ocr or "auto").lower(),
                formula_ocr_engine=(formula_ocr_engine or "auto").lower(),
                pdf_page_headings=pdf_page_headings,
                html_keep_infobox=html_keep_infobox,
            )
        except UnsupportedFormatError as e:
            raise HTTPException(status_code=415, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"conversion failed: {e}") from e

        text = result.read_text(encoding="utf-8", errors="replace")
        assets = result.with_name(result.stem + "_assets")
        asset_count = len(list(assets.rglob("*"))) if assets.is_dir() else 0
        preview = text if len(text) <= 20000 else text[:20000] + "\n\n…(preview truncated)…"
        return JSONResponse(
            {
                "ok": True,
                "kind": sn.kind,
                "filename": filename,
                "markdown_name": result.name,
                "chars": len(text),
                "lines": text.count("\n") + 1,
                "assets": asset_count,
                "preview": preview,
            }
        )
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
