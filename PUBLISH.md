# Publish to PyPI (when ready)

This package is already installable from GitHub:

```bash
pip install "git+https://github.com/a77710178a/convert-to-md.git"
# or with extras
pip install "convert-to-md[web,ocr] @ git+https://github.com/a77710178a/convert-to-md.git"
```

## What you need

1. PyPI account: https://pypi.org/account/register/
2. API token: https://pypi.org/manage/account/token/
3. Local build tools:

```bash
python -m pip install -U build twine
```

## Build

```bash
cd E:/Project/paper_guide/sim_proj/convert_to_md
source .venv/Scripts/activate
python -m build
python -m twine check dist/*
```

## Upload

### TestPyPI first (recommended)

```bash
python -m twine upload --repository testpypi dist/*
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple convert-to-md
```

### Production PyPI

```bash
python -m twine upload dist/*
```

When prompted:
- username: `__token__`
- password: paste your PyPI API token (`pypi-...`)

Or use environment variables:

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-xxxxxxxx
python -m twine upload dist/*
```

Then users can:

```bash
pip install convert-to-md
pip install "convert-to-md[web,ocr]"
convert-to-md serve
```

## Notes

- Optional extras: `ocr`, `formula`, `web`, `all`, `dev`
- Keep version in both `pyproject.toml` and `src/convert_to_md/__init__.py` in sync
- Prefer GitHub release tags matching versions (`v0.6.2`)
- Do **not** commit PyPI tokens
