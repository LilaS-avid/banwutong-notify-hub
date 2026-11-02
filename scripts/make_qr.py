"""生成网页入口 / 访客上传页的二维码（可选小工具，运行时不需要）。

依赖：`pip install qrcode[pil]`（Pillow 主项目已经装了）。

用法：

    python -m scripts.make_qr --url "http://10.2.0.3:8765/?guest=1" --out docs/qr-guest-upload.png
    python -m scripts.make_qr --url "http://10.2.0.3:8765/" --out docs/qr-home.png

注意：二维码里存的是**写死当时的地址**。换了网段、换了机器，要重新生成。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def make(url: str, out: Path, box: int = 10, border: int = 2) -> Path:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box, border=border)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="把网址生成二维码 PNG")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--box", type=int, default=10, help="每个码元的像素数")
    args = parser.parse_args()

    path = make(args.url, Path(args.out), box=args.box)
    print(f"已生成 {path}（内容：{args.url}）")


if __name__ == "__main__":
    main()
