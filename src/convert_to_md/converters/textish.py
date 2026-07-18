from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path

from convert_to_md.context import ConvertContext
from convert_to_md.converters.base import BaseConverter
from convert_to_md.ir import DocumentIR


class TextConverter(BaseConverter):
    name = "text"
    kinds = ("text",)

    def convert(self, path: Path, ctx: ConvertContext) -> DocumentIR:
        text = _read_text(path)
        doc = DocumentIR(source=path, title=path.stem)
        # already markdown → keep; plain text → paragraph blocks by blank line
        if path.suffix.lower() in {".md", ".markdown"}:
            doc.raw(text.rstrip() + "\n")
            return doc
        chunks = [c.strip() for c in text.split("\n\n")]
        for c in chunks:
            if c:
                doc.paragraph(c)
        return doc


class CsvConverter(BaseConverter):
    name = "csv"
    kinds = ("csv", "tsv")

    def convert(self, path: Path, ctx: ConvertContext) -> DocumentIR:
        text = _read_text(path)
        dialect = "excel-tab" if path.suffix.lower() == ".tsv" or ctx.extra.get("kind") == "tsv" else "excel"
        # sniff kind from path via suffix
        if path.suffix.lower() == ".tsv":
            delimiter = "\t"
        else:
            try:
                dialect_obj = csv.Sniffer().sniff(text[:4096], delimiters=",\t;|")
                delimiter = dialect_obj.delimiter
            except Exception:
                delimiter = ","

        reader = csv.reader(StringIO(text), delimiter=delimiter)
        rows: list[list[str]] = []
        for i, row in enumerate(reader):
            if i >= ctx.max_table_rows:
                break
            rows.append([c.strip() for c in row])
        doc = DocumentIR(source=path, title=path.stem)
        if rows:
            doc.table(rows)
        return doc


class JsonConverter(BaseConverter):
    name = "json"
    kinds = ("json",)

    def convert(self, path: Path, ctx: ConvertContext) -> DocumentIR:
        text = _read_text(path)
        doc = DocumentIR(source=path, title=path.stem)
        try:
            obj = json.loads(text)
            pretty = json.dumps(obj, ensure_ascii=False, indent=2)
            doc.code(pretty, language="json")
        except json.JSONDecodeError:
            doc.code(text, language="json")
        return doc


class XmlConverter(BaseConverter):
    name = "xml"
    kinds = ("xml",)

    def convert(self, path: Path, ctx: ConvertContext) -> DocumentIR:
        text = _read_text(path)
        doc = DocumentIR(source=path, title=path.stem)
        # pretty-ish via lxml if possible
        try:
            from lxml import etree

            parser = etree.XMLParser(remove_blank_text=True, recover=True)
            root = etree.fromstring(text.encode("utf-8"), parser=parser)
            pretty = etree.tostring(root, pretty_print=True, encoding="unicode")
            doc.code(pretty.strip(), language="xml")
        except Exception:
            doc.code(text, language="xml")
        return doc


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    if not data:
        return ""
    from charset_normalizer import from_bytes

    best = from_bytes(data).best()
    if best is not None:
        return str(best)
    return data.decode("utf-8", errors="replace")
