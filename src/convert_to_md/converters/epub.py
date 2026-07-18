from __future__ import annotations

import re
import warnings
from pathlib import Path
from urllib.parse import unquote

from convert_to_md.context import ConvertContext
from convert_to_md.converters.base import BaseConverter
from convert_to_md.ir import DocumentIR

_PG_START = re.compile(
    r"(?is)^\s*\*{0,3}\s*START OF (THE |THIS )?(PROJECT GUTENBERG|GUTENBERG).*?\*{0,3}\s*"
)
_PG_END = re.compile(
    r"(?is)\s*\*{0,3}\s*END OF (THE |THIS )?(PROJECT GUTENBERG|GUTENBERG).*$"
)
_PG_LICENSE_HEAD = re.compile(
    r"(?is)this ebook is for the use of anyone anywhere.*?(?=\n#|\n\*\*|chapter|\Z)"
)
_FRONT_META_LINES = re.compile(
    r"(?im)^(\*\*)?(Title|Author|Release date|Language|Credits|Other information and formats)\*\*?:"
)


class EpubConverter(BaseConverter):
    name = "epub"
    kinds = ("epub",)

    def convert(self, path: Path, ctx: ConvertContext) -> DocumentIR:
        import ebooklib
        from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
        from ebooklib import epub
        from markdownify import markdownify as md

        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

        book = epub.read_epub(str(path))
        title = path.stem
        try:
            t = book.get_metadata("DC", "title")
            if t:
                title = t[0][0]
        except Exception:
            pass

        doc = DocumentIR(source=path, title=title)
        ctx.assets_dir.mkdir(parents=True, exist_ok=True)

        image_map: dict[str, str] = {}
        image_i = 0
        for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
            image_i += 1
            raw_name = Path(item.get_name()).name or f"image_{image_i}"
            safe = _safe_name(raw_name)
            if not Path(safe).suffix:
                ext = _ext_from_media(item.media_type) or ".img"
                safe = f"{safe}{ext}"
            target = ctx.assets_dir / safe
            if target.exists():
                target = ctx.assets_dir / f"{target.stem}_{image_i}{target.suffix}"
                safe = target.name
            try:
                target.write_bytes(item.get_content())
            except Exception:
                continue
            rel = f"{ctx.assets_dir.name}/{safe}".replace("\\", "/")
            image_map[raw_name] = rel
            image_map[item.get_name()] = rel
            image_map[Path(item.get_name()).as_posix()] = rel

        items = []
        spine_ids = [s[0] for s in book.spine]
        id_map = {
            item.get_id(): item
            for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_DOCUMENT
        }
        for sid in spine_ids:
            if sid in id_map:
                items.append(id_map[sid])
        if not items:
            items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))

        for item in items:
            try:
                html = item.get_content().decode("utf-8", errors="replace")
            except Exception:
                continue

            soup = BeautifulSoup(html, "lxml")
            for img in soup.find_all("img"):
                src = img.get("src") or ""
                if not src:
                    continue
                rewritten = _resolve_image_src(src, image_map)
                if rewritten:
                    img["src"] = rewritten

            for image in soup.find_all("image"):
                href = image.get("href") or image.get("xlink:href")
                if not href:
                    continue
                rewritten = _resolve_image_src(href, image_map)
                if rewritten:
                    image["href"] = rewritten

            h = soup.find(["h1", "h2", "title"])
            chapter_title = None
            if h and h.get_text(strip=True):
                chapter_title = h.get_text(strip=True)

            body = soup.body or soup
            markdown = md(
                str(body),
                heading_style="ATX",
                bullets="-",
                strip=["script", "style"],
                escape_asterisks=False,
                escape_underscores=False,
            ).strip()
            markdown = _cleanup_md(markdown)
            if not markdown:
                continue
            if _is_boilerplate_chapter(markdown, chapter_title):
                continue
            if chapter_title and not markdown.lstrip().startswith("#"):
                doc.heading(chapter_title, level=1)
            doc.raw(markdown)
            doc.hr()

        if doc.blocks and doc.blocks[-1].type.value == "thematic_break":
            doc.blocks.pop()
        return doc


def _is_boilerplate_chapter(markdown: str, chapter_title: str | None) -> bool:
    """Drop pure PG license / cover notes, never drop real chapters."""
    text = markdown.lower()
    title = (chapter_title or "").lower()
    # Real narrative usually has dialogue or chapter markers.
    looks_like_story = bool(
        re.search(r"(?i)\bchapter\b|“|\"|‘|'", markdown)
        or re.search(r"(?i)\b(mr\.|mrs\.|said|replied)\b", markdown)
    )
    if looks_like_story and len(markdown) > 400:
        return False

    # short pure license / PG wrapper pages
    if "this ebook is for the use of anyone anywhere" in text and len(markdown) < 2500:
        return True
    if "start of the project gutenberg" in text and len(markdown) < 1500:
        return True
    if "end of the project gutenberg" in text and len(markdown) < 4000 and not looks_like_story:
        return True
    if title and any(k in title for k in ("project gutenberg", "transcriber", "license")):
        if len(markdown) < 800 and not looks_like_story:
            return True
    return False


def _resolve_image_src(src: str, image_map: dict[str, str]) -> str | None:
    src = unquote(src.split("?")[0].split("#")[0])
    candidates = [
        src,
        Path(src).name,
        src.lstrip("./"),
        Path(src.lstrip("./")).as_posix(),
    ]
    for c in candidates:
        if c in image_map:
            return image_map[c]
    name = Path(src).name
    for k, v in image_map.items():
        if Path(k).name == name:
            return v
    return None


def _safe_name(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)
    return name or "image.bin"


def _ext_from_media(media: str | None) -> str | None:
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/svg+xml": ".svg",
        "image/webp": ".webp",
    }
    return mapping.get((media or "").lower())


def _cleanup_md(text: str) -> str:
    # strip PG markers inside chapter text
    text = _PG_START.sub("", text)
    text = _PG_END.sub("", text)
    # drop dense front-matter license paragraph if present at top
    if "this ebook is for the use of anyone anywhere" in text.lower():
        text = _PG_LICENSE_HEAD.sub("", text, count=1)
    # drop simple metadata lines often repeated from PG headers
    lines = []
    for line in text.splitlines():
        if _FRONT_META_LINES.match(line.strip()):
            continue
        if re.match(r"(?i)^\*\*\* START OF THE PROJECT GUTENBERG", line.strip()):
            continue
        if re.match(r"(?i)^\*\*\* END OF THE PROJECT GUTENBERG", line.strip()):
            continue
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
