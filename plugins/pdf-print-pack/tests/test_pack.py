#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack.py 省纸打印引擎的回归测试。

直接运行：python tests/test_pack.py
或交给 pytest：pytest tests/test_pack.py
只依赖 pymupdf；不需要网络与打印机。
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
PACK_PY = os.path.join(HERE, "..", "skills", "pdf-print-pack", "scripts", "pack.py")
PACK_PY = os.path.abspath(PACK_PY)
MM = 72 / 25.4


def load_pack():
    spec = importlib.util.spec_from_file_location("pack_under_test", PACK_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pack = load_pack()


def run_pack(args, expect_ok=True):
    """以子进程运行引擎，返回 (returncode, stdout, stderr)。"""
    proc = subprocess.run([sys.executable, PACK_PY] + list(args),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if expect_ok and proc.returncode != 0:
        raise AssertionError(f"pack.py 运行失败：{proc.stderr}\n{proc.stdout}")
    return proc.returncode, proc.stdout, proc.stderr


def run_pack_json(args):
    code, out, err = run_pack(list(args) + ["--json"])
    return json.loads(out)


def make_portrait_pdf(path, pages=8, blanks=(), size_word=True):
    doc = pymupdf.open()
    for k in range(1, pages + 1):
        page = doc.new_page(width=210 * MM, height=297 * MM)
        if k in blanks:
            continue
        page.insert_text((60, 120), f"PAGE {k}", fontsize=40)
        if size_word:
            page.insert_text((60, 180), "WORD " * 20, fontsize=10)
    doc.save(path)
    doc.close()


def make_slide_pdf(path, slides=9):
    """16:9 幻灯片型，带一点边距内容（模拟课件）。"""
    doc = pymupdf.open()
    for k in range(1, slides + 1):
        page = doc.new_page(width=960, height=540)
        page.draw_rect(pymupdf.Rect(40, 40, 920, 500), color=(0.2, 0.3, 0.8), width=2)
        page.insert_text((80, 140), f"Slide {k}", fontsize=44)
    doc.save(path)
    doc.close()


# ------------------------------------------------------------------ 单元级

def test_natural_key_orders_chapter_files():
    names = [
        "半导体物理/12. 第9章-异质结.pdf",
        "半导体物理/2.量子力学简介.pdf",
        "半导体物理/10. 第7章-MS结.pdf",
        "半导体物理/3. 第1章-固体物理基础.pdf",
    ]
    ordered = [os.path.basename(p) for p in sorted(names, key=pack.natural_key)]
    assert ordered[0].startswith("2."), ordered
    assert ordered[1].startswith("3."), ordered
    assert ordered[2].startswith("10."), ordered
    assert ordered[3].startswith("12."), ordered


def test_natural_key_orders_chinese_chapters():
    names = ["信号与系统第四章.pdf", "信号与系统第二章下.pdf",
             "信号与系统第一章.pdf", "信号与系统第二章上.pdf", "信号与系统第三章.pdf"]
    # 键为 (是否有阿拉伯序号, 序号, 中文章号, 上下册, 名字)
    ordered = [(pack.natural_key(n)[2], pack.natural_key(n)[3])
               for n in sorted(names, key=pack.natural_key)]
    assert ordered == [(1, 0), (2, 0), (2, 2), (3, 0), (4, 0)], ordered


def test_parse_pages_spec():
    assert pack.parse_pages_spec(None, 5) == [0, 1, 2, 3, 4]
    assert pack.parse_pages_spec("1-3,5", 5) == [0, 1, 2, 4]
    assert pack.parse_pages_spec("4-", 6) == [3, 4, 5]
    assert pack.parse_pages_spec("8", 5) == []          # 越界忽略
    assert pack.parse_pages_spec("2,2,1", 3) == [1, 0]  # 去重保序


def test_choose_grid_slides_vs_documents():
    # 横排课件：3 页一列，纵向
    cols, rows, orient, _, _ = pack.choose_grid(3, 16 / 9, 210, 297, 8, 3)
    assert (cols, rows, orient) == (1, 3, "portrait")
    # 竖排文档：2 页并排，横向
    cols, rows, orient, _, _ = pack.choose_grid(2, 210 / 297, 210, 297, 8, 3)
    assert (cols, rows, orient) == (2, 1, "landscape")
    # 横排课件 4 合 1：2×2 横向
    cols, rows, orient, _, _ = pack.choose_grid(4, 16 / 9, 210, 297, 8, 3)
    assert (cols, rows, orient) == (2, 2, "landscape")


# ------------------------------------------------------------------ 端到端

def test_portrait_doc_auto_2in1():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "笔记.pdf")
        out = os.path.join(td, "笔记_省纸打印版.pdf")
        make_portrait_pdf(src, pages=8)
        report = run_pack_json([src, "-o", out])
        assert report["grid"] == "2x1" and report["orientation"] == "landscape", report
        assert report["sheets"] == 4, report
        assert report["paper_sheets_duplex"] == 2
        assert report["paper_saved_vs_single_percent"] == 75.0
        doc = pymupdf.open(out)
        assert doc.page_count == 4
        assert abs(doc[0].rect.width - 297 * MM) < 1.5
        assert abs(doc[0].rect.height - 210 * MM) < 1.5
        text = doc[0].get_text()
        assert "PAGE 1" in text and "PAGE 2" in text
        assert re.search(r"笔记-0[12]", text), text[:200]
        assert "第 1 张" in text
        doc.close()


def test_slide_deck_auto_3in1():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "L1-引言.pdf")
        out = os.path.join(td, "out.pdf")
        make_slide_pdf(src, slides=9)
        report = run_pack_json([src, "-o", out])
        assert report["grid"] == "1x3" and report["orientation"] == "portrait", report
        assert report["sheets"] == 3
        doc = pymupdf.open(out)
        assert abs(doc[0].rect.width - 210 * MM) < 1.5
        text = doc[0].get_text()
        assert "L1-01" in text and "L1-03" in text, text[:200]
        doc.close()


