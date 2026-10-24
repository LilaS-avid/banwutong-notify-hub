from __future__ import annotations

import re
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json"}
DOCX_SUFFIXES = {".docx"}
PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_SUFFIXES = TEXT_SUFFIXES | DOCX_SUFFIXES | PDF_SUFFIXES | IMAGE_SUFFIXES
OCR_SCORE_THRESHOLD = 0.3

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


def _extract_pdf(path: Path) -> list[DocumentBlock]:
    reader = PdfReader(str(path))
    blocks: list[DocumentBlock] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            blocks.append(
                DocumentBlock(
                    locator=f"page-{index}",
                    block_type="page",
                    text=text,
                )
            )
    return blocks


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def _extract_image(path: Path) -> list[DocumentBlock]:
    with _OCR_LOCK:
        engine = _get_ocr_engine()
        result, _ = engine(str(path))
    lines: list[str] = []
    for item in result or []:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        text = str(item[1]).strip()
        try:
            score = float(item[2])
        except (TypeError, ValueError):
            score = 0.0
        if text and score >= OCR_SCORE_THRESHOLD:
            lines.append(text)
    return [
        DocumentBlock(
            locator=f"ocr-line-{index}",
            block_type="ocr_line",
            text=text,
        )
        for index, text in enumerate(lines, start=1)
    ]


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
