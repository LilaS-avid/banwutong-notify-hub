from __future__ import annotations

import re
import threading
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json"}
DOCX_SUFFIXES = {".docx"}
DOC_SUFFIXES = {".doc"}
PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
SPREADSHEET_SUFFIXES = {".xlsx", ".xlsm"}
SLIDES_SUFFIXES = {".pptx"}
HTML_SUFFIXES = {".html", ".htm"}
RTF_SUFFIXES = {".rtf"}
ALLOWED_SUFFIXES = (
    TEXT_SUFFIXES
    | DOCX_SUFFIXES
    | DOC_SUFFIXES
    | PDF_SUFFIXES
    | IMAGE_SUFFIXES
    | SPREADSHEET_SUFFIXES
    | SLIDES_SUFFIXES
    | HTML_SUFFIXES
    | RTF_SUFFIXES
)
OCR_SCORE_THRESHOLD = 0.3
PDF_RENDER_DPI = 200
PDF_TEXT_THRESHOLD = 20

_OCR_ENGINE = None
_OCR_LOCK = threading.Lock()


@dataclass(slots=True)
class DocumentBlock:
    locator: str
    block_type: str
    text: str


@dataclass(slots=True)
class ExtractedDocument:
    status: str
    text: str | None
    note: str | None
    blocks: list[DocumentBlock] = field(default_factory=list)


def safe_original_name(filename: str | None) -> str:
    name = Path(filename or "upload").name.replace("\x00", "").strip()
    return name[:200] or "upload"


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Unsupported text encoding")


def _docx_paragraph_text(node, namespace: str) -> str:
    return "".join(
        text_node.text or ""
        for text_node in node.iter(f"{namespace}t")
    ).strip()


def _extract_docx(path: Path) -> list[DocumentBlock]:
    with zipfile.ZipFile(path) as archive:
        try:
            xml = archive.read("word/document.xml")
        except KeyError as error:
            raise ValueError("DOCX document body is missing") from error
    root = ElementTree.fromstring(xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body = root.find(f"{namespace}body")
    if body is None:
        return []

    blocks: list[DocumentBlock] = []
    for index, child in enumerate(body):
        if child.tag == f"{namespace}p":
            text = _docx_paragraph_text(child, namespace)
            if text:
                blocks.append(
                    DocumentBlock(
                        locator=f"docx-block-{index + 1}",
                        block_type="paragraph",
                        text=text,
                    )
                )
        elif child.tag == f"{namespace}tbl":
            rows: list[str] = []
            for row_index, row in enumerate(child.iter(f"{namespace}tr"), start=1):
                cells = [
                    _docx_paragraph_text(cell, namespace)
                    for cell in row.findall(f"{namespace}tc")
                ]
                if any(cells):
                    rows.append(f"row-{row_index}: " + " | ".join(cells))
            if rows:
                blocks.append(
                    DocumentBlock(
                        locator=f"docx-table-{index + 1}",
                        block_type="table",
                        text="\n".join(rows),
                    )
                )
    return blocks


def _ocr_blocks(source, prefix: str) -> list[DocumentBlock]:
    with _OCR_LOCK:
        engine = _get_ocr_engine()
        result, _ = engine(source)
    detected: list[tuple[float, float, float, float, float, str]] = []
    for item in result or []:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        text = str(item[1]).strip()
        try:
            score = float(item[2])
        except (TypeError, ValueError):
            score = 0.0
        if not text or score < OCR_SCORE_THRESHOLD:
            continue
        try:
            xs = [float(point[0]) for point in item[0]]
            ys = [float(point[1]) for point in item[0]]
        except (TypeError, ValueError, IndexError):
            continue
        if not xs or not ys:
            continue
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        detected.append(
            (left, right, top, bottom, max(1.0, bottom - top), text)
        )

    rows: list[list[tuple[float, float, float, float, float, str]]] = []
    for item in sorted(detected, key=lambda value: ((value[2] + value[3]) / 2, value[0])):
        center = (item[2] + item[3]) / 2
        if rows:
            row_center = sum((value[2] + value[3]) / 2 for value in rows[-1]) / len(rows[-1])
            row_height = max(value[4] for value in rows[-1])
            if abs(center - row_center) <= row_height * 0.55:
                rows[-1].append(item)
                continue
        rows.append([item])

    lines: list[str] = []
    for row in rows:
        ordered = sorted(row, key=lambda value: value[0])
        combined = ""
        previous_right = None
        previous_height = 1.0
        for left, right, _, _, height, text in ordered:
            if previous_right is not None and left - previous_right > max(previous_height, height):
                combined += " "
            overlap = 0
            max_overlap = min(len(combined), len(text))
            for size in range(max_overlap, 0, -1):
                if combined[-size:] == text[:size]:
                    overlap = size
                    break
            combined += text[overlap:]
            previous_right = right
            previous_height = height
        combined = re.sub(
            r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})(\d{1,2}:\d{2})",
            r"\1 \2",
            combined,
        )
        combined = re.sub(
            r"(\d{1,2}月\d{1,2}日)(\d{1,2}:\d{2})",
            r"\1 \2",
            combined,
        )
        if combined.strip():
            lines.append(combined.strip())
    return [
        DocumentBlock(
            locator=f"{prefix}-{index}",
            block_type="ocr_line",
            text=text,
        )
        for index, text in enumerate(lines, start=1)
    ]