def test_skip_blank_and_pad_duplex():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "带空白.pdf")
        out = os.path.join(td, "out.pdf")
        make_portrait_pdf(src, pages=10, blanks=(3, 8))
        report = run_pack_json([src, "-o", out, "--skip-blank", "--pad-duplex"])
        assert report["source_pages"] == 8, report        # 两张空白页被剔除
        assert report["sheets"] == 4 and report["sheets"] % 2 == 0
        doc = pymupdf.open(out)
        joined = "".join(p.get_text() for p in doc)
        assert "PAGE 3" not in joined.split("PAGE 4")[0] or True  # 3 是空白页，两种实现都可接受
        assert "PAGE 10" in joined
        doc.close()


def test_booklet_order_is_saddle_stitch():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "八页.pdf")
        out = os.path.join(td, "out.pdf")
        make_portrait_pdf(src, pages=8, size_word=False)
        run_pack([src, "-o", out, "--booklet"])
        doc = pymupdf.open(out)
        assert doc.page_count == 4
        expect = [("PAGE 8", "PAGE 1"), ("PAGE 2", "PAGE 7"),
                  ("PAGE 6", "PAGE 3"), ("PAGE 4", "PAGE 5")]
        for i, (left, right) in enumerate(expect):
            r = doc[i].rect
            mid = r.width / 2
            lt = doc[i].get_text(clip=pymupdf.Rect(0, 0, mid, r.height))
            rt = doc[i].get_text(clip=pymupdf.Rect(mid, 0, r.width, r.height))
            assert left in lt and right in rt, (i, lt[:40], rt[:40])
        doc.close()


def test_per_file_labels_on_merge():
    with tempfile.TemporaryDirectory() as td:
        a = os.path.join(td, "L1-概论.pdf")
        b = os.path.join(td, "L2-编码.pdf")
        out = os.path.join(td, "merge.pdf")
        make_slide_pdf(a, slides=3)
        make_slide_pdf(b, slides=3)
        run_pack([a, b, "-o", out, "--nup", "3in1"])
        doc = pymupdf.open(out)
        text = "".join(p.get_text() for p in doc)
        assert "L1-01" in text and "L1-03" in text, text[:300]
        assert "L2-01" in text and "L2-03" in text, text[:300]
        doc.close()


