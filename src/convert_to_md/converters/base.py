from __future__ import annotations

from pathlib import Path
from typing import Protocol

from convert_to_md.context import ConvertContext
from convert_to_md.detect import SniffResult
from convert_to_md.ir import DocumentIR


class Converter(Protocol):
    name: str
    kinds: tuple[str, ...]

    def can_handle(self, path: Path, sniff: SniffResult) -> bool: ...

    def convert(self, path: Path, ctx: ConvertContext) -> DocumentIR: ...


class BaseConverter:
    name: str = "base"
    kinds: tuple[str, ...] = ()

    def can_handle(self, path: Path, sniff: SniffResult) -> bool:
        return sniff.kind in self.kinds

    def convert(self, path: Path, ctx: ConvertContext) -> DocumentIR:  # pragma: no cover
        raise NotImplementedError
