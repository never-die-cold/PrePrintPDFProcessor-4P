#!/usr/bin/env python3
"""check_handout.py 的测试：能抓出被裁的正文、放行干净的讲义。

直接运行：python tests/test_check_handout.py
没有本机浏览器时自动跳过（退出码 0）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.abspath(os.path.join(
    HERE, "..", "skills", "pdf-print-pack", "scripts", "check_handout.py"))

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>体检样例</title>
<style>
@page {{ size: 297mm 210mm; margin: 0; }}
html,body{{ margin:0; padding:0; }}
.sheet{{ width:297mm; height:209mm; break-after:page; page-break-after:always;
         font-size:0; line-height:0; }}
.sheet:last-child{{ break-after:auto; }}
.lp{{ display:inline-block; vertical-align:top; width:49.9%; height:209mm;
      box-sizing:border-box; overflow:hidden; padding:10mm; position:relative;
      font-family:"Microsoft YaHei",sans-serif; font-size:7.5pt; line-height:1.44; }}
.hd{{ font-size:5.6pt; line-height:1.2; }}
.bd{{ height:172mm; overflow:hidden; font-size:7.5pt; line-height:1.44; }}
p{{ margin:0 0 1.5mm 0; }}
</style></head><body>
<div class="sheet">
  <div class="lp"><div class="hd">头</div><div class="bd">{left}</div></div>
  <div class="lp"><div class="hd">头</div><div class="bd">第二逻辑页，内容很少。</div></div>
</div>
</body></html>
"""


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


def write_html(path: str, left_content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(TEMPLATE.format(left=left_content))


def run_check(html: str, extra=None):
    proc = subprocess.run([sys.executable, CHECK, html, "--json", *list(extra or [])],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    payload = None
    if proc.stdout.strip().startswith("{"):
        payload = json.loads(proc.stdout)
    return proc.returncode, payload, proc.stderr


def test_overflow_is_detected():
    if not browser_available():
        print("  SKIP  test_overflow_is_detected（未找到本机浏览器）")
        return
    with tempfile.TemporaryDirectory() as td:
        # 内容超高：200 段 <p> 撑爆 172mm 的 .bd
        bad = "".join(f"<p>第 {i} 行内容，用来把正文区撑到溢出被裁掉。</p>"
                      for i in range(200))
        html_bad = os.path.join(td, "溢出.html")
        write_html(html_bad, bad)
        code, payload, err = run_check(html_bad)
        assert code == 1, (code, err, payload)
        assert payload and payload["ok"] is False, payload
        assert payload["overflow"], payload
        assert payload["overflow"][0]["side"] == "left", payload["overflow"]

        ok = "".join(f"<p>第 {i} 行内容，留白充足不会溢出。</p>" for i in range(20))
        html_ok = os.path.join(td, "干净.html")
        write_html(html_ok, ok)
        code2, payload2, err2 = run_check(html_ok)
        assert code2 == 0, (code2, err2, payload2)
        assert payload2 and payload2["ok"] is True and not payload2["overflow"], payload2


def test_keep_writes_staged_copy():
    if not browser_available():
        print("  SKIP  test_keep_writes_staged_copy（未找到本机浏览器）")
        return
    with tempfile.TemporaryDirectory() as td:
        html = os.path.join(td, "样例.html")
        write_html(html, "<p>短内容。</p>")
        code, payload, err = run_check(html, ["--keep"])
        assert code == 0, (code, err)
        staged = os.path.join(td, "样例_检查版.html")
        assert os.path.exists(staged), payload
        with open(staged, encoding="utf-8") as fh:
            text = fh.read()
        assert "pp-check-script" in text, "染色版应包含体检脚本"


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