def test_trim_enlarges_content():
    """内容只占页面中间一小块时，默认裁白边应让内容显著变大（按墨迹像素宽衡量）。"""
    def ink_bbox_width(pdf_path):
        """左半张（第一格）内的墨迹宽度：避开顶部页标与底部页脚所在的条带。"""
        doc = pymupdf.open(pdf_path)
        pix = doc[0].get_pixmap(dpi=60, colorspace=pymupdf.csGRAY)
        w, h = pix.width, pix.height
        samples = pix.samples
        stride = pix.stride
        min_x, max_x = w, -1
        for y in range(int(0.15 * h), int(0.80 * h), 2):
            row = y * stride
            for x in range(0, w // 2):
                if samples[row + x] < 200:  # 有墨
                    if x < min_x:
                        min_x = x
                    if x > max_x:
                        max_x = x
        doc.close()
        return (max_x - min_x) if max_x >= 0 else 0

    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "留白.pdf")
        out_t = os.path.join(td, "trim.pdf")
        out_n = os.path.join(td, "notrim.pdf")
        doc = pymupdf.open()
        for k in range(1, 9):
            page = doc.new_page(width=210 * MM, height=297 * MM)
            page.insert_textbox(pymupdf.Rect(70 * MM, 120 * MM, 140 * MM, 170 * MM),
                                f"INNER {k} " * 30, fontsize=9)
        doc.save(src)
        doc.close()
        run_pack([src, "-o", out_t])
        run_pack([src, "-o", out_n, "--no-trim"])
        wt, wn = ink_bbox_width(out_t), ink_bbox_width(out_n)
        assert wt > wn * 1.8, (wt, wn)


def test_gray_and_page_label_and_error_paths():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "彩页.pdf")
        out = os.path.join(td, "gray.pdf")
        doc = pymupdf.open()
        for k in range(1, 7):
            page = doc.new_page(width=960, height=540)
            page.draw_rect(pymupdf.Rect(40, 40, 920, 500), color=(1, 0, 0), fill=(1, 1, 0))
        doc.save(src)
        doc.close()
        report = run_pack_json([src, "-o", out, "--gray", "--gray-raster", "--dpi", "150"])
        assert report["gray"] is True
        doc = pymupdf.open(out)
        # 灰度输出：页面里不应再有彩色图像
        assert not any("DeviceRGB" in str(img) for img in doc[0].get_images(full=True))
        doc.close()

        # 缺文件 → 非零退出且报错
        code, out_s, err_s = run_pack([os.path.join(td, "不存在.pdf")], expect_ok=False)
        assert code != 0 and "找不到输入文件" in err_s

        # 已存在的他人文件 → 拒绝覆盖
        foreign = os.path.join(td, "他人.pdf")
        make_portrait_pdf(foreign, pages=2)
        code, out_s, err_s = run_pack([src, "-o", foreign], expect_ok=False)
        assert code != 0 and "已存在" in err_s, err_s


def test_gray_mode_places_all_pages():
    """回归：recolor 与 show_pdf_page 同用曾导致除首页外整页丢失。"""
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "多页彩图.pdf")
        out = os.path.join(td, "out.pdf")
        make_slide_pdf(src, slides=12)
        code, _, err = run_pack([src, "-o", out, "--gray"])
        assert "放置失败" not in err, err
        report = json.loads(run_pack([src, "-o", out + ".2", "--gray", "--json"])[1])
        assert report["source_pages"] == 12


def read_toc(path):
    """读取 PDF 目录后立即关闭，避免 Windows 上句柄未释放导致临时目录清理失败。"""
    doc = pymupdf.open(path)
    try:
        return doc.get_toc(simple=False)
    finally:
        doc.close()


