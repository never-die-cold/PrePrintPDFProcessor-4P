#!/usr/bin/env python3
"""html2pdf.py（Edge/Chrome 无头 HTML→PDF）的冒烟测试。

直接运行：python tests/test_html2pdf.py
没有本机浏览器时自动跳过（退出码 0）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
HTML2PDF = os.path.abspath(os.path.join(
    HERE, "..", "skills", "pdf-print-pack", "scripts", "html2pdf.py"))
MM = 72 / 25.4

SAMPLE_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>样例</title>
<style>
@page { size: 297mm 210mm; margin: 0; }
html,body{ margin:0; padding:0; }
.sheet{ box-sizing:border-box; width:297mm; height:209mm;
         break-after:page; page-break-after:always;
         font-family:"Microsoft YaHei",sans-serif; font-size:7.5pt; padding:12mm; }
.sheet:last-child{ break-after:auto; }
h1{ font-size:12pt; }
</style></head><body>
<div class="sheet"><h1>第一张</h1><p>横向 A4 的第一逻辑页。</p></div>
<div class="sheet"><h1>第二张</h1><p>横向 A4 的第二逻辑页。</p></div>
</body></html>
"""


def find_browser_available() -> bool:
    if os.environ.get("PDFPP_BROWSER") and os.path.isfile(os.environ["PDFPP_BROWSER"]):
        return True
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
    ]
    return any(os.path.isfile(c) for c in candidates)


def main() -> int:
    if not find_browser_available():
        print("  SKIP  test_html2pdf_renders_declared_paper （未找到本机 Edge/Chrome）")
        return 0

    with tempfile.TemporaryDirectory() as td:
        html = os.path.join(td, "样例讲义.html")
        out = os.path.join(td, "样例讲义.pdf")
        with open(html, "w", encoding="utf-8") as fh:
            fh.write(SAMPLE_HTML)
        proc = subprocess.run(
            [sys.executable, HTML2PDF, html, "-o", out, "--timeout", "120"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            print(f"  FAIL  test_html2pdf_renders_declared_paper: {proc.stderr}\n{proc.stdout}")
            return 1
        ok = True
        detail = ""
        doc = pymupdf.open(out)
        try:
            if doc.page_count != 2:
                ok, detail = False, f"页数应为 2，实际 {doc.page_count}"
            else:
                r = doc[0].rect
                if abs(r.width - 297 * MM) > 2 or abs(r.height - 210 * MM) > 2:
                    ok, detail = False, f"页面尺寸 {r.width / MM:.1f}×{r.height / MM:.1f}mm"
                else:
                    text = "".join(p.get_text() for p in doc)
                    if "第一张" not in text or "第二张" not in text:
                        ok, detail = False, f"文字缺失：{text[:120]}"
        finally:
            doc.close()
        if not ok:
            print(f"  FAIL  test_html2pdf_renders_declared_paper: {detail}")
            return 1
    print("  PASS  test_html2pdf_renders_declared_paper")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
