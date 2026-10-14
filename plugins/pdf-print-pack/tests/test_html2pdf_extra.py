#!/usr/bin/env python3
"""html2pdf.py 的边界测试：文件名里的 # & % 空格 与中文，以及页眉参数降级。

直接运行：python tests/test_html2pdf_extra.py
没有本机浏览器时自动跳过（退出码 0）。
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import types

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
HTML2PDF = os.path.abspath(os.path.join(
    HERE, "..", "skills", "pdf-print-pack", "scripts", "html2pdf.py"))
MM = 72 / 25.4

SAMPLE_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>边界样例</title>
<style>@page { size: 297mm 210mm; margin: 0; }
.sheet{ box-sizing:border-box; width:297mm; height:209mm; break-after:page;
        page-break-after:always; padding:10mm; font-family:"Microsoft YaHei",sans-serif; }
.sheet:last-child{ break-after:auto; }</style></head><body>
<div class="sheet"><h1>特殊文件名 #1 与 &amp; 符号</h1></div>
<div class="sheet"><h1>第二页</h1></div>
</body></html>
"""


def load_html2pdf():
    spec = importlib.util.spec_from_file_location("html2pdf_under_test", HTML2PDF)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def browser_available() -> bool:
    if os.environ.get("PDFPP_BROWSER") and os.path.isfile(os.environ["PDFPP_BROWSER"]):
        return True
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ]
    return any(os.path.isfile(c) for c in candidates)


def test_url_encoding_for_awkward_file_names():
    """文件名含 空格 # % & 中文 时也要能打印。"""
    if not browser_available():
        print("  SKIP  test_url_encoding_for_awkward_file_names（未找到本机浏览器）")
        return
    with tempfile.TemporaryDirectory() as td:
        name = "讲义 #1 & 100%的 测试.html"
        html = os.path.join(td, name)
        out = os.path.join(td, "输出 #1.pdf")
        with open(html, "w", encoding="utf-8") as fh:
            fh.write(SAMPLE_HTML)
        proc = subprocess.run([sys.executable, HTML2PDF, html, "-o", out],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
        assert proc.returncode == 0, proc.stderr
        doc = pymupdf.open(out)
        try:
            assert doc.page_count == 2, doc.page_count
            r = doc[0].rect
            assert abs(r.width - 297 * MM) < 2 and abs(r.height - 210 * MM) < 2
        finally:
            doc.close()


def test_headless_flag_fallback():
    """老版本 Chrome 不认 --no-pdf-header-footer 时，应自动换用兼容参数重试。"""
    mod = load_html2pdf()
    with tempfile.TemporaryDirectory() as td:
        html = os.path.join(td, "样例.html")
        out = os.path.join(td, "样例.pdf")
        with open(html, "w", encoding="utf-8") as fh:
            fh.write(SAMPLE_HTML)

        # 造一个最小合法 PDF（模拟浏览器产物）
        src = pymupdf.open()
        src.new_page(width=297 * MM, height=209.9 * MM)
        minimal = src.tobytes()
        src.close()

        calls: list[list[str]] = []

        def fake_run(cmd, capture_output=True, timeout=None):
            calls.append(list(cmd))
            if "--no-pdf-header-footer" in cmd:      # 模拟老浏览器：不认这个开关
                return types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"bad flag")
            target = next(c.split("=", 1)[1] for c in cmd if c.startswith("--print-to-pdf="))
            with open(target, "wb") as fh:
                fh.write(minimal)
            return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        real_run = mod.subprocess.run
        mod.subprocess.run = fake_run
        try:
            # 用本测试文件自身充当“浏览器可执行文件”（只需存在）
            code = mod.main([html, "-o", out, "--browser", os.path.abspath(__file__)])
        finally:
            mod.subprocess.run = real_run
        assert code == 0
        assert len(calls) >= 2, calls
        assert "--no-pdf-header-footer" in calls[0]
        assert "--print-to-pdf-no-header" in calls[1], calls[1]
        assert os.path.exists(out)


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as exc:
                failed += 1
                print(f"  FAIL  {name}: {exc}")
    raise SystemExit(1 if failed else 0)
