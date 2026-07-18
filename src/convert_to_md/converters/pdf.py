from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from convert_to_md.context import ConvertContext
from convert_to_md.converters.base import BaseConverter
from convert_to_md.ir import DocumentIR, ImageAsset


@dataclass
class _TB:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    lines: list[str]
    avg_size: float
    max_size: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def xmid(self) -> float:
        return (self.x0 + self.x1) / 2.0


class PdfDigitalConverter(BaseConverter):
    """Extract text from PDFs. Digital text layer first; optional OCR for scans."""

    name = "pdf"
    kinds = ("pdf",)

    def convert(self, path: Path, ctx: ConvertContext) -> DocumentIR:
        import fitz  # PyMuPDF

        pdf = fitz.open(str(path))
        doc = DocumentIR(source=path, title=path.stem)
        try:
            meta_title = (pdf.metadata or {}).get("title")
            if meta_title and str(meta_title).strip():
                doc.title = str(meta_title).strip()
        except Exception:
            pass

        max_pages = ctx.pdf_max_pages
        page_count = pdf.page_count
        limit = page_count if max_pages is None else min(page_count, max_pages)
        page_headings = ctx.pdf_page_headings
        ocr_mode = (ctx.pdf_ocr or "auto").lower()

        digital_chars = 0
        page_blocks: list[list[_TB]] = []
        for i in range(limit):
            page = pdf.load_page(i)
            page_w = float(page.rect.width)
            page_h = float(page.rect.height)
            blocks = _extract_blocks(page)
            blocks = [b for b in blocks if not _is_margin_noise(b, page_w, page_h)]
            blocks = _sort_reading_order(blocks, page_w)
            page_blocks.append(blocks)
            digital_chars += sum(len(b.text) for b in blocks)

        # sparse / empty text layer → likely scan
        # Use a low floor so short digital pages are not misclassified.
        looks_scanned = digital_chars < 20
        formula_ocr_mode = (getattr(ctx, "pdf_formula_ocr", "auto") or "auto").lower()
        # Full-page OCR only when requested; keep digital path if formula-image OCR may still help.
        use_full_page_ocr = ocr_mode == "force" or (
            ocr_mode == "auto" and looks_scanned and formula_ocr_mode == "off"
        )

        if use_full_page_ocr:
            pdf.close()
            return _convert_via_ocr(path, ctx, title=doc.title)

        image_i = 0
        seen_xrefs: set[int] = set()

        for i in range(limit):
            page = pdf.load_page(i)
            page_w = float(page.rect.width)
            page_h = float(page.rect.height)
            blocks = page_blocks[i]

            if page_headings and page_count > 1:
                doc.heading(f"Page {i + 1}", level=2)

            if i == 0 and (not doc.title or doc.title == path.stem):
                guessed = _guess_title(blocks)
                if guessed:
                    doc.title = guessed

            _emit_page_blocks(doc, blocks, page_w, page_index=i)

            image_items = _page_image_items(page)
            for item in image_items:
                xref = item.get("xref")
                if xref is not None:
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                try:
                    blob = item.get("blob") or b""
                    if not blob and xref is not None:
                        info = pdf.extract_image(xref)
                        blob = info.get("image") or b""
                        ext = info.get("ext") or "png"
                    else:
                        ext = item.get("ext") or "png"
                    if len(blob) < 800:
                        continue
                    image_i += 1
                    asset = ImageAsset(
                        data=blob,
                        filename=f"page{i + 1}_image_{image_i}.{ext}",
                        alt=f"page {i + 1} image {image_i}",
                        content_type=f"image/{ext}",
                    )
                    formula_md = None
                    if formula_ocr_mode != "off":
                        rect = item.get("rect")
                        formula_md = _ocr_formula_region(
                            page,
                            rect,
                            blob=blob if rect is None else None,
                            page_w=page_w,
                            page_h=page_h,
                            mode=formula_ocr_mode,
                            engine=getattr(ctx, "formula_ocr_engine", "auto") or "auto",
                        )
                    if formula_md:
                        doc.image(asset)
                        doc.formula(formula_md, display=True)
                    else:
                        doc.image(asset)
                except Exception:
                    continue

            # Force mode: OCR empty horizontal bands that may contain formula drawings.
            if formula_ocr_mode == "force":
                for band in _formula_band_candidates(page_w, page_h, blocks):
                    text = _ocr_formula_region(
                        page,
                        band,
                        blob=None,
                        page_w=page_w,
                        page_h=page_h,
                        mode="force",
                        engine=getattr(ctx, "formula_ocr_engine", "auto") or "auto",
                    )
                    if text:
                        doc.formula(text, display=True)

            if page_headings and i < limit - 1:
                doc.hr()

        has_body = any(
            b.type.value == "paragraph"
            or (b.type.value == "heading" and not b.text.startswith("Page "))
            or b.type.value == "list"
            or b.type.value == "formula"
            or b.type.value == "image"
            for b in doc.blocks
        )
        if not has_body:
            if ocr_mode == "off":
                doc.paragraph(
                    "_No extractable text layer found. This may be a scanned PDF. "
                    "Re-run with `--pdf-ocr auto` or `--pdf-ocr force` (requires Tesseract)._"
                )
            else:
                # auto already tried threshold; still empty somehow
                doc.paragraph(
                    "_No extractable text layer found. This may be a scanned PDF; OCR support is available via `--pdf-ocr force`._"
                )

        pdf.close()
        return doc