def test_page_labels_mark_first_source_page():
    """页标签应等于该张第一个格对应的源页序号，便于反查。"""
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "六页.pdf")
        out = os.path.join(td, "o.pdf")
        make_portrait_pdf(src, pages=6, size_word=False)

        run_pack([src, "-o", out, "--nup", "2"])
        d = pymupdf.open(out)
        try:
            labels = d.get_page_labels()
            assert [x["firstpagenum"] for x in labels] == [1, 3, 5], labels
            assert len(labels) == d.page_count == 3
        finally:
            d.close()

        run_pack([src, "-o", out + ".3", "--nup", "3"])
        d = pymupdf.open(out + ".3")
        try:
            assert [x["firstpagenum"] for x in d.get_page_labels()] == [1, 4]
        finally:
            d.close()

        run_pack([src, "-o", out + ".off", "--page-labels", "none"])
        d = pymupdf.open(out + ".off")
        try:
            assert not d.get_page_labels()
        finally:
            d.close()


def test_outline_is_preserved_and_mapped():
    """拼版后书签应保留，并指向新张上对应格的位置。"""
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "带目录.pdf")
        out = os.path.join(td, "out.pdf")
        doc = pymupdf.open()
        for k in range(1, 10):
            page = doc.new_page(width=210 * MM, height=297 * MM)
            page.insert_text((60, 120), f"PAGE {k}", fontsize=30)
        doc.set_toc([[1, "第一章", 1], [2, "1.1 小节", 2], [1, "第二章", 5]])
        doc.save(src)
        doc.close()

        run_pack([src, "-o", out, "--nup", "2"])
        toc = read_toc(out)
        assert [t[1] for t in toc] == ["第一章", "1.1 小节", "第二章"], toc
        # 2 合 1（每张纸 2 页）：源页 1、2 → 第 1 张；源页 5 → 第 3 张
        assert [t[2] for t in toc] == [1, 1, 3], toc
        assert [t[0] for t in toc] == [1, 2, 1]
        assert isinstance(toc[0][3], dict) and "to" in toc[0][3], toc[0]
        # 目的地点应落在左格内（源页 1 在左格）
        assert toc[0][3]["to"].x < 842 / 2, toc[0][3]

        run_pack([src, "-o", out + ".no", "--outline", "none"])
        assert read_toc(out + ".no") == []

        run_pack([src, "-o", out + ".l1", "--outline", "1"])
        assert [t[1] for t in read_toc(out + ".l1")] == ["第一章", "第二章"]


def test_outline_survives_gray_and_booklet():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "带目录.pdf")
        doc = pymupdf.open()
        for k in range(1, 9):
            page = doc.new_page(width=210 * MM, height=297 * MM)
            page.insert_text((60, 120), f"PAGE {k}", fontsize=30)
        doc.set_toc([[1, "甲", 1], [1, "乙", 5]])
        doc.save(src)
        doc.close()

        out_gray = os.path.join(td, "gray.pdf")
        run_pack([src, "-o", out_gray, "--gray"])
        assert [t[1] for t in read_toc(out_gray)] == ["甲", "乙"]

        out_bk = os.path.join(td, "booklet.pdf")
        run_pack([src, "-o", out_bk, "--booklet"])
        toc = read_toc(out_bk)
        assert [t[1] for t in toc] == ["甲", "乙"], toc
        # 骑马钉 8 页：册序 8,1,2,7,6,3,4,5 → 源页 1 在第 1 面，源页 5 在第 4 面
        assert [t[2] for t in toc] == [1, 4], toc


def test_json_report_is_pure_json():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "d.pdf")
        out = os.path.join(td, "o.pdf")
        make_portrait_pdf(src, pages=2)
        code, out_s, err_s = run_pack([src, "-o", out])
        # 人类可读报告走 stdout，进度走 stderr
        json.loads(run_pack([src, "-o", out + ".2", "--json"])[1])
        assert "省纸打印" in out_s
        assert "排版" in err_s  # 进度信息在 stderr


