from __future__ import annotations

from convert_to_md.converters.base import BaseConverter, Converter
from convert_to_md.converters.docx import DocxConverter
from convert_to_md.converters.epub import EpubConverter
from convert_to_md.converters.html import HtmlConverter
from convert_to_md.converters.image import ImageConverter
from convert_to_md.converters.pdf import PdfDigitalConverter
from convert_to_md.converters.pptx import PptxConverter
from convert_to_md.converters.textish import (
    CsvConverter,
    JsonConverter,
    TextConverter,
    XmlConverter,
)
from convert_to_md.converters.xlsx import XlsxConverter

_REGISTRY: list[BaseConverter] | None = None


def get_converters() -> list[BaseConverter]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = [
            DocxConverter(),
            PptxConverter(),
            XlsxConverter(),
            HtmlConverter(),
            TextConverter(),
            CsvConverter(),
            JsonConverter(),
            XmlConverter(),
            EpubConverter(),
            PdfDigitalConverter(),
            ImageConverter(),
        ]
    return _REGISTRY


def find_converter(path, sniff):
    for conv in get_converters():
        if conv.can_handle(path, sniff):
            return conv
    return None


def supported_kinds() -> list[tuple[str, tuple[str, ...]]]:
    return [(c.name, c.kinds) for c in get_converters()]


__all__ = [
    "BaseConverter",
    "Converter",
    "get_converters",
    "find_converter",
    "supported_kinds",
]
