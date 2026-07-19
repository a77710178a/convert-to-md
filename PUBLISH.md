# Publish to PyPI (when ready)

This package is already installable from GitHub:

```bash
pip install "git+https://github.com/a77710178a/convert-to-md.git"
# or with extras
pip install "convert-to-md[web,ocr] @ git+https://github.com/a77710178a/convert-to-md.git"
```

## Build locally

```bash
python -m pip install -U build twine
python -m build
# creates dist/*.whl and dist/*.tar.gz
python -m twine check dist/*
```

## Test upload (TestPyPI)

```bash
python -m twine upload --repository testpypi dist/*
pip install -i https://test.pypi.org/simple/ convert-to-md
```

## Production upload (PyPI)

1. Create an account at https://pypi.org
2. Create an API token
3. Upload:

```bash
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
- Prefer GitHub release tags matching versions (`v0.6.1`)
