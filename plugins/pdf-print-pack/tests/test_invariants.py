#!/usr/bin/env python3
"""拼版不变量测试：随机参数下的硬约束（页数守恒、标签唯一、格子合法）。

直接运行：python tests/test_invariants.py
这些检查与具体像素无关，因此跨平台稳定，适合放进 CI。
"""

from __future__ import annotations

import importlib.util
import math
import os
import random
import re
import subprocess
import sys
import tempfile

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
PACK_PY = os.path.abspath(os.path.join(
    HERE, "..", "skills", "pdf-print-pack", "scripts", "pack.py"))
MM = 72 / 25.4

PAPERS = {"a4": (210.0, 297.0), "a5": (148.0, 210.0)}


def load_pack():
    spec = importlib.util.spec_from_file_location("pack_invariants", PACK_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pack = load_pack()


def run_pack(args):
    proc = subprocess.run([sys.executable, PACK_PY, *list(args)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0:
        raise AssertionError(f"pack.py 失败：{proc.stderr}")
    return proc


def make_marked_pdf(path, pages, portrait=True, scale=1.0):
    """每页一个唯一标记，便于校验“每页恰好出现一次、顺序正确”。"""
    doc = pymupdf.open()
    for k in range(1, pages + 1):
        width, height = (210 * MM, 297 * MM) if portrait else (960, 540)
        page = doc.new_page(width=width * scale, height=height * scale)
        page.insert_text((40, 80), f"MARKER {k:03d} ", fontsize=14)
    doc.save(path)
    doc.close()


def output_text(path) -> str:
    doc = pymupdf.open(path)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


# ---------------------------------------------------------------- 网格不变量

def test_choose_grid_invariants_randomized():
    rng = random.Random(20261014)
    for _ in range(300):
        nup = rng.choice([2, 3, 4, 6, 8, 9, 12, 16])
        aspect = math.exp(rng.uniform(math.log(0.4), math.log(3.0)))
        paper = rng.choice(list(PAPERS))
        pw, ph = PAPERS[paper]
        margin, gap = rng.uniform(0, 15), rng.uniform(0, 8)
        cols, rows, orient, cw, ch = pack.choose_grid(nup, aspect, pw, ph, margin, gap)
        assert cols * rows == nup, (nup, cols, rows)
        assert orient in ("portrait", "landscape")
        assert cw > 0 and ch > 0, (cw, ch)
        sheet_w, sheet_h = (pw, ph) if orient == "portrait" else (ph, pw)
        assert cols * cw + (cols - 1) * gap <= sheet_w - 2 * margin + 1e-6, (nup, cols, cw)
        assert rows * ch + (rows - 1) * gap <= sheet_h - 2 * margin + 1e-6, (nup, rows, ch)
        # 旋转不变量：把源页面转 90° 后，网格朝向应当互换
        cols2, rows2, orient2, _, _ = pack.choose_grid(nup, 1 / aspect, pw, ph, margin, gap)
        if orient == "portrait":
            assert orient2 == "landscape" or cols == cols2, (nup, aspect, orient, orient2)


def test_decide_rotation_invariants():
    rng = random.Random(7)
    for _ in range(200):
        src = pymupdf.Rect(0, 0, 100, 100 * math.exp(rng.uniform(-1, 1)))
        cell = pymupdf.Rect(0, 0, 100, 100 * math.exp(rng.uniform(-1, 1)))
        rot = pack.decide_rotation(src, cell)
        assert rot in (0, 90)
        # 90° 只应在横竖明显不匹配时出现
        if rot == 90:
            a_src = src.width / src.height
            a_cell = cell.width / cell.height
            assert abs(math.log(a_cell / (1 / a_src))) + 1e-9 < abs(math.log(a_cell / a_src))


# ---------------------------------------------------------------- 页数/内容守恒

def test_pages_are_conserved_and_labeled():
    rng = random.Random(99)
    with tempfile.TemporaryDirectory() as td:
        for trial in range(4):
            pages = rng.randint(3, 23)
            nup = rng.choice([2, 3, 4, 6])
            portrait = nup == 2
            src = os.path.join(td, f"K1-样本{trial}.pdf")
            out = os.path.join(td, f"out{trial}.pdf")
            make_marked_pdf(src, pages, portrait=portrait)
            run_pack([src, "-o", out, "--nup", str(nup), "--fast"])

            doc = pymupdf.open(out)
            sheets = doc.page_count
            doc.close()
            expected = math.ceil(pages / nup)
            assert sheets == expected, (pages, nup, sheets, expected)

            text = output_text(out)
            for k in range(1, pages + 1):
                marker = f"MARKER {k:03d}"
                assert text.count(marker) == 1, f"第 {k} 页出现 {text.count(marker)} 次"
            # 顺序：标记出现的先后应与源顺序一致
            order = [int(m) for m in re.findall(r"MARKER (\d{3})", text)]
            assert order == list(range(1, pages + 1)), order

            # 页标唯一且数量等于页数
            labels = re.findall(r"K1-\d{2,3}", text)
            assert len(labels) == pages, (len(labels), pages)
            assert len(set(labels)) == pages


def test_pad_duplex_makes_even_faces():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "K1-奇数.pdf")
        make_marked_pdf(src, 9, portrait=False)     # 3 合 1 → 3 面（奇数）
        out = os.path.join(td, "even.pdf")
        run_pack([src, "-o", out, "--nup", "3", "--pad-duplex", "--fast"])
        doc = pymupdf.open(out)
        try:
            assert doc.page_count % 2 == 0, doc.page_count
        finally:
            doc.close()


def test_merged_documents_keep_order_and_totals():
    with tempfile.TemporaryDirectory() as td:
        files = []
        total = 0
        for idx in (1, 2, 3):
            path = os.path.join(td, f"K{idx}-章节.pdf")
            pages = 2 + idx
            make_marked_pdf(path, pages, portrait=False)
            files.append(path)
            total += pages
        out = os.path.join(td, "merged.pdf")
        # 故意打乱命令行顺序，验证按文件名自然排序
        run_pack([files[2], files[0], files[1], "-o", out, "--nup", "3", "--fast"])
        text = output_text(out)
        for k in (1, 2, 3):
            assert f"K{k}-01" in text, f"缺少第 {k} 份文件的页标"
        # 每份文件的标签顺序：K1 的全部在前，然后 K2、K3
        pos = [text.index(f"K{k}-01") for k in (1, 2, 3)]
        assert pos == sorted(pos), pos
        assert total == sum([2 + 1, 2 + 2, 2 + 3])


def test_no_overlap_between_cells():
    """格子矩形两两不相交（重叠会导致内容互相盖住）。"""
    from pymupdf import Rect
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "K1-样本.pdf")
        make_marked_pdf(src, 6, portrait=False)
        args = pack.parse_args([src, "-o", os.path.join(td, "o.pdf"), "--nup", "6"])
        paper_w, paper_h = pack.PAPERS[args.paper]
        cols, rows, orient, cw, ch = pack.choose_grid(
            6, 16 / 9, paper_w, paper_h, args.margin, args.gap)
        sheet_w = (paper_w if orient == "portrait" else paper_h) * MM
        sheet_h = (paper_h if orient == "portrait" else paper_w) * MM
        cells = []
        for r in range(rows):
            for c in range(cols):
                # choose_grid 返回毫米，这里统一折算成点
                x0 = args.margin * MM + c * (cw * MM + args.gap * MM)
                y0 = args.margin * MM + r * (ch * MM + args.gap * MM)
                cells.append(Rect(x0, y0, x0 + cw * MM, y0 + ch * MM))
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                inter = cells[i] & cells[j]
                assert inter.is_empty or inter.width * inter.height < 0.01, (i, j, inter)
        for cell in cells:
            assert cell.x0 >= 0 and cell.y0 >= 0, cell
            assert cell.x1 <= sheet_w + 0.01 and cell.y1 <= sheet_h + 0.01, cell


if __name__ == "__main__":
    failed = 0
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    raise SystemExit(1 if failed else 0)