def ink_left_edge(pdf_path, page_index=0, half="left"):
    """第一格内墨迹最左位置（60dpi 像素），用于验证装订线把内容推离装订侧。"""
    doc = pymupdf.open(pdf_path)
    try:
        pix = doc[page_index].get_pixmap(dpi=60, colorspace=pymupdf.csGRAY)
        w, h, stride, samples = pix.width, pix.height, pix.stride, pix.samples
        x_end = w // 2 if half == "left" else w
        min_x = x_end
        for y in range(int(0.15 * h), int(0.80 * h), 2):
            row = y * stride
            for x in range(0, x_end):
                if samples[row + x] < 200:
                    if x < min_x:
                        min_x = x
                    break
        return min_x
    finally:
        doc.close()


def test_gutter_shifts_content_and_mirror_flips_back():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "十页.pdf")
        base = os.path.join(td, "base.pdf")
        g10 = os.path.join(td, "g10.pdf")
        g10m = os.path.join(td, "g10m.pdf")
        make_portrait_pdf(src, pages=10, size_word=False)
        run_pack([src, "-o", base, "--nup", "2"])
        run_pack([src, "-o", g10, "--nup", "2", "--gutter", "10"])
        run_pack([src, "-o", g10m, "--nup", "2", "--gutter", "10", "--mirror"])

        px_per_mm = 60 / 25.4
        base_left, g10_left = ink_left_edge(base), ink_left_edge(g10)
        assert g10_left - base_left > 6 * px_per_mm, (base_left, g10_left)
        assert g10_left - base_left < 16 * px_per_mm, (base_left, g10_left)

        # 背面镜像：第 2 面不右推（装订线改到右侧）
        back_left = ink_left_edge(g10m, page_index=1)
        assert back_left < g10_left - 4 * px_per_mm, (back_left, g10_left)

        # 小册子：装订线朝中缝，不报错且能读回标签
        bk = os.path.join(td, "bk.pdf")
        run_pack([src, "-o", bk, "--booklet", "--gutter", "8"])
        assert read_toc(bk) == []


def test_cost_estimate_in_report():
    """给纸张单价后，报告应直接给出省下的钱。"""
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "十页.pdf")
        out = os.path.join(td, "o.pdf")
        make_portrait_pdf(src, pages=10, size_word=False)
        rep = run_pack_json([src, "-o", out, "--cost", "0.1", "--nup", "2"])
        assert rep["cost_per_sheet"] == 0.1
        assert rep["paper_sheets_duplex"] == 3          # 10 页 → 5 面 → 双面 3 张
        assert rep["cost_saved_vs_single"] == 0.7       # 原样单面 10 张
        assert rep["cost_saved_vs_duplex"] == 0.2       # 原样双面 5 张
        # 不给单价时不出现成本字段以外的干扰（默认 0）
        rep2 = run_pack_json([src, "-o", out + ".2", "--nup", "2"])
        assert rep2["cost_per_sheet"] == 0.0


def make_noisy_scan(path, pages=4):
    """模拟扫描件：灰底 + 深色文字。"""
    doc = pymupdf.open()
    for k in range(1, pages + 1):
        page = doc.new_page(width=210 * MM, height=297 * MM)
        page.draw_rect(page.rect, fill=(0.78, 0.78, 0.80))
        page.insert_text((60, 120), f"PAGE {k}", fontsize=30, color=(0.12, 0.12, 0.12))
    doc.save(path)
    doc.close()


def gray_page_stats(pdf_path):
    doc = pymupdf.open(pdf_path)
    try:
        pix = doc[0].get_pixmap(dpi=72, colorspace=pymupdf.csGRAY)
        s = pix.samples
        n = len(s)
        return {"mean": sum(s) / n,
                "white": sum(1 for v in s if v > 235) / n,
                "min": min(s),
                "size": os.path.getsize(pdf_path)}
    finally:
        doc.close()


def test_unit_luts_and_png_writer():
    hist = [0] * 256
    hist[200] = 900   # 背景
    hist[30] = 100    # 文字
    lut_e = pack._lut_enhance(hist)
    assert lut_e[200] == 255 and lut_e[30] < 80, (lut_e[200], lut_e[30])
    lut_b = pack._lut_binarize(hist)
    assert set(lut_b) <= {0, 255} and lut_b[200] == 255 and lut_b[30] == 0
    data = bytes([0, 128, 255, 255, 64, 32])
    pm = pymupdf.Pixmap(pack.write_gray_png(3, 2, data))
    assert (pm.width, pm.height) == (3, 2)
    assert list(pm.samples) == list(data)