def _convert_via_ocr(path: Path, ctx: ConvertContext, title: str | None) -> DocumentIR:
    from convert_to_md.ocr import OcrUnavailableError, ocr_pdf

    doc = DocumentIR(source=path, title=title or path.stem)
    try:
        result = ocr_pdf(path, max_pages=ctx.pdf_max_pages)
    except OcrUnavailableError as e:
        doc.paragraph(f"_{e}_")
        return doc

    doc.metadata["ocr_engine"] = result.engine
    for page in result.pages:
        if ctx.pdf_page_headings and len(result.pages) > 1:
            doc.heading(f"Page {page.index + 1}", level=2)
        text = _cleanup_ocr_text(page.text)
        if not text:
            continue
        for para in re.split(r"\n\s*\n", text):
            para = _join_lines(para.splitlines())
            if para:
                doc.paragraph(para)
        if ctx.pdf_page_headings and page.index < len(result.pages) - 1:
            doc.hr()

    if not any(b.type.value == "paragraph" for b in doc.blocks):
        doc.paragraph("_OCR produced no text._")
    return doc


def _cleanup_ocr_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _page_image_items(page) -> list[dict]:
    """Collect embedded images with optional rects (best-effort across PyMuPDF versions)."""
    items: list[dict] = []
    seen: set[int] = set()

    # Primary: xref list
    try:
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            rect = None
            try:
                rects = list(page.get_image_rects(xref))
                rect = rects[0] if rects else None
            except Exception:
                rect = None
            items.append({"xref": xref, "rect": rect, "blob": None, "ext": "png"})
    except Exception:
        pass

    # Fallback: image info with bbox
    if not items:
        try:
            for info in page.get_image_info(xrefs=True):
                xref = info.get("xref") or 0
                bbox = info.get("bbox")
                rect = None
                if bbox is not None:
                    import fitz

                    rect = fitz.Rect(bbox)
                items.append({"xref": xref or None, "rect": rect, "blob": None, "ext": "png"})
        except Exception:
            pass

    return items


def _ocr_formula_region(
    page,
    rect,
    *,
    blob: bytes | None,
    page_w: float,
    page_h: float,
    mode: str,
    engine: str = "auto",
) -> str | None:
    """OCR a PDF image/region that may contain a formula. Returns latexish text or None."""
    from convert_to_md.formula_ocr import FormulaOcrUnavailableError, ocr_formula_bytes, ocr_formula_pil
    from convert_to_md.mathutil import looks_like_formula_text

    try:
        import fitz
        from PIL import Image
        import io
    except Exception:
        return None

    # Geometry gate for auto mode: formula images are usually short-wide, not full-page photos.
    if rect is not None:
        try:
            r = fitz.Rect(rect)
        except Exception:
            r = None
        if r is not None and mode == "auto":
            w, h = float(r.width), float(r.height)
            if w < 40 or h < 12:
                return None
            if w > page_w * 0.98 and h > page_h * 0.35:
                return None  # likely figure/photo
            if h > page_h * 0.45:
                return None
            if w / max(h, 1.0) < 1.2 and h > 80:
                # square-ish medium block: could be diagram; only force keeps it
                return None

    text = ""
    used_engine = ""
    try:
        if rect is not None:
            clip = fitz.Rect(rect)
            pad = 2
            clip = fitz.Rect(clip.x0 - pad, clip.y0 - pad, clip.x1 + pad, clip.y1 + pad) & page.rect
            mat = fitz.Matrix(3, 3)
            pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            result = ocr_formula_pil(img, engine=engine)
            text, used_engine = result.latex, result.engine
        elif blob:
            result = ocr_formula_bytes(blob, engine=engine)
            text, used_engine = result.latex, result.engine
    except FormulaOcrUnavailableError:
        return None
    except Exception:
        return None

    text = _cleanup_ocr_text(text)
    if not text:
        return None
    compact = re.sub(r"\s*\n\s*", " ", text).strip()
    # Specialized engines already return LaTeX; accept more liberally.
    if used_engine == "pix2tex":
        return compact
    if mode == "auto" and not looks_like_formula_text(compact) and not _ocr_text_formulaish(compact):
        return None
    if looks_like_formula_text(compact) or _ocr_text_formulaish(compact) or mode == "force":
        return compact
    return None