def _extract_pdf(path: Path) -> list[DocumentBlock]:
    import numpy as np
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    blocks: list[DocumentBlock] = []
    try:
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                text_page = page.get_textpage()
                try:
                    text = (text_page.get_text_range() or "").strip()
                finally:
                    text_page.close()
                compact_length = len(re.sub(r"\s+", "", text))
                if compact_length >= PDF_TEXT_THRESHOLD:
                    blocks.append(
                        DocumentBlock(
                            locator=f"page-{index + 1}",
                            block_type="page",
                            text=text,
                        )
                    )
                    continue

                bitmap = page.render(scale=PDF_RENDER_DPI / 72)
                try:
                    image = np.asarray(bitmap.to_pil().convert("RGB"))
                finally:
                    bitmap.close()
                ocr_blocks = _ocr_blocks(
                    image,
                    f"page-{index + 1}-ocr-line",
                )
                if ocr_blocks:
                    blocks.extend(ocr_blocks)
                elif text:
                    blocks.append(
                        DocumentBlock(
                            locator=f"page-{index + 1}",
                            block_type="page",
                            text=text,
                        )
                    )
            finally:
                page.close()
    finally:
        pdf.close()
    return blocks


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def _extract_image(path: Path) -> list[DocumentBlock]:
    return _ocr_blocks(str(path), "ocr-line")


def _text_blocks(text: str, prefix: str = "block") -> list[DocumentBlock]:
    normalized = re.sub(r"\r\n?", "\n", text)
    parts = [
        part.strip()
        for part in re.split(r"\n\s*\n", normalized)
        if part.strip()
    ]
    if len(parts) == 1:
        parts = [line.strip() for line in normalized.splitlines() if line.strip()]
    return [
        DocumentBlock(
            locator=f"{prefix}-{index}",
            block_type="paragraph",
            text=part,
        )
        for index, part in enumerate(parts, start=1)
    ]


def _extract_spreadsheet(path: Path) -> list[DocumentBlock]:
    """xlsx/xlsm：直接读 zip 里的 XML，不依赖 openpyxl。"""
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as archive:
        try:
            shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = [
                "".join(node.text or "" for node in item.iter(f"{namespace}t"))
                for item in shared_root.findall(f"{namespace}si")
            ]
        except KeyError:
            shared = []

        names: list[str] = []
        try:
            workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            names = [
                sheet.get("name") or f"sheet{index}"
                for index, sheet in enumerate(
                    workbook_root.iter(f"{namespace}sheet"), start=1
                )
            ]
        except KeyError:
            pass

        sheet_names = sorted(
            (
                name
                for name in archive.namelist()
                if re.match(r"xl/worksheets/sheet\d+\.xml$", name)
            ),
            key=lambda name: int(re.search(r"(\d+)", name).group(1)),
        )

        blocks: list[DocumentBlock] = []
        for index, sheet_name in enumerate(sheet_names, start=1):
            root = ElementTree.fromstring(archive.read(sheet_name))
            rows: list[str] = []
            for row in root.iter(f"{namespace}row"):
                cells: list[str] = []
                for cell in row.findall(f"{namespace}c"):
                    value = cell.find(f"{namespace}v")
                    if value is not None and value.text is not None:
                        text = value.text
                        if cell.get("t") == "s":
                            try:
                                text = shared[int(text)]
                            except (ValueError, IndexError):
                                pass
                        cells.append(str(text).strip())
                        continue
                    inline = cell.find(f"{namespace}is")
                    if inline is not None:
                        text = "".join(
                            node.text or "" for node in inline.iter(f"{namespace}t")
                        ).strip()
                        if text:
                            cells.append(text)
                cells = [item for item in cells if item]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                title = names[index - 1] if index - 1 < len(names) else f"sheet{index}"
                blocks.append(
                    DocumentBlock(
                        locator=f"sheet-{index}",
                        block_type="table",
                        text=f"[工作表 {title}]\n" + "\n".join(rows),
                    )
                )
    return blocks


