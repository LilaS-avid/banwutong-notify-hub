from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageDraw

import app.documents as documents_module
from app.documents import extract_document


def test_docx_extracts_paragraphs_and_tables(tmp_path) -> None:
    path = tmp_path / "notice.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document
  xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>活动名称：创新大赛</w:t></w:r></w:p>
    <w:p><w:r><w:t>报名截止：2026-11-05 18:00</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>材料</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>报名表</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>"""
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)

    extracted = extract_document(path, ".docx")

    assert extracted.status == "processed"
    assert [block.block_type for block in extracted.blocks] == [
        "paragraph",
        "paragraph",
        "table",
    ]
    assert "创新大赛" in extracted.text
    assert "报名表" in extracted.text


def test_plain_text_is_split_into_blocks(tmp_path) -> None:
    path = tmp_path / "notice.txt"
    path.write_text("第一段\n\n第二段", encoding="utf-8")

    extracted = extract_document(path, ".txt")

    assert len(extracted.blocks) == 2
    assert extracted.blocks[0].locator == "block-1"
    assert extracted.text == "第一段\n\n第二段"


def test_image_ocr_returns_ordered_blocks(monkeypatch, tmp_path) -> None:
    path = tmp_path / "notice.png"
    path.write_bytes(b"fake image")

    class FakeOcr:
        def __call__(self, image_path: str):
            assert image_path == str(path)
            return (
                [
                    [[[0, 0], [1, 0], [1, 1], [0, 1]], "活动名称：图片通知", 0.91],
                    [[[0, 2], [1, 2], [1, 3], [0, 3]], "报名截止：2026-11-05", 0.90],
                ],
                None,
            )

    monkeypatch.setattr(documents_module, "_OCR_ENGINE", FakeOcr())

    extracted = extract_document(path, ".png")

    assert extracted.status == "processed"
    assert [block.locator for block in extracted.blocks] == [
        "ocr-line-1",
        "ocr-line-2",
    ]
    assert "图片通知" in extracted.text


def test_scanned_pdf_is_ocr_processed_page_by_page(monkeypatch, tmp_path) -> None:
    path = tmp_path / "scanned.pdf"
    pages = []
    for label in ("first", "second"):
        image = Image.new("RGB", (600, 240), "white")
        draw = ImageDraw.Draw(image)
        draw.text((30, 80), label, fill="black")
        pages.append(image)
    pages[0].save(path, save_all=True, append_images=pages[1:], resolution=150)

    class FakeOcr:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, image) -> tuple:
            self.calls += 1
            return (
                [[[[0, 0], [1, 0], [1, 1], [0, 1]], f"page-{self.calls}", 0.95]],
                None,
            )

    fake = FakeOcr()
    monkeypatch.setattr(documents_module, "_OCR_ENGINE", fake)

    extracted = extract_document(path, ".pdf")

    assert extracted.status == "processed"
    assert fake.calls == 2
    assert [block.locator for block in extracted.blocks] == [
        "page-1-ocr-line-1",
        "page-2-ocr-line-1",
    ]


def test_ocr_merges_overlapping_row_boxes(monkeypatch, tmp_path) -> None:
    path = tmp_path / "notice.png"
    path.write_bytes(b"fake image")

    class FakeOcr:
        def __call__(self, image_path: str):
            return (
                [
                    [[[0, 0], [100, 0], [100, 20], [0, 20]], "报名截止：2026-11-0518:00", 0.95],
                    [[[0, 40], [80, 40], [80, 60], [0, 60]], "适用对象：全", 0.94],
                    [[[70, 40], [180, 40], [180, 60], [70, 60]], "全体学生", 0.93],
                ],
                None,
            )

    monkeypatch.setattr(documents_module, "_OCR_ENGINE", FakeOcr())

    extracted = extract_document(path, ".png")

    assert "报名截止：2026-11-05 18:00" in extracted.text
    assert "适用对象：全体学生" in extracted.text