def _ocr_text_formulaish(text: str) -> bool:
    t = text.strip()
    if len(t) < 3 or len(t) > 220:
        return False
    # OCR often yields ascii approximations of math
    score = 0
    if re.search(r"[=≈≠≤≥<>]", t):
        score += 1
    if re.search(r"[\^_/\\]|sqrt|sum|int|frac|lim|sin|cos|log|pi|theta|alpha|beta", t, re.I):
        score += 1
    if re.search(r"\d", t) and re.search(r"[A-Za-z]", t):
        score += 1
    if re.search(r"[()\[\]{}]", t):
        score += 1
    return score >= 2


def _formula_band_candidates(page_w: float, page_h: float, blocks: list[_TB]):
    """Heuristic empty horizontal bands between text blocks (force mode helper)."""
    import fitz

    if not blocks:
        return []
    ys = sorted((b.y0, b.y1) for b in blocks)
    bands = []
    prev_y1 = min(b.y0 for b in blocks)
    for y0, y1 in ys:
        gap = y0 - prev_y1
        if 28 <= gap <= 120:
            band = fitz.Rect(page_w * 0.12, prev_y1 + 4, page_w * 0.88, y0 - 4)
            if band.height >= 18:
                bands.append(band)
        prev_y1 = max(prev_y1, y1)
    return bands[:5]


def _extract_blocks(page) -> list[_TB]:
    import fitz

    raw = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    out: list[_TB] = []
    for b in raw:
        if b.get("type") != 0:
            continue
        lines: list[str] = []
        sizes: list[float] = []
        for line in b.get("lines", []):
            line_text = "".join(span.get("text", "") for span in line.get("spans", []))
            if line_text.strip():
                lines.append(line_text.rstrip())
            for span in line.get("spans", []):
                if "size" in span:
                    sizes.append(float(span["size"]))
        if not lines:
            continue
        x0, y0, x1, y1 = b.get("bbox", [0, 0, 0, 0])
        avg = sum(sizes) / len(sizes) if sizes else 0.0
        mx = max(sizes) if sizes else 0.0
        out.append(
            _TB(
                x0=float(x0),
                y0=float(y0),
                x1=float(x1),
                y1=float(y1),
                text=_join_lines(lines),
                lines=lines,
                avg_size=avg,
                max_size=mx,
            )
        )
    return out


def _is_margin_noise(b: _TB, page_w: float, page_h: float) -> bool:
    if b.width > 0 and b.height / max(b.width, 1.0) >= 4.0 and b.width < page_w * 0.12:
        if b.x0 < page_w * 0.12 or b.x1 > page_w * 0.88:
            return True
    if re.fullmatch(r"\d{1,4}", b.text.strip()) and b.avg_size <= 11 and b.y0 > page_h * 0.85:
        return True
    if re.fullmatch(r"\d{1,4}", b.text.strip()) and b.avg_size <= 11 and b.y1 < page_h * 0.08:
        return True
    if re.match(r"(?i)^arXiv:\d{4}\.\d+", b.text.strip()):
        return True
    return False