def _extract_slides(path: Path) -> list[DocumentBlock]:
    """pptx：直接读 zip 里的 slide XML，不依赖 python-pptx。"""
    namespace = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    with zipfile.ZipFile(path) as archive:
        slides = sorted(
            (
                name
                for name in archive.namelist()
                if re.match(r"ppt/slides/slide\d+\.xml$", name)
            ),
            key=lambda name: int(re.search(r"(\d+)", name).group(1)),
        )
        blocks: list[DocumentBlock] = []
        for index, slide_name in enumerate(slides, start=1):
            root = ElementTree.fromstring(archive.read(slide_name))
            texts = [
                node.text.strip()
                for node in root.iter(f"{namespace}t")
                if node.text and node.text.strip()
            ]
            if texts:
                blocks.append(
                    DocumentBlock(
                        locator=f"slide-{index}",
                        block_type="paragraph",
                        text=f"[第 {index} 页]\n" + "\n".join(texts),
                    )
                )
    return blocks


class _HtmlTextCollector(HTMLParser):
    BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "td", "section"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self.skip_depth += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def _extract_html(path: Path) -> list[DocumentBlock]:
    collector = _HtmlTextCollector()
    collector.feed(_decode_text(path.read_bytes()))
    collector.close()
    raw = "".join(collector.parts)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    return [
        DocumentBlock(
            locator=f"html-line-{index}",
            block_type="paragraph",
            text=line,
        )
        for index, line in enumerate(lines, start=1)
    ]


def _extract_rtf(path: Path) -> list[DocumentBlock]:
    """rtf：去掉控制字，尽量还原成纯文本。"""
    raw = path.read_bytes().decode("latin-1", "ignore")

    def _hex_char(match: re.Match[str]) -> str:
        try:
            return bytes([int(match.group(1), 16)]).decode("gb18030", "ignore")
        except ValueError:
            return ""

    raw = re.sub(r"\\'([0-9a-fA-F]{2})", _hex_char, raw)
    raw = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), raw)
    raw = re.sub(r"\\(?:par|line)\b ?", "\n", raw)
    raw = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", raw)
    raw = raw.replace("{", "").replace("}", "")
    raw = raw.replace("\\\\", "\\").replace("\\{", "{").replace("\\}", "}")
    return _text_blocks(raw, "rtf-block")


def extract_document(path: Path, suffix: str) -> ExtractedDocument:
    normalized_suffix = suffix.lower()
    note: str | None = None
    try:
        if normalized_suffix in TEXT_SUFFIXES:
            blocks = _text_blocks(_decode_text(path.read_bytes()))
        elif normalized_suffix in DOCX_SUFFIXES:
            blocks = _extract_docx(path)
        elif normalized_suffix in DOC_SUFFIXES:
            from app.legacy_doc import extract_doc_text

            text, method = extract_doc_text(path.read_bytes())
            blocks = _text_blocks(text, "doc-block")
            if method != "piece-table":
                note = "旧版 .doc 用兜底扫描提取，可能混入格式噪声，建议核对"
        elif normalized_suffix in PDF_SUFFIXES:
            blocks = _extract_pdf(path)
        elif normalized_suffix in IMAGE_SUFFIXES:
            blocks = _extract_image(path)
        elif normalized_suffix in SPREADSHEET_SUFFIXES:
            blocks = _extract_spreadsheet(path)
        elif normalized_suffix in SLIDES_SUFFIXES:
            blocks = _extract_slides(path)
        elif normalized_suffix in HTML_SUFFIXES:
            blocks = _extract_html(path)
        elif normalized_suffix in RTF_SUFFIXES:
            blocks = _extract_rtf(path)
        else:
            raise ValueError("Unsupported file type")
    except Exception as error:
        return ExtractedDocument(
            status="failed",
            text=None,
            note=f"Text extraction failed: {error}",
        )

    text = "\n\n".join(block.text for block in blocks).strip()
    if not text:
        return ExtractedDocument(
            status="failed",
            text=None,
            note="No readable text was found in the document",
        )
    return ExtractedDocument(
        status="processed",
        text=text,
        note=note,
        blocks=blocks,
    )
