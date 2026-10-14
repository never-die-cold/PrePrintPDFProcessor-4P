#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 README 用的效果对比图（全部来自合成样本，不含任何课程资料）。

运行：python docs/make_images.py
输出：docs/images/*.png
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PACK = os.path.join(REPO, "plugins", "pdf-print-pack", "skills", "pdf-print-pack",
                    "scripts", "pack.py")
OUT_DIR = os.path.join(HERE, "images")
MM = 72 / 25.4


def make_slides(path: str, slides: int = 6) -> None:
    """合成课件：深蓝标题条 + 标题 + 几条正文（16:9）。"""
    doc = pymupdf.open()
    for k in range(1, slides + 1):
        page = doc.new_page(width=960, height=540)
        page.draw_rect(pymupdf.Rect(0, 0, 960, 90), fill=(0.16, 0.25, 0.45))
        page.insert_text((50, 60), f"第 {k} 讲 · 示例章节标题", fontsize=30,
                         color=(1, 1, 1), fontname="china-s")
        y = 170
        for line in range(6):
            page.insert_text((70, y), f"要点 {line + 1}：这里是课件正文，"
                                      f"换页时会连同标题一起排版。", fontsize=17,
                             fontname="china-s")
            y += 45
        page.draw_rect(pymupdf.Rect(70, y + 10, 890, y + 90), color=(0.6, 0.6, 0.6))
        page.insert_text((90, y + 55), "示意图占位框", fontsize=15,
                         color=(0.4, 0.4, 0.4), fontname="china-s")
    doc.save(path)
    doc.close()


def make_notes(path: str, pages: int = 8) -> None:
    """合成竖版讲义：标题 + 正文段落（A4 竖版）。"""
    doc = pymupdf.open()
    for k in range(1, pages + 1):
        page = doc.new_page(width=210 * MM, height=297 * MM)
        page.insert_text((60, 80), f"第 {k} 页 · 复习笔记", fontsize=18,
                         fontname="china-s")
        y = 120
        for para in range(14):
            page.insert_text((60, y), "这里是笔记正文，用于演示 2 合 1 拼版后的效果，"
                                      "内容会被缩到 A5 大小并排两页。", fontsize=10,
                             fontname="china-s")
            y += 26
    doc.save(path)
    doc.close()


def make_scan(path: str) -> None:
    """合成“扫描件”：灰底 + 倾斜的深色文字。"""
    from PIL import Image, ImageDraw
    width, height = 1240, 1754
    img = Image.new("L", (width, height), 208)
    draw = ImageDraw.Draw(img)
    for row in range(14):
        y = 180 + row * 95
        draw.rectangle([140, y, 1080, y + 34], fill=55)
    img = img.rotate(2.5, resample=Image.Resampling.BICUBIC, fillcolor=208)
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=210 * MM, height=297 * MM)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    doc.close()


def run_pack(args) -> None:
    proc = subprocess.run([sys.executable, PACK] + list(args),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"pack.py 失败：{proc.stderr}")


def out_path(name: str) -> str:
    return os.path.join(OUT_DIR, name)


def render_pair(before_pdf: str, before_page: int, after_pdf: str, after_page: int,
                target: str, dpi_before: int = 70, dpi_after: int = 100) -> None:
    """把「处理前的一页」和「处理后的一张」并排拼成一张 PNG。"""
    from PIL import Image
    left = pymupdf.open(before_pdf)[before_page].get_pixmap(dpi=dpi_before)
    right = pymupdf.open(after_pdf)[after_page].get_pixmap(dpi=dpi_after)
    left_img = Image.frombytes("RGB", (left.width, left.height), left.samples)
    right_img = Image.frombytes("RGB", (right.width, right.height), right.samples)
    height = 760
    left_img = left_img.resize((int(left_img.width * height / left_img.height), height),
                               Image.Resampling.LANCZOS)
    right_img = right_img.resize((int(right_img.width * height / right_img.height), height),
                                 Image.Resampling.LANCZOS)
    gap = 24
    canvas = Image.new("RGB", (left_img.width + right_img.width + gap * 3, height + gap * 2),
                       (245, 245, 248))
    canvas.paste(left_img, (gap, gap))
    canvas.paste(right_img, (left_img.width + gap * 2, gap))
    canvas.save(target, optimize=True)


def main() -> int:
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("需要 Pillow：pip install pillow", file=sys.stderr)
        return 2
    os.makedirs(OUT_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        slides = os.path.join(td, "合成课件.pdf")
        notes = os.path.join(td, "合成笔记.pdf")
        scan = os.path.join(td, "合成扫描.pdf")
        make_slides(slides)
        make_notes(notes)
        make_scan(scan)

        packed_slides = os.path.join(td, "课件_省纸打印版.pdf")
        run_pack([slides, "-o", packed_slides, "--nup", "3", "--frame", "thin",
                  "--pad-duplex", "--fast"])
        render_pair(slides, 0, packed_slides, 0, out_path("slides-3in1.png"))

        packed_notes = os.path.join(td, "笔记_省纸打印版.pdf")
        run_pack([notes, "-o", packed_notes, "--nup", "2", "--footer", "auto", "--fast"])
        render_pair(notes, 0, packed_notes, 0, out_path("notes-2in1.png"))

        booklet = os.path.join(td, "笔记_小册子.pdf")
        run_pack([notes, "-o", booklet, "--booklet", "--gutter", "6", "--fast"])
        doc = pymupdf.open(booklet)
        doc[0].get_pixmap(dpi=100).save(out_path("booklet.png"))
        doc.close()

        scan_gray = os.path.join(td, "扫描_原样.pdf")
        scan_fixed = os.path.join(td, "扫描_清理后.pdf")
        run_pack([scan, "-o", scan_gray, "--nup", "2", "--gray-raster", "--fast"])
        run_pack([scan, "-o", scan_fixed, "--nup", "2", "--enhance", "--deskew", "--fast"])
        render_pair(scan_gray, 0, scan_fixed, 0, out_path("scan-enhance.png"),
                    dpi_before=100, dpi_after=100)

        handout = os.path.join(REPO, "plugins", "pdf-print-pack", "skills",
                               "pdf-print-pack", "assets", "handout-skeleton.html")
        handout_pdf = os.path.join(td, "讲义主题.pdf")
        subprocess.run([sys.executable, os.path.join(
            REPO, "plugins", "pdf-print-pack", "skills", "pdf-print-pack",
            "scripts", "html2pdf.py"), handout, "-o", handout_pdf],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if os.path.exists(handout_pdf):
            doc = pymupdf.open(handout_pdf)
            doc[0].get_pixmap(dpi=100).save(out_path("handout-theme.png"))
            doc.close()

    for name in sorted(os.listdir(OUT_DIR)):
        print(f"  {name:24} {os.path.getsize(os.path.join(OUT_DIR, name)) // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