def _sort_reading_order(blocks: list[_TB], page_w: float) -> list[_TB]:
    if len(blocks) < 4:
        return sorted(blocks, key=lambda b: (round(b.y0, 1), b.x0))

    cols = _detect_columns(blocks, page_w)
    if cols is None:
        return sorted(blocks, key=lambda b: (round(b.y0, 1), b.x0))

    left_cut, right_cut = cols
    left = [b for b in blocks if b.xmid <= left_cut]
    right = [b for b in blocks if b.xmid >= right_cut]
    middle = [b for b in blocks if left_cut < b.xmid < right_cut]

    if len(left) < 2 or len(right) < 2:
        return sorted(blocks, key=lambda b: (round(b.y0, 1), b.x0))
    if len(middle) >= max(len(left), len(right)):
        return sorted(blocks, key=lambda b: (round(b.y0, 1), b.x0))

    left_span = max(b.y1 for b in left) - min(b.y0 for b in left)
    right_span = max(b.y1 for b in right) - min(b.y0 for b in right)
    if left_span > 120 and right_span > 120:
        left_s = sorted(left + middle, key=lambda b: (round(b.y0, 1), b.x0))
        right_s = sorted(right, key=lambda b: (round(b.y0, 1), b.x0))
        return left_s + right_s
    return sorted(blocks, key=lambda b: (round(b.y0, 1), b.x0))


def _detect_columns(blocks: list[_TB], page_w: float) -> tuple[float, float] | None:
    narrow = [b for b in blocks if b.width < page_w * 0.55 and b.width > page_w * 0.15]
    if len(narrow) < 6:
        return None
    xmids = sorted(b.xmid for b in narrow)
    gaps = [(b - a, a, b) for a, b in zip(xmids, xmids[1:])]
    if not gaps:
        return None
    gap, left_edge, right_edge = max(gaps, key=lambda g: g[0])
    if gap < page_w * 0.08:
        return None
    left_cluster = [x for x in xmids if x <= left_edge]
    right_cluster = [x for x in xmids if x >= right_edge]
    if len(left_cluster) < 3 or len(right_cluster) < 3:
        return None
    mid = (left_edge + right_edge) / 2
    if not (page_w * 0.35 <= mid <= page_w * 0.65):
        return None
    return left_edge, right_edge


def _emit_page_blocks(
    doc: DocumentIR,
    blocks: list[_TB],
    page_w: float,
    *,
    page_index: int = 0,
) -> None:
    if not blocks:
        return

    author_idxs = _author_block_indices(blocks, page_w) if page_index == 0 else set()
    para_buf: list[str] = []
    last: _TB | None = None
    authors_emitted = False

    def flush_para() -> None:
        nonlocal para_buf
        if not para_buf:
            return
        text = _join_lines(para_buf)
        if text:
            from convert_to_md.mathutil import (
                looks_like_formula_text,
                unicode_formula_to_latexish,
            )

            if looks_like_formula_text(text):
                doc.formula(unicode_formula_to_latexish(text), display=True)
            else:
                doc.paragraph(text)
        para_buf = []

    i = 0
    while i < len(blocks):
        b = blocks[i]
        if i in author_idxs:
            flush_para()
            if not authors_emitted:
                authors = _cluster_author_cards(blocks, author_idxs)
                if authors:
                    doc.heading("Authors", level=4)
                    doc.list_items(authors, ordered=False)
                authors_emitted = True
            while i < len(blocks) and i in author_idxs:
                i += 1
            last = None
            continue

        if _looks_like_heading(b):
            flush_para()
            doc.heading(b.text, level=_heading_level(b))
            last = b
            i += 1
            continue

        if last is not None and _should_break_paragraph(last, b):
            flush_para()

        para_buf.extend(b.lines)
        last = b
        i += 1

    flush_para()


def _author_block_indices(blocks: list[_TB], page_w: float) -> set[int]:
    cands: list[int] = []
    for i, b in enumerate(blocks):
        if b.y0 > 420:
            continue
        if b.avg_size > 11.5:
            continue
        if b.width >= page_w * 0.42:
            continue
        if len(b.text) > 180:
            continue
        if _looks_like_heading(b):
            continue
        if (
            "@" in b.text
            or re.search(r"(?i)(university|google|research|institute|lab|department|brain)", b.text)
            or (len(b.lines) <= 4 and b.avg_size <= 10.5 and b.width < page_w * 0.28)
        ):
            cands.append(i)

    if len(cands) < 2:
        return set()

    has_pair = any(
        abs(blocks[a].y0 - blocks[b].y0) < 28 and abs(blocks[a].xmid - blocks[b].xmid) > 40
        for a in cands
        for b in cands
        if a < b
    )
    if not has_pair:
        return set()

    idxs = set(cands)
    for i, b in enumerate(blocks):
        if i in idxs or b.y0 > 420:
            continue
        if b.avg_size > 11.5 or b.width >= page_w * 0.35 or len(b.text) > 80:
            continue
        if _looks_like_heading(b):
            continue
        for j in list(idxs):
            other = blocks[j]
            if abs(b.xmid - other.xmid) >= 45:
                continue
            if 0 <= (other.y0 - b.y1) < 16 or 0 <= (b.y0 - other.y1) < 16:
                idxs.add(i)
                break
    return idxs


