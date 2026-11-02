"""更多文件类型：xlsx / pptx / html / rtf 先转成文本再解析。

xlsx / pptx 用 zipfile + XML 直接解析（和项目里 docx 的做法一致），
所以测试用最小化的 zip 构造样本，不依赖 openpyxl / python-pptx。
"""
import zipfile

from app.documents import extract_document

SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _write_xlsx(path, sheets):
    """sheets: [(name, [[cell, cell, ...], ...])]"""
    shared: list[str] = []
    sheet_xml_parts = []

    workbook_sheets = []
    for index, (name, rows) in enumerate(sheets, start=1):
        workbook_sheets.append(
            f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>'
        )
        row_parts = []
        for row_index, row in enumerate(rows, start=1):
            cells = []
            for col_index, value in enumerate(row):
                shared.append(str(value))
                ref = f"{chr(65 + col_index)}{row_index}"
                cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
            row_parts.append(f'<row r="{row_index}">{"".join(cells)}</row>')
        sheet_xml_parts.append(
            f'<worksheet xmlns="{SPREADSHEET_NS}"><sheetData>'
            + "".join(row_parts)
            + "</sheetData></worksheet>"
        )

    workbook_xml = (
        f'<workbook xmlns="{SPREADSHEET_NS}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>" + "".join(workbook_sheets) + "</sheets></workbook>"
    )
    shared_xml = (
        f'<sst xmlns="{SPREADSHEET_NS}">'
        + "".join(f"<si><t>{value}</t></si>" for value in shared)
        + "</sst>"
    )

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        for index, xml in enumerate(sheet_xml_parts, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", xml)


def _write_pptx(path, slides):
    """slides: [[line, line, ...]]"""
    with zipfile.ZipFile(path, "w") as archive:
        for index, lines in enumerate(slides, start=1):
            paragraphs = "".join(
                f"<a:p><a:r><a:t>{line}</a:t></a:r></a:p>" for line in lines
            )
            xml = (
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                f'xmlns:a="{DRAWING_NS}"><p:cSld><p:spTree><p:sp><p:txBody>'
                + paragraphs
                + "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
            )
            archive.writestr(f"ppt/slides/slide{index}.xml", xml)


def test_html_is_converted_to_text(tmp_path) -> None:
    path = tmp_path / "notice.html"
    path.write_text(
        """
        <html><head><style>body{color:red}</style><script>alert(1)</script></head>
        <body>
          <h1>关于举办讲座的通知</h1>
          <p>时间：11月8日下午两点</p>
          <p>地点：图书馆报告厅</p>
        </body></html>
        """,
        encoding="utf-8",
    )
    result = extract_document(path, ".html")
    assert result.status == "processed"
    assert "关于举办讲座的通知" in result.text
    assert "图书馆报告厅" in result.text
    assert "alert" not in result.text
    assert "color:red" not in result.text


def test_rtf_is_converted_to_text(tmp_path) -> None:
    path = tmp_path / "notice.rtf"
    path.write_text(
        r"{\rtf1\ansi\deff0 {\fonttbl {\f0 SimSun;}}\f0\fs24 "
        r"\u20851?\u20110?\u20030?\u21150? \par "
        r"deadline 2026-11-08\par}",
        encoding="ascii",
    )
    result = extract_document(path, ".rtf")
    assert result.status == "processed"
    assert "deadline 2026-11-08" in result.text


def test_xlsx_is_converted_to_text(tmp_path) -> None:
    path = tmp_path / "notice.xlsx"
    _write_xlsx(
        path,
        [
            (
                "报名表",
                [
                    ["活动名称", "报名截止", "地点"],
                    ["创新大赛", "2026-11-05 18:00", "体育馆"],
                ],
            )
        ],
    )
    result = extract_document(path, ".xlsx")
    assert result.status == "processed"
    assert "报名表" in result.text
    assert "创新大赛" in result.text
    assert "2026-11-05 18:00" in result.text
    assert "体育馆" in result.text


def test_pptx_is_converted_to_text(tmp_path) -> None:
    path = tmp_path / "notice.pptx"
    _write_pptx(path, [["奖学金申请说明", "截止时间：2026-11-10 17:00"]])
    result = extract_document(path, ".pptx")
    assert result.status == "processed"
    assert "奖学金申请说明" in result.text
    assert "2026-11-10 17:00" in result.text


def test_unknown_binary_still_fails_cleanly(tmp_path) -> None:
    path = tmp_path / "archive.zip"
    path.write_bytes(b"PK\x03\x04binary")
    result = extract_document(path, ".zip")
    assert result.status == "failed"
    assert "Unsupported file type" in (result.note or "")


def test_legacy_doc_falls_back_to_utf16_scan(tmp_path) -> None:
    """真实 .doc 的 OLE 结构这里不构造，只验证兜底路径能捞出中文正文。"""
    from app.legacy_doc import extract_doc_text

    body = "关于举办讲座的通知\r\n时间：11月8日下午两点\r\n地点：图书馆报告厅"
    payload = b"\x00" * 64 + body.encode("utf-16-le") + b"\x00" * 64

    text, method = extract_doc_text(payload)
    assert method == "utf16-scan"
    assert "关于举办讲座的通知" in text
    assert "图书馆报告厅" in text


def test_legacy_doc_file_is_processed(tmp_path) -> None:
    path = tmp_path / "notice.doc"
    body = "关于举办读书会的通知\r\n时间：11月15日下午3点"
    path.write_bytes(b"\x00" * 32 + body.encode("utf-16-le") + b"\x00" * 32)

    result = extract_document(path, ".doc")
    assert result.status == "processed"
    assert "关于举办读书会的通知" in result.text
    # 兜底提取要留下提示，提醒人工核对
    assert result.note is not None
    assert "兜底" in result.note
