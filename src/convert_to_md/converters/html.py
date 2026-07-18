from __future__ import annotations

import re
from pathlib import Path

from convert_to_md.context import ConvertContext
from convert_to_md.converters.base import BaseConverter
from convert_to_md.ir import DocumentIR

# Prefer the real article body over chrome.
_CONTENT_SELECTORS = (
    "article",
    "main article",
    "[role='main'] article",
    "main .mw-parser-output",
    "#mw-content-text .mw-parser-output",
    "#mw-content-text",
    "#bodyContent",
    "main",
    "[role='main']",
    "#content",
    "#main-content",
    ".post-content",
    ".entry-content",
    ".article-content",
    ".markdown-body",
    "#readme",
)

_DROP_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "iframe",
    "svg",
    "canvas",
    "nav",
    "footer",
    "header",
    "aside",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    "label",
}

_DROP_ROLES = {
    "navigation",
    "banner",
    "complementary",
    "contentinfo",
    "search",
    "menu",
    "menubar",
    "toolbar",
}

_NOISE_TOKENS = re.compile(
    r"(?i)("
    r"nav(bar|igation)?|menu|sidebar|side-bar|footer|header|breadcrumb|"
    r"cookie|consent|banner|promo|advert|ads?|sponsor|"
    r"social|share|related|recommend|comment|newsletter|subscribe|"
    r"toc-mobile|vector-|mw-jump|mw-editsection|mw-indicators|"
    r"catlinks|printfooter|siteNotice|noprint|navbox|metadata|"
    r"reference-preview|hatnote-?list|global-nav|topbar|bottombar|"
    r"login|signup|searchbox|language-list|mw-authority-control|"
    r"sistersitebox|shortdescription|ambox|tmbox|ombox|cmbox|fmbox"
    r")"
)

_KEEP_DESPITE_NOISE = re.compile(
    r"(?i)(content|article|post-body|entry-content|mw-parser-output|bodyContent|headline|title)"
)

_INFOBOX_CLASS = re.compile(r"(?i)\binfobox\b")
_NAVBOX_CLASS = re.compile(r"(?i)\b(navbox|vertical-navbox|sidebar)\b")
_THUMB_NOISE = re.compile(r"(?i)\b(thumb|magnify|noprint|mw-file-description)\b")


class HtmlConverter(BaseConverter):
    name = "html"
    kinds = ("html",)

    def convert(self, path: Path, ctx: ConvertContext) -> DocumentIR:
        from bs4 import BeautifulSoup
        from markdownify import markdownify as md

        from convert_to_md.mathutil import (
            replace_html_math_with_placeholders,
            restore_math_placeholders,
        )

        raw = path.read_bytes()
        text = _decode(raw)
        soup = BeautifulSoup(text, "lxml")

        title = _extract_title(soup)
        root = _select_content_root(soup)

        # Extract MathML / MathJax before noise stripping removes <script type="math/tex">.
        math_map = replace_html_math_with_placeholders(root)

        # Normalize noisy document titles in-body (ar5iv copyright suffixes, arxiv ids).
        for h in root.select("h1.ltx_title_document, h1"):
            if h.get_text(strip=True):
                cleaned = _normalize_title(h.get_text(" ", strip=True))
                if cleaned and cleaned != h.get_text(" ", strip=True):
                    h.clear()
                    h.string = cleaned
                break

        _strip_noise(
            root,
            keep_infobox=ctx.html_keep_infobox,
            keep_navboxes=ctx.html_keep_navboxes,
        )

        if not root.get_text(strip=True) and not math_map:
            root = soup.body or soup
            math_map = replace_html_math_with_placeholders(root)
            _strip_noise(
                root,
                keep_infobox=ctx.html_keep_infobox,
                keep_navboxes=ctx.html_keep_navboxes,
            )

        markdown = md(
            str(root),
            heading_style="ATX",
            bullets="-",
            strip=["script", "style", "noscript"],
            escape_asterisks=False,
            escape_underscores=False,
        ).strip()
        markdown = restore_math_placeholders(markdown, math_map)
        markdown = _cleanup_markdown(markdown, title=title)
        # markdownify may leave placeholders escaped or split; second pass safety
        markdown = restore_math_placeholders(markdown, math_map)

        doc = DocumentIR(source=path, title=title or path.stem)
        if markdown:
            doc.raw(markdown)
        return doc


