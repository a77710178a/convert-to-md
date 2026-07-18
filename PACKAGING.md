# Packaging / release notes for convert-to-md

## Local install

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -e ".[dev,ocr]"
# optional specialized formula OCR:
# pip install -e ".[formula]"
```

## Optional extras

| extra | packages | purpose |
|-------|----------|---------|
| `ocr` | pytesseract, pillow | page / image OCR (needs system Tesseract) |
| `formula` | pix2tex, torch, pillow | specialized formula → LaTeX |
| `all` | ocr + formula | full optional stack |
| `dev` | pytest | tests |

## Config

Copy `convert-to-md.example.toml` to `convert-to-md.toml` in your project root.

## Build a wheel / sdist

```bash
pip install build
python -m build
# outputs under dist/
```

## pix2tex weights

`pix2tex` package install is not enough; first run downloads model weights.

```bash
pip install -e ".[formula]"
python scripts/download_pix2tex_weights.py
convert-to-md formats   # should list pix2tex under Formula OCR engines
```

If weight download fails due to network, conversion automatically falls back to Tesseract.

## Smoke checklist before release

```bash
pytest -q
convert-to-md --version
convert-to-md formats
convert-to-md samples/raw/formulas.html -o samples/out --no-cache
convert-to-md samples/raw/formula_image.pdf -o samples/out --pdf-formula-ocr force --no-cache
```

## CLI entrypoint

```toml
[project.scripts]
convert-to-md = "convert_to_md.cli:main"
```