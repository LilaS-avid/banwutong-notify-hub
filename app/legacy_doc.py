"""旧版 .doc（Word 97-2003 二进制格式）的文本提取。

.doc 是 OLE2 复合文档：文本不在 XML 里，而在 "WordDocument" 流中，
靠 FIB 里的 piece table（CLX）描述每段文本的字节区间和编码。

这里用标准库实现两层：
1. 正规路径：解析复合文档 → 读 FIB → 解析 piece table → 拼出正文；
2. 兜底路径：正规解析失败时，按 UTF-16LE 扫描可打印字符，尽量捞出正文。

注意：兜底结果可能混入格式噪声，只在前一条路走不通时使用。
"""
from __future__ import annotations

import struct

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
END_OF_CHAIN = 0xFFFFFFFE
FREE_SECTOR = 0xFFFFFFFF
FIB_CLX_OFFSET = 0x01A2
FIB_FLAGS_OFFSET = 0x0A
FLAG_TABLE_STREAM = 0x0200


def _read_compound_streams(data: bytes) -> dict[str, bytes]:
    if data[:8] != OLE_SIGNATURE:
        raise ValueError("not an OLE compound document")
    if len(data) < 512:
        raise ValueError("compound document is truncated")

    sector_size = 1 << struct.unpack_from("<H", data, 0x1E)[0]
    mini_size = 1 << struct.unpack_from("<H", data, 0x20)[0]
    fat_count = struct.unpack_from("<I", data, 0x2C)[0]
    dir_start = struct.unpack_from("<I", data, 0x30)[0]
    mini_cutoff = struct.unpack_from("<I", data, 0x38)[0]
    mini_fat_start = struct.unpack_from("<I", data, 0x3C)[0]
    difat_start = struct.unpack_from("<I", data, 0x44)[0]

    difat = list(struct.unpack_from("<109I", data, 0x4C))
    sector = difat_start
    guard = 0
    while sector not in (END_OF_CHAIN, FREE_SECTOR) and guard < 4096:
        guard += 1
        offset = (sector + 1) * sector_size
        if offset + sector_size > len(data):
            break
        entries = struct.unpack_from(f"<{sector_size // 4 - 1}I", data, offset)
        difat.extend(entries)
        sector = struct.unpack_from("<I", data, offset + sector_size - 4)[0]

    fat: list[int] = []
    for sector in [value for value in difat if value != FREE_SECTOR][:fat_count]:
        offset = (sector + 1) * sector_size
        if offset + sector_size > len(data):
            continue
        fat.extend(struct.unpack_from(f"<{sector_size // 4}I", data, offset))

    def chain(start: int) -> list[int]:
        result: list[int] = []
        seen: set[int] = set()
        while start not in (END_OF_CHAIN, FREE_SECTOR) and start not in seen:
            seen.add(start)
            result.append(start)
            start = fat[start] if start < len(fat) else END_OF_CHAIN
        return result

    def read_chain(start: int, size: int | None = None) -> bytes:
        chunks = []
        for sector in chain(start):
            offset = (sector + 1) * sector_size
            chunks.append(data[offset : offset + sector_size])
        blob = b"".join(chunks)
        return blob[:size] if size is not None else blob

    directory = read_chain(dir_start)
    entries: list[tuple[str, int, int, int]] = []
    for index in range(0, len(directory), 128):
        entry = directory[index : index + 128]
        if len(entry) < 128:
            break
        name_length = struct.unpack_from("<H", entry, 0x40)[0]
        name = entry[: max(0, name_length - 2)].decode("utf-16-le", "ignore")
        entry_type = entry[0x42]
        start = struct.unpack_from("<I", entry, 0x74)[0]
        size = struct.unpack_from("<I", entry, 0x78)[0]
        entries.append((name, entry_type, start, size))

    root = next((entry for entry in entries if entry[1] == 5), None)
    mini_stream = read_chain(root[2], root[3]) if root else b""
    mini_fat: list[int] = []
    if mini_fat_start not in (END_OF_CHAIN, FREE_SECTOR):
        blob = read_chain(mini_fat_start)
        mini_fat = list(struct.unpack_from(f"<{len(blob) // 4}I", blob, 0)) if blob else []

    def read_mini(start: int, size: int) -> bytes:
        parts = []
        seen: set[int] = set()
        sector = start
        while sector not in (END_OF_CHAIN, FREE_SECTOR) and sector not in seen:
            seen.add(sector)
            offset = sector * mini_size
            parts.append(mini_stream[offset : offset + mini_size])
            sector = mini_fat[sector] if sector < len(mini_fat) else END_OF_CHAIN
        return b"".join(parts)[:size]

    streams: dict[str, bytes] = {}
    for name, entry_type, start, size in entries:
        if entry_type != 2:
            continue
        streams[name] = (
            read_mini(start, size) if size < mini_cutoff else read_chain(start, size)
        )
    return streams