def _extract_title(soup) -> str | None:
    for sel in (
        "h1#firstHeading",
        "h1.entry-title",
        "h1.ltx_title_document",
        ".ltx_title_document",
        "article h1",
        "main h1",
        "h1",
    ):
        el = soup.select_one(sel)
        if el:
            t = el.get_text(" ", strip=True)
            if t:
                return _normalize_title(t)
    if soup.title and soup.title.string:
        t = soup.title.string.strip()
        t = re.sub(r"\s*[|\-–—]\s*Wikipedia\s*$", "", t, flags=re.I).strip()
        # ar5iv titles often: "[1909.03550] Real Title ..."
        t = re.sub(r"^\[\d{4}\.\d{4,5}(?:v\d+)?\]\s*", "", t)
        return _normalize_title(t) or None
    return None


def _normalize_title(title: str) -> str:
    t = re.sub(r"\s+", " ", title).strip()
    t = re.sub(r"(?i)\s*all rights reserved\.?\s*$", "", t).strip()
    t = re.sub(r"(?i)^lecture notes:\s*", "", t).strip() or t
    return t


def _select_content_root(soup):
    for sel in _CONTENT_SELECTORS:
        el = soup.select_one(sel)
        if el is None:
            continue
        text = el.get_text(" ", strip=True)
        if len(text) >= 80:
            return el
    return soup.body or soup


def _strip_noise(root, *, keep_infobox: bool = False, keep_navboxes: bool = False) -> None:
    from bs4 import Tag

    def alive(el) -> bool:
        return isinstance(el, Tag) and el.attrs is not None and el.parent is not None

    for tag_name in _DROP_TAGS:
        for el in list(root.find_all(tag_name)):
            if alive(el):
                el.decompose()

    candidates = [el for el in root.find_all(True) if isinstance(el, Tag)]
    for el in candidates:
        if not alive(el):
            continue
        role = str(el.attrs.get("role") or "").strip().lower()
        if role in _DROP_ROLES:
            el.decompose()
            continue
        aria = str(el.attrs.get("aria-hidden") or "").strip().lower()
        if aria == "true":
            el.decompose()
            continue

        tokens = _element_tokens(el)
        if not keep_infobox and el.name == "table" and _INFOBOX_CLASS.search(tokens):
            el.decompose()
            continue
        if not keep_navboxes and _NAVBOX_CLASS.search(tokens):
            el.decompose()
            continue
        # Wikipedia hatnotes / maintenance banners
        if re.search(r"(?i)\b(hatnote|ambox|tmbox|ombox|cmbox|fmbox|shortdescription)\b", tokens):
            el.decompose()
            continue
        # reference backlinks / cite brackets later handled; drop edit sections
        if el.name in {"div", "section", "ul", "ol", "table", "span"} and _is_noise_element(el):
            if _is_keep_element(el):
                continue
            if _looks_like_chrome(el):
                el.decompose()

    for el in list(root.select(".mw-editsection, .mw-editsection-bracket, .mw-cite-backlink, .reference")):
        # keep numbered references list items content, but strip inline cite superscripts
        if not alive(el):
            continue
        classes = " ".join(el.get("class") or [])
        if "reference" in classes.split() and el.name in {"sup", "span"}:
            el.decompose()
            continue
        if "mw-editsection" in classes or "mw-cite-backlink" in classes:
            el.decompose()

    for el in list(root.find_all("a", class_=True)):
        if not alive(el):
            continue
        classes = " ".join(el.get("class") or [])
        if "mw-jump-link" in classes:
            el.decompose()

    # remove tiny icon-only thumbs that add noise without alt text value
    for el in list(root.find_all(["figure", "div", "span"])):
        if not alive(el):
            continue
        tokens = _element_tokens(el)
        if _THUMB_NOISE.search(tokens) and len(el.get_text(" ", strip=True)) < 8:
            el.decompose()

    # unwrap empty links
    for el in list(root.find_all("a")):
        if not alive(el):
            continue
        if not el.get_text(strip=True) and not el.find("img"):
            el.decompose()


def _is_noise_element(el) -> bool:
    tokens = _element_tokens(el)
    return bool(tokens and _NOISE_TOKENS.search(tokens))


