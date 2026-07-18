from __future__ import annotations

import re
from pathlib import Path

from convert_to_md.ir import Block, BlockType, DocumentIR, ImageAsset


def render_markdown(doc: DocumentIR, assets_dir: Path, assets_rel: str = "assets") -> str:
    """Render DocumentIR to GFM markdown. Images written under assets_dir."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    skip_first_heading = False
    if doc.title:
        lines.append(f"# {_escape_inline(doc.title)}")
        lines.append("")
        # avoid "# Title" then another identical h1
        if doc.blocks:
            first = doc.blocks[0]
            if (
                first.type == BlockType.HEADING
                and first.level == 1
                and _norm(first.text) == _norm(doc.title)
            ):
                skip_first_heading = True

    image_index = 0
    for idx, block in enumerate(doc.blocks):
        if skip_first_heading and idx == 0:
            continue
        chunk = _render_block(block, assets_dir, assets_rel, image_index)
        if block.type == BlockType.IMAGE and block.asset is not None:
            image_index += 1
        if chunk is None:
            continue
        # rewrite raw markdown image links that already point into assets_rel after epub rewrite
        lines.append(chunk)
        lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def write_markdown(doc: DocumentIR, output_md: Path, assets_dir: Path | None = None) -> Path:
    assets_dir = assets_dir or output_md.with_name(output_md.stem + "_assets")
    if assets_dir.parent == output_md.parent:
        assets_rel = assets_dir.name
    else:
        try:
            assets_rel = str(assets_dir.relative_to(output_md.parent)).replace("\\", "/")
        except ValueError:
            assets_rel = assets_dir.name

    md = render_markdown(doc, assets_dir=assets_dir, assets_rel=assets_rel)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(md, encoding="utf-8")

    if assets_dir.exists() and not any(assets_dir.iterdir()):
        try:
            assets_dir.rmdir()
        except OSError:
            pass
    return output_md


def _render_block(block: Block, assets_dir: Path, assets_rel: str, image_index: int) -> str | None:
    t = block.type
    if t == BlockType.HEADING:
        level = max(1, min(block.level, 6))
        return f"{'#' * level} {_escape_inline(block.text)}"
    if t == BlockType.PARAGRAPH:
        return _escape_inline(block.text)
    if t == BlockType.LIST:
        out = []
        for i, item in enumerate(block.items, start=1):
            prefix = f"{i}." if block.ordered else "-"
            out.append(f"{prefix} {_escape_inline(item)}")
        return "\n".join(out)
    if t == BlockType.TABLE:
        return _render_table(block.rows)
    if t == BlockType.CODE:
        lang = block.language or ""
        body = block.text.rstrip("\n")
        return f"```{lang}\n{body}\n```"
    if t == BlockType.IMAGE:
        return _write_image(block.asset, assets_dir, assets_rel, image_index, block.text)
    if t == BlockType.FORMULA:
        from convert_to_md.mathutil import latex_to_markdown

        md = latex_to_markdown(block.text, display=block.display)
        number = (block.meta or {}).get("number")
        if number and block.display:
            num = str(number).strip()
            if num and not (num.startswith("(") and num.endswith(")")):
                num = f"({num})"
            return f"{md}\n\n*{num}*"
        return md
    if t == BlockType.THEMATIC_BREAK:
        return "---"
    if t == BlockType.RAW:
        return block.text.rstrip()
    return None


def _write_image(
    asset: ImageAsset | None,
    assets_dir: Path,
    assets_rel: str,
    image_index: int,
    alt: str,
) -> str | None:
    if asset is None or not asset.data:
        return None
    name = asset.filename or f"image_{image_index + 1}.bin"
    name = _safe_filename(name)
    target = assets_dir / name
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        target = assets_dir / f"{stem}_{image_index + 1}{suffix}"
        name = target.name
    assets_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(asset.data)
    alt_text = _escape_inline(alt or asset.alt or name)
    rel = f"{assets_rel}/{name}".replace("\\", "/")
    return f"![{alt_text}]({rel})"


def _render_table(rows: list[list[str]]) -> str | None:
    if not rows:
        return None
    width = max(len(r) for r in rows)
    norm = [list(r) + [""] * (width - len(r)) for r in rows]
    norm = [[_cell(c) for c in r] for r in norm]
    header = norm[0]
    body = norm[1:] if len(norm) > 1 else []
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _cell(value: str) -> str:
    return (value or "").replace("\n", " ").replace("|", "\\|").strip()


def _escape_inline(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _safe_filename(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)
    return name or "asset.bin"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()
