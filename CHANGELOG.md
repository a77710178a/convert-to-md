# Changelog

## 0.6.2

- Web batch jobs with progress polling (`/api/jobs`, `/api/jobs/{id}`, download)
- Browser UI progress bar for multi-file conversion
- MIT LICENSE
- PyPI packaging docs (`PUBLISH.md`), build/twine check verified

## 0.6.1

- Multi-file web batch convert (`/api/convert-batch`) with zip + SUMMARY.md
- Formula OCR latex post-processing
- Richer package metadata and GitHub install docs

## 0.6.0

- Local FastAPI web UI (`convert-to-md serve`)
- Single-file preview and download endpoints
- Optional `[web]` extra

## 0.5.x

- Formula extraction (HTML MathML/MathJax, DOCX OMML)
- Equation numbers
- Tesseract page OCR + optional pix2tex formula OCR
- Cache, parallel batch CLI, config file support