def _is_keep_element(el) -> bool:
    tokens = _element_tokens(el)
    return bool(tokens and _KEEP_DESPITE_NOISE.search(tokens))


def _element_tokens(el) -> str:
    parts: list[str] = []
    if el.get("id"):
        parts.append(str(el.get("id")))
    for c in el.get("class") or []:
        parts.append(str(c))
    return " ".join(parts)


def _looks_like_chrome(el) -> bool:
    tokens = _element_tokens(el)
    if not _NOISE_TOKENS.search(tokens):
        return False
    if re.search(
        r"(?i)(vector-header|vector-main-menu|vector-toc|navbox|catlinks|printfooter|"
        r"mw-jump|sidebar|site-nav|global-nav|cookie|consent|advert|breadcrumb|infobox)",
        tokens,
    ):
        return True
    text = el.get_text(" ", strip=True)
    if len(text) < 20:
        return True
    links = el.find_all("a")
    if links and len(links) >= 5 and len(text) / max(len(links), 1) < 40:
        return True
    return False


def _cleanup_markdown(text: str, title: str | None = None) -> str:
    # strip invisible format chars that Wikipedia/MathML inject around fractions
    text = re.sub(r"[⁠​‌‍⁡⁢⁣⁤﻿]", "", text)

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned: list[str] = []
    skip_patterns = [
        re.compile(r"(?i)^jump to (content|search|navigation)\.?$"),
        re.compile(r"(?i)^(main menu|move to sidebar|hide|appearance|personal tools)$"),
        re.compile(r"(?i)^toggle .* menu$"),
        re.compile(r"(?i)^\[edit\]$"),
        re.compile(r"(?i)^search$"),
        re.compile(r"(?i)^contents$"),
        re.compile(r"(?i)^from wikipedia, the free encyclopedia$"),
        re.compile(r"(?i)^coordinates?:\s*.+$"),
        re.compile(r"(?i)^all rights reserved\.?$"),
        re.compile(r"^•$"),
    ]
    for line in lines:
        s = line.strip()
        if any(p.match(s) for p in skip_patterns):
            continue
        if s.startswith("[Jump to "):
            continue
        # ar5iv / LaTeXML often emits "- •" then indented content
        line = re.sub(r"(?m)^(\s*[-*+]\s+)•\s*", r"\1", line)
        line = re.sub(r"(?m)^(\s*\d+\.\s+)•\s*", r"\1", line)
        # drop orphan table separator rows left by removed infoboxes
        if re.fullmatch(r"\|?(?:\s*\|?\s*---+\s*)+\|?", s):
            if cleaned:
                prev = cleaned[-1].strip()
                if prev.count("|") >= 2 and not re.fullmatch(r"\|?(?:\s*\|?\s*---+\s*)+\|?", prev):
                    cleaned.append(line)
            continue
        cleaned.append(line)

    text = "\n".join(cleaned)
    text = re.sub(r"\[(?:\d+|edit|citation needed)\]", "", text, flags=re.I)
    text = re.sub(r"(?m)^\|\s*\|\s*$\n?", "", text)
    text = re.sub(r"(?m)^\|\s*$", "", text)
    text = re.sub(
        r"(?is)\|\s*\[?icon\]?[^\n]*\n\|\s*---.*?\n(?:\|[^\n]*\n){0,6}",
        "",
        text,
    )
    # collapse "- \n\n  text" style broken list items a bit
    text = re.sub(r"(?m)^(\s*[-*+])\s*\n+\s+", r"\1 ", text)
    # drop residual empty table scaffolding near formulas
    from convert_to_md.mathutil import cleanup_formula_table_chrome

    text = cleanup_formula_table_chrome(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # strip copyright suffix if it survived in headings
    text = re.sub(r"(?im)^(#{1,6}\s+.*?)(\s+All rights reserved\.?)\s*$", r"\1", text)
    text = re.sub(r"(?im)^(#{1,6}\s+)\[\d{4}\.\d{4,5}(?:v\d+)?\]\s*", r"\1", text)
    return text


def _decode(data: bytes) -> str:
    from charset_normalizer import from_bytes

    best = from_bytes(data).best()
    if best is not None:
        return str(best)
    return data.decode("utf-8", errors="replace")