def _piece_table_text(word: bytes, table: bytes) -> str:
    flags = struct.unpack_from("<H", word, FIB_FLAGS_OFFSET)[0]
    fc_clx, lcb_clx = struct.unpack_from("<II", word, FIB_CLX_OFFSET)
    clx = table[fc_clx : fc_clx + lcb_clx]
    if not clx:
        raise ValueError("empty CLX")

    position = 0
    piece_data: bytes | None = None
    while position < len(clx):
        kind = clx[position]
        if kind == 0x01:
            size = struct.unpack_from("<H", clx, position + 1)[0]
            position += 3 + size
        elif kind == 0x02:
            size = struct.unpack_from("<I", clx, position + 1)[0]
            piece_data = clx[position + 5 : position + 5 + size]
            break
        else:
            break
    if not piece_data:
        raise ValueError("piece table not found")

    count = (len(piece_data) - 4) // 12
    if count <= 0:
        raise ValueError("piece table is empty")
    positions = struct.unpack_from(f"<{count + 1}I", piece_data, 0)
    base = 4 * (count + 1)

    pieces: list[str] = []
    for index in range(count):
        offset_in_table = base + 8 * index
        fc = struct.unpack_from("<I", piece_data, offset_in_table + 2)[0]
        compressed = bool(fc & 0x40000000)
        start = (fc & 0x3FFFFFFF) // 2 if compressed else fc
        length = positions[index + 1] - positions[index]
        if compressed:
            raw = word[start : start + length]
            pieces.append(raw.decode("cp1252", "ignore"))
        else:
            raw = word[start : start + length * 2]
            pieces.append(raw.decode("utf-16-le", "ignore"))
    return "".join(pieces)


def _heuristic_text(data: bytes) -> str:
    decoded = data.decode("utf-16-le", "ignore")
    cleaned = "".join(
        character if character.isprintable() or character in "\n\r\t" else "\n"
        for character in decoded
    )
    lines = [line.strip() for line in cleaned.splitlines()]
    return "\n".join(line for line in lines if len(line) >= 4)


def extract_doc_text(data: bytes) -> tuple[str, str]:
    """返回 (文本, 提取方式)。提取方式为 'piece-table' 或 'utf16-scan'。"""
    try:
        streams = _read_compound_streams(data)
        word = streams.get("WordDocument")
        if not word:
            raise ValueError("缺少 WordDocument 流")
        flags = struct.unpack_from("<H", word, FIB_FLAGS_OFFSET)[0]
        table = streams.get("1Table" if flags & FLAG_TABLE_STREAM else "0Table")
        if not table:
            raise ValueError("缺少 Table 流")
        text = _piece_table_text(word, table)
        text = text.replace("\r", "\n").replace("\x07", "\n").replace("\x0b", "\n")
        if text.strip():
            return text, "piece-table"
        raise ValueError("piece table 没有解出文本")
    except (ValueError, struct.error, IndexError):
        return _heuristic_text(data), "utf16-scan"