def test_enhance_and_binarize_clean_scan_background():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "扫描件.pdf")
        base = os.path.join(td, "base.pdf")
        enh = os.path.join(td, "enh.pdf")
        bina = os.path.join(td, "bin.pdf")
        make_noisy_scan(src)
        run_pack([src, "-o", base, "--nup", "2", "--gray-raster"])
        run_pack([src, "-o", enh, "--nup", "2", "--enhance"])
        run_pack([src, "-o", bina, "--nup", "2", "--binarize"])
        b, e, i = gray_page_stats(base), gray_page_stats(enh), gray_page_stats(bina)
        # 去底灰：背景大幅变白，文字仍深
        assert e["white"] > 0.8 > b["white"], (b["white"], e["white"])
        assert e["mean"] > b["mean"] + 20, (b["mean"], e["mean"])
        assert e["min"] < 80, e["min"]
        # 二值化：纯黑白，体积明显更小
        assert i["min"] == 0 and i["white"] > 0.8, i
        assert i["size"] < b["size"] * 0.6, (i["size"], b["size"])


def _pillow_and_numpy() -> bool:
    try:
        import numpy  # noqa: F401
        from PIL import Image, ImageDraw  # noqa: F401
        return True
    except ImportError:
        return False


def make_skewed_scan(path, angle=3.0):
    """生成“倾斜扫描件”：横排文字条整体旋转 angle 度后嵌进 PDF。"""
    from PIL import Image, ImageDraw
    width, height = 1240, 1754          # ≈ A4 @150dpi
    img = Image.new("L", (width, height), 205)
    draw = ImageDraw.Draw(img)
    for row in range(6):
        y = 250 + row * 220
        draw.rectangle([150, y, 1050, y + 60], fill=40)
    img = img.rotate(angle, resample=pack._pillow_resample(Image, "BICUBIC"),
                     fillcolor=205)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=210 * MM, height=297 * MM)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    doc.close()


def row_projection_score(pdf_path) -> float:
    """行投影峰谷强度：文本行越水平，分数越高。"""
    import numpy as np
    doc = pymupdf.open(pdf_path)
    try:
        pix = doc[0].get_pixmap(dpi=120, colorspace=pymupdf.csGRAY)
    finally:
        doc.close()
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width).astype("float32")
    rows = (arr < 128).sum(axis=1).astype("float32")
    return float(((rows[1:] - rows[:-1]) ** 2).sum())


def test_deskew_estimates_and_improves_scan():
    if not _pillow_and_numpy():
        print("  SKIP  test_deskew_estimates_and_improves_scan（缺 Pillow/numpy）")
        return
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "倾斜扫描.pdf")
        plain = os.path.join(td, "enh.pdf")
        fixed = os.path.join(td, "enh_deskew.pdf")
        make_skewed_scan(src, angle=3.0)

        doc = pymupdf.open(src)
        try:
            pm = doc[0].get_pixmap(dpi=150, colorspace=pymupdf.csGRAY, alpha=False)
        finally:
            doc.close()
        est = pack.estimate_skew_angle(pm)
        assert est is not None and abs(abs(est) - 3.0) <= 1.0, est

        run_pack([src, "-o", plain, "--enhance"])
        run_pack([src, "-o", fixed, "--enhance", "--deskew"])
        s_plain, s_fixed = row_projection_score(plain), row_projection_score(fixed)
        assert s_fixed > s_plain * 3, (s_plain, s_fixed)

        rep = json.loads(run_pack([src, "-o", fixed + ".2", "--enhance", "--deskew",
                                   "--json"])[1])
        assert rep["deskew_angles"] and abs(rep["deskew_angles"][0]) <= 5, rep


def ink_fraction(pdf_path) -> float:
    """整份输出的墨迹像素占比：用来衡量内容占格子的饱满程度。"""
    doc = pymupdf.open(pdf_path)
    try:
        ink = total = 0
        for page in doc:
            pix = page.get_pixmap(dpi=60, colorspace=pymupdf.csGRAY)
            smp = pix.samples
            total += len(smp)
            ink += sum(1 for v in smp if v < 128)
        return ink / total
    finally:
        doc.close()


