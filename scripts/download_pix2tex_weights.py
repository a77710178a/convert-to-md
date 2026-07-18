"""Download pix2tex model weights into the package checkpoint directory.

Usage:
  python scripts/download_pix2tex_weights.py
"""

from __future__ import annotations

import sys
from pathlib import Path


TAG = "v0.0.1"
FILES = {
    "weights.pth": f"https://github.com/lukas-blecher/LaTeX-OCR/releases/download/{TAG}/weights.pth",
    "image_resizer.pth": f"https://github.com/lukas-blecher/LaTeX-OCR/releases/download/{TAG}/image_resizer.pth",
}


def checkpoint_dir() -> Path:
    import pix2tex

    return Path(pix2tex.__file__).resolve().parent / "model" / "checkpoints"


def download(url: str, dest: Path) -> None:
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"GET {url}")
    print(f" -> {dest}")
    req = urllib.request.Request(url, headers={"User-Agent": "convert-to-md-weight-downloader/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                pct = 100.0 * done / total
                print(f"\r  {done/1e6:.1f}/{total/1e6:.1f} MB ({pct:.1f}%)", end="", flush=True)
        print()
    tmp.replace(dest)


def main() -> int:
    try:
        ckpt = checkpoint_dir()
    except Exception as e:
        print(f"pix2tex not importable: {e}")
        print('Install with: pip install -e ".[formula]"')
        return 1

    print("checkpoint dir:", ckpt)
    ok = True
    for name, url in FILES.items():
        dest = ckpt / name
        if dest.exists() and dest.stat().st_size > 1_000_000:
            print(f"skip existing {name} ({dest.stat().st_size} bytes)")
            continue
        try:
            download(url, dest)
        except Exception as e:
            ok = False
            print(f"FAILED {name}: {e}")
    if not ok:
        return 2
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
