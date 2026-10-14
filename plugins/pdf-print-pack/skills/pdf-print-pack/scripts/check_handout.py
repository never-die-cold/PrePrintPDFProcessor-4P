#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""讲义排版体检 check_handout.py

拼版讲义时最容易出的错是「正文比逻辑页高，超出部分被 .bd 的 overflow:hidden 裁掉」——
肉眼在缩略图里很难发现。本工具把 HTML 里每块 .bd 的溢出情况染成品红，用无头浏览器
渲染后数像素，直接报告「第几张纸、左半还是右半溢出」。

用法：
  python check_handout.py 讲义.html                # 体检，退出码 0=干净 1=有溢出
  python check_handout.py 讲义.html --json         # 机器可读结果
  python check_handout.py 讲义.html --keep         # 保留染色版 HTML 便于人工查看

依赖：本机 Edge/Chrome（与 html2pdf.py 相同）。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MAGENTA_R, MAGENTA_G, MAGENTA_B = 255, 0, 255

INJECT = """
<style id="pp-check-style"></style>
<script id="pp-check-script">
(function () {
  function mark() {
    var nodes = document.querySelectorAll('.bd');
    var bad = 0;
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      // 允许 1px 的舍入误差；超出即染成品红
      if (el.scrollHeight > el.clientHeight + 1) {
        el.style.background = '#ff00ff';
        el.style.outline = '4px solid #ff00ff';
        bad += 1;
      }
    }
    document.title = 'PPCHECK:' + bad + ':' + nodes.length;
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mark);
  } else {
    mark();
  }
})();
</script>
"""


def load_html2pdf():
    """复用同目录的 html2pdf.py（浏览器探测与无头打印逻辑）。"""
    spec = importlib.util.spec_from_file_location(
        "html2pdf_for_check", os.path.join(HERE, "html2pdf.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def inject_checker(html_text: str) -> str:
    """把体检脚本插到 </head> 之前（没有 head 就插到最前面）。"""
    if re.search(r"</head>", html_text, re.IGNORECASE):
        return re.sub(r"</head>", INJECT + "</head>", html_text, count=1,
                      flags=re.IGNORECASE)
    return INJECT + html_text


def count_sheets(html_text: str) -> int:
    return len(re.findall(r'class="[^"]*\bsheet\b', html_text))


def find_overflow(pymupdf, pdf_path: str, dpi: int = 50):
    """逐页找品红像素，返回 [{page, side, pixels}]。"""
    doc = pymupdf.open(pdf_path)
    found = []
    try:
        for index, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB)
            samples = pix.samples
            stride = pix.stride
            width = pix.width
            left = right = 0
            for y in range(pix.height):
                row = y * stride
                for x in range(width):
                    off = row + x * 3
                    if (samples[off] > 200 and samples[off + 1] < 80
                            and samples[off + 2] > 200):
                        if x < width // 2:
                            left += 1
                        else:
                            right += 1
            if left + right >= 50:      # 少量像素可能是抗锯齿，忽略
                side = "both" if left >= 50 and right >= 50 else \
                    ("left" if left >= right else "right")
                found.append({"page": index + 1, "side": side,
                              "pixels": left + right})
    finally:
        doc.close()
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="讲义排版体检：找出被 .bd 裁掉的正文（品红染色 + 无头渲染检测）")
    ap.add_argument("html", help="待体检的讲义 HTML")
    ap.add_argument("--keep", action="store_true",
                    help="保留染色版 HTML（<名字>_检查版.html），可用浏览器直接看品红块")
    ap.add_argument("--json", action="store_true", help="输出 JSON 结果")
    ap.add_argument("--timeout", type=int, default=180, help="浏览器超时秒数")
    args = ap.parse_args(argv)

    html_path = os.path.abspath(args.html)
    if not os.path.isfile(html_path):
        print(f"错误：找不到 HTML：{html_path}", file=sys.stderr)
        return 2
    with open(html_path, encoding="utf-8") as fh:
        original = fh.read()

    try:
        import pymupdf
    except ImportError:
        print("错误：需要 PyMuPDF（pip install pymupdf）", file=sys.stderr)
        return 2

    staged = inject_checker(original)
    expected_sheets = count_sheets(original)
    keep_path = None
    tmp_dir = tempfile.mkdtemp(prefix="ppcheck-")
    try:
        staged_path = os.path.join(tmp_dir, "staged.html")
        with open(staged_path, "w", encoding="utf-8") as fh:
            fh.write(staged)
        if args.keep:
            keep_path = os.path.splitext(html_path)[0] + "_检查版.html"
            with open(keep_path, "w", encoding="utf-8") as fh:
                fh.write(staged)

        pdf_path = os.path.join(tmp_dir, "staged.pdf")
        mod = load_html2pdf()
        try:
            browser = mod.find_browser(None)
        except SystemExit as exc:
            print(str(exc), file=sys.stderr)
            return 2
        profile = os.path.join(tmp_dir, "profile")
        os.makedirs(profile, exist_ok=True)
        url = "file:///" + mod.quote(staged_path.replace("\\", "/").lstrip("/"),
                                     safe="/:")
        ok, detail = mod.print_to_pdf(browser, profile, url, pdf_path, args.timeout)
        if not ok:
            print(f"错误：渲染失败：{detail}", file=sys.stderr)
            return 2

        overflow = find_overflow(pymupdf, pdf_path)
        doc = pymupdf.open(pdf_path)
        pages = doc.page_count
        doc.close()
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    problems = []
    if pages != expected_sheets:
        problems.append(f"渲染出 {pages} 页，但 HTML 里有 {expected_sheets} 张 .sheet"
                        f"（可能某个逻辑页内容溢出成多页）")
    side_txt = {"left": "左半", "right": "右半", "both": "两半"}
    for item in overflow:
        problems.append(f"第 {item['page']} 张的{side_txt[item['side']]}"
                        f"有正文溢出被裁（品红像素 {item['pixels']}）")

    result = {
        "html": html_path,
        "expected_sheets": expected_sheets,
        "rendered_pages": pages,
        "overflow": overflow,
        "problems": problems,
        "ok": not problems,
        "staged_copy": keep_path,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"讲义体检：{os.path.basename(html_path)}"
              f"（{expected_sheets} 张纸，渲染 {pages} 页）")
        if problems:
            print("  ✗ 发现问题：")
            for text in problems:
                print(f"    - {text}")
            print("  处理：把该逻辑页的内容删减几行，或把字号/行距调小，再重跑本体检。")
        else:
            print("  ✓ 没有发现被裁的正文，可以打印")
        if keep_path:
            print(f"  染色版已保留：{keep_path}（浏览器打开可看到品红标记）")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