def _cluster_author_cards(blocks: list[_TB], idxs: set[int]) -> list[str]:
    if not idxs:
        return []
    items = sorted(idxs)
    parent = {i: i for i in items}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a in items:
        ba = blocks[a]
        for b in items:
            if a >= b:
                continue
            bb = blocks[b]
            if abs(ba.xmid - bb.xmid) > 40:
                continue
            gap = bb.y0 - ba.y1 if bb.y0 >= ba.y0 else ba.y0 - bb.y1
            if gap < 14:
                union(a, b)

    groups: dict[int, list[int]] = {}
    for i in items:
        groups.setdefault(find(i), []).append(i)

    clusters = list(groups.values())
    clusters.sort(key=lambda c: (min(blocks[i].y0 for i in c), min(blocks[i].xmid for i in c)))

    authors: list[str] = []
    for cluster in clusters:
        cluster.sort(key=lambda i: blocks[i].y0)
        lines: list[str] = []
        for i in cluster:
            for ln in blocks[i].lines:
                s = ln.strip()
                if s and s not in lines:
                    lines.append(s)
        if not lines:
            continue
        authors.append(lines[0] if len(lines) == 1 else f"{lines[0]} — " + " — ".join(lines[1:]))
    return authors


def _should_break_paragraph(prev: _TB, cur: _TB) -> bool:
    gap = cur.y0 - prev.y1
    if gap > max(8.0, (prev.avg_size or 11) * 0.85):
        return True
    if abs(cur.xmid - prev.xmid) > 120 and gap >= 0 and gap < 20:
        return True
    if prev.avg_size and cur.avg_size and abs(prev.avg_size - cur.avg_size) >= 3.5:
        return True
    return False


def _guess_title(blocks: list[_TB]) -> str | None:
    upper = [b for b in blocks if b.y0 < 220 and 5 < len(b.text) <= 120]
    if not upper:
        return None
    best = max(upper, key=lambda b: (b.max_size, -b.y0))
    # require a clearly large title font; avoid section headings like "Introduction"
    if best.max_size < 16:
        return None
    if re.match(r"^\d+(\.\d+)*\s+\S", best.text):
        return None
    if best.text.strip() in {"Abstract", "Introduction", "References", "Appendix", "Method", "Results"}:
        return None
    return best.text


def _heading_level(b: _TB) -> int:
    text = b.text
    if re.match(r"^\d+\.\d+", text):
        return 4
    if re.match(r"^\d+\s+\S", text):
        return 3
    if b.max_size >= 16:
        return 3
    if text in {"Abstract", "References", "Acknowledgments", "Appendix", "Introduction"}:
        return 3
    return 4


def _looks_like_heading(b: _TB) -> bool:
    text = b.text.strip()
    if not text or len(text) > 100:
        return False
    if text.endswith(".") and len(text) > 40:
        return False
    if re.match(r"(?i)^arXiv:", text):
        return False
    if b.max_size >= 13.5 and len(text) <= 80 and b.width < 500:
        if text.endswith(".") and b.max_size < 15:
            return False
        return True
    if re.match(r"^\d+(\.\d+)*\s+[A-ZА-Я一-鿿]", text):
        return True
    if re.match(r"^[一二三四五六七八九十]+[、.．]\s*\S", text):
        return True
    if text in {"Abstract", "References", "Acknowledgments", "Appendix"}:
        return True
    return False


def _join_lines(lines: list[str]) -> str:
    out: list[str] = []
    for line in lines:
        s = re.sub(r"[ \t]+", " ", line).strip()
        if not s:
            continue
        # de-hyphenate across line breaks: "trans-\nformer" / "trans- former"
        if out and re.search(r"[A-Za-z]-$", out[-1]) and re.match(r"^[a-z]", s):
            out[-1] = out[-1][:-1] + s
        else:
            out.append(s)
    text = " ".join(out)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
