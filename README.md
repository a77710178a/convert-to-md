# convert-to-md

Local multi-format → Markdown converter for the AI era.  
**Rule-based first** — no LLM on the hot path.

## Install

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -e .

# optional OCR for scans / images (needs Tesseract on PATH)
pip install -e ".[ocr,dev]"

# optional specialized formula OCR (heavier: torch + pix2tex)
pip install -e ".[formula]"

# optional local web UI
pip install -e ".[web]"

# everything
pip install -e ".[all,dev]"
```

## Usage

```bash
convert-to-md file.docx
convert-to-md docs/ -o out/ -r
convert-to-md docs/ -o out/ -j 4
convert-to-md scan.pdf --pdf-ocr force
convert-to-md paper.pdf --pdf-formula-ocr force
convert-to-md formula.png --formula-ocr-engine pix2tex
convert-to-md page.html --html-keep-infobox
convert-to-md formats

# local web UI (browser; multi-file batch + progress)
convert-to-md serve
# opens http://127.0.0.1:8765/
# convert-to-md serve --no-open
```

### Config file (optional)

Create `convert-to-md.toml` in the project directory (see `convert-to-md.example.toml`):

```toml
[convert-to-md]
workers = 4
pdf_ocr = "auto"
pdf_formula_ocr = "auto"
formula_ocr_engine = "auto"   # auto | pix2tex | tesseract
use_cache = true
```

Environment variables also work, e.g. `CONVERT_TO_MD_WORKERS=4`.  
**CLI flags always override config/env.**

### Output naming

| input | output |
|-------|--------|
| `report.docx` | `report.docx.md` |
| `report.pdf` | `report.pdf.md` |
| `photo.png` | `photo.png.md` + assets |

## Formats

| Kind | Notes |
|------|--------|
| docx / pptx / xlsx | office text + tables + images; **docx OMML → LaTeX** |
| html | chrome stripped; **MathML / MathJax / `$...$` → LaTeX** |
| txt / md / csv / tsv / json / xml | text family |
| epub | chapters; Gutenberg boilerplate filtered |
| pdf | digital text; unicode formulas; full-page OCR; **formula-region OCR** |
| png / jpg / webp / tif / bmp / gif | OCR / formula OCR via Tesseract or pix2tex |

### Formulas

Preferred output is GitHub-friendly LaTeX (`$...$` / `$$...$$`).

| Source | How |
|--------|-----|
| HTML MathML + TeX annotation | best (Wikipedia, ar5iv) |
| MathJax / `$...$` / `\( \)` | normalized |
| Multi-line aligned/array/matrix | pretty-printed |
| DOCX OMML | fractions, scripts, n-ary, matrices |
| PDF formula images | crop + **pix2tex** (preferred) or Tesseract |
| PDF text layer | heuristic |
| Equation numbers `(1.1)` | attached under display formulas when present |

```bash
# prefer specialized formula model when installed
convert-to-md eq.png --formula-ocr-engine pix2tex
convert-to-md paper.pdf --pdf-formula-ocr force --formula-ocr-engine auto
```

> **Note on pix2tex:** package may install fine, but first run downloads model weights and needs network access. If weight download fails, the tool automatically falls back to Tesseract.

## Architecture

```text
detect → converter plugin → DocumentIR → GFM markdown + assets/
```

- Content-hash cache
- Parallel directory convert (`-j`)
- Optional page OCR + formula OCR backends
- Optional TOML config

## Samples

```bash
convert-to-md samples/raw -o samples/out -j 4 --no-cache
```

## Install from GitHub

```bash
pip install "git+https://github.com/a77710178a/convert-to-md.git"
pip install "convert-to-md[web,ocr] @ git+https://github.com/a77710178a/convert-to-md.git"
```

See `PUBLISH.md` for PyPI build/upload steps.

## Version

0.6.2