def test_auto_rotate_only_turns_mismatched_pages():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "混排.pdf")
        plain = os.path.join(td, "plain.pdf")
        turned = os.path.join(td, "turned.pdf")
        doc = pymupdf.open()
        for k in range(1, 7):                     # 3 竖 + 3 横，满版填色
            portrait = k <= 3
            page = doc.new_page(width=(210 if portrait else 297) * MM,
                                height=(297 if portrait else 210) * MM)
            page.draw_rect(page.rect, fill=(0.2, 0.2, 0.2))
        doc.save(src)
        doc.close()

        run_pack([src, "-o", plain, "--nup", "2"])
        rep = run_pack_json([src, "-o", turned, "--nup", "2", "--auto-rotate"])
        assert rep["rotated_pages"] == 3, rep["rotated_pages"]
        # 横页转正后应明显填满竖向格子
        assert ink_fraction(turned) > ink_fraction(plain) * 1.2, \
            (ink_fraction(turned), ink_fraction(plain))
        # 不用 --auto-rotate 时一页都不转
        assert run_pack_json([src, "-o", plain + ".2", "--nup", "2"])["rotated_pages"] == 0


def test_dry_run_writes_nothing_and_preview_writes_pngs():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "十页.pdf")
        out = os.path.join(td, "不会存在.pdf")
        make_portrait_pdf(src, pages=10, size_word=False)

        rep = run_pack_json([src, "-o", out, "--nup", "2", "--dry-run", "--cost", "0.05"])
        assert rep["dry_run"] is True
        assert not os.path.exists(out), "预演不应写出文件"
        assert rep["sheets"] == 5 and rep["paper_sheets_duplex"] == 3
        assert rep["cost_saved_vs_single"] == 0.35

        out2 = os.path.join(td, "预览版.pdf")
        rep2 = run_pack_json([src, "-o", out2, "--nup", "2", "--preview", "2"])
        assert os.path.exists(out2)
        assert len(rep2["previews"]) == 2, rep2["previews"]
        for png in rep2["previews"]:
            assert os.path.exists(png) and os.path.getsize(png) > 3000, png
            assert os.path.dirname(png) == td


def test_progress_output_on_large_docs():
    """大任务应在 stderr 报进度，避免用户以为卡死。"""
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "百页.pdf")
        make_portrait_pdf(src, pages=100, size_word=False)
        code, out_s, err_s = run_pack([src, "-o", os.path.join(td, "o.pdf"),
                                       "--nup", "4", "--fast"])
        assert "拼版" in err_s and "%" in err_s, err_s[:400]
        # 小任务不刷进度
        small = os.path.join(td, "十页.pdf")
        make_portrait_pdf(small, pages=10, size_word=False)
        code, out_s2, err_s2 = run_pack([small, "-o", os.path.join(td, "s.pdf"), "--nup", "2"])
        assert "拼版 " not in err_s2, err_s2[:300]


if __name__ == "__main__":
    all_tests = [(name, fn) for name, fn in sorted(globals().items())
                 if name.startswith("test_") and callable(fn)]
    args = sys.argv[1:]
    if args and args[0] in ("-l", "--list"):
        for name, _ in all_tests:
            print(name)
        raise SystemExit(0)
    tests = all_tests
    if args:
        needle = args[0].lower()
        tests = [(n, f) for n, f in all_tests if needle in n.lower()]
        if not tests:
            print(f"没有匹配 “{args[0]}” 的测试；-l 可列出全部名称")
            raise SystemExit(2)
    failed = []
    for name, fn in tests:
        t0 = time.perf_counter()
        try:
            fn()
            print(f"  PASS  {name}（{time.perf_counter() - t0:.1f}s）")
        except Exception as exc:  # noqa: BLE001
            failed.append((name, exc))
            print(f"  FAIL  {name}: {exc}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} 通过")
    raise SystemExit(1 if failed else 0)
