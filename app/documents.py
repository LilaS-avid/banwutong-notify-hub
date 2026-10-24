from __future__ import annotations

import re
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json"}
DOCX_SUFFIXES = {".docx"}
PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_SUFFIXES = TEXT_SUFFIXES | DOCX_SUFFIXES | PDF_SUFFIXES | IMAGE_SUFFIXES
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


def extract_document(path: Path, suffix: str) -> ExtractedDocument:
    normalized_suffix = suffix.lower()
    try:
        if normalized_suffix in TEXT_SUFFIXES:
            blocks = _text_blocks(_decode_text(path.read_bytes()))
        elif normalized_suffix in DOCX_SUFFIXES:
            blocks = _extract_docx(path)
        elif normalized_suffix in PDF_SUFFIXES:
            blocks = _extract_pdf(path)
        elif normalized_suffix in IMAGE_SUFFIXES:
            blocks = _extract_image(path)
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
        note=None,
        blocks=blocks,
    )
