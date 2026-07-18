from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    CODE = "code"
    IMAGE = "image"
    FORMULA = "formula"
    THEMATIC_BREAK = "thematic_break"
    RAW = "raw"  # already markdown-ish text


@dataclass
class ImageAsset:
    """In-memory image extracted from a source document."""

    data: bytes
    filename: str  # preferred name, e.g. image1.png
    alt: str = ""
    content_type: str | None = None


@dataclass
class Block:
    type: BlockType
    text: str = ""
    level: int = 1  # heading level 1-6
    ordered: bool = False  # for lists
    items: list[str] = field(default_factory=list)  # list items
    rows: list[list[str]] = field(default_factory=list)  # table rows
    language: str = ""  # code fence language
    display: bool = False  # formulas: block vs inline
    asset: ImageAsset | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentIR:
    title: str | None = None
    source: Path | None = None
    blocks: list[Block] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, block: Block) -> None:
        self.blocks.append(block)

    def heading(self, text: str, level: int = 1) -> None:
        self.add(Block(type=BlockType.HEADING, text=text.strip(), level=max(1, min(level, 6))))

    def paragraph(self, text: str) -> None:
        t = text.strip()
        if t:
            self.add(Block(type=BlockType.PARAGRAPH, text=t))

    def list_items(self, items: list[str], ordered: bool = False) -> None:
        cleaned = [i.strip() for i in items if i and i.strip()]
        if cleaned:
            self.add(Block(type=BlockType.LIST, items=cleaned, ordered=ordered))

    def table(self, rows: list[list[str]]) -> None:
        if rows:
            self.add(Block(type=BlockType.TABLE, rows=rows))

    def code(self, text: str, language: str = "") -> None:
        self.add(Block(type=BlockType.CODE, text=text, language=language))

    def image(self, asset: ImageAsset) -> None:
        self.add(Block(type=BlockType.IMAGE, asset=asset, text=asset.alt))

    def formula(self, latex: str, *, display: bool = False, number: str | None = None) -> None:
        t = (latex or "").strip()
        if t:
            meta: dict[str, Any] = {}
            if number:
                meta["number"] = str(number).strip()
            self.add(Block(type=BlockType.FORMULA, text=t, display=display, meta=meta))

    def hr(self) -> None:
        self.add(Block(type=BlockType.THEMATIC_BREAK))

    def raw(self, text: str) -> None:
        if text:
            self.add(Block(type=BlockType.RAW, text=text))
