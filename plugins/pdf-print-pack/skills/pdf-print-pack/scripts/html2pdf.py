#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""html2pdf.py — 用系统里的 Edge/Chrome 无头模式把 HTML 打印成 PDF。

讲义重排工作流里，HTML 用 @page CSS 声明纸张（如 A4 横向 297mm×210mm），
本脚本调用浏览器 --print-to-pdf，尺寸与边距完全由 CSS 决定，
因此打印设置与浏览器预览一致、可复现。

用法：
  python html2pdf.py 讲义.html                       # 输出同名 .pdf
  python html2pdf.py 讲义.html -o 讲义_2合1.pdf
  python html2pdf.py 讲义.html --browser "C:/.../msedge.exe"

依赖：本机已装 Microsoft Edge 或 Google Chrome（Windows 一般自带 Edge）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

MM = 72.0 / 25.4

# 无头参数组合，按“新→旧”顺序尝试：
# 新版 Chrome/Edge 用 --headless=new 与 --no-pdf-header-footer，
# 旧版只认 --headless 与 --print-to-pdf-no-header。
HEADLESS_VARIANTS = (
    ("--headless=new", "--no-pdf-header-footer"),
    ("--headless=new", "--print-to-pdf-no-header"),
    ("--headless", "--print-to-pdf-no-header"),
    ("--headless", "--no-pdf-header-footer"),
)

BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/microsoft-edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def find_browser(explicit: str | None) -> str:
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        sys.exit(f"错误：指定的浏览器不存在：{explicit}")
    env = os.environ.get("PDFPP_BROWSER")
    if env and os.path.isfile(env):
        return env
    for cand in BROWSER_CANDIDATES:
        if os.path.isfile(cand):
            return cand
    for name in ("msedge", "google-chrome", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    sys.exit("错误：未找到 Edge/Chrome。请用 --browser 指定可执行文件路径，"
             "或设置环境变量 PDFPP_BROWSER。")


def print_to_pdf(browser: str, profile: str, url: str, out: str, timeout: int):
    """按新旧参数组合依次尝试无头打印；返回 (是否成功, 最后一次错误摘要)。"""
    last_err = ""
    for idx, variant in enumerate(HEADLESS_VARIANTS):
        if os.path.exists(out):
            os.remove(out)          # 浏览器不覆盖已有文件
        cmd = [browser, *variant, "--disable-gpu", "--no-first-run",
               "--no-default-browser-check", f"--user-data-dir={profile}",
               f"--print-to-pdf={out}", url]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            last_err = f"超时（>{timeout}s）。HTML 是否过大？"
            continue
        # 浏览器偶尔先返回、文件稍后就绪
        for _ in range(20):
            if os.path.exists(out) and os.path.getsize(out) > 0:
                if idx > 0:
                    print(f"提示：浏览器不认新参数，已用兼容组合重试成功（{variant[1]}）",
                          file=sys.stderr)
                return True, ""
            time.sleep(0.25)
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        last_err = err[-800:] if err else f"退出码 {proc.returncode}"
    return False, last_err


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="HTML → PDF（Edge/Chrome 无头打印）")
    ap.add_argument("html", help="输入的 HTML 文件（用 @page 声明纸张尺寸）")
    ap.add_argument("-o", "--out", help="输出 PDF（默认与 HTML 同名）")
    ap.add_argument("--browser", help="Edge/Chrome 可执行文件路径")
    ap.add_argument("--timeout", type=int, default=180, help="超时秒数（默认 180）")
    args = ap.parse_args(argv)

    html = os.path.abspath(args.html)
    if not os.path.isfile(html):
        sys.exit(f"错误：找不到 HTML：{html}")
    out = os.path.abspath(args.out) if args.out else os.path.splitext(html)[0] + ".pdf"
    browser = find_browser(args.browser)

    if os.path.exists(out):
        os.remove(out)  # 浏览器不会覆盖已有文件，先删掉

    profile = tempfile.mkdtemp(prefix="pdfpp-")
    # 路径可能含空格、#、% 或非 ASCII 字符，必须做百分号编码，否则 # 会被当成片段
    url = "file:///" + quote(html.replace("\\", "/").lstrip("/"), safe="/:")
    try:
        ok, detail = print_to_pdf(browser, profile, url, out, args.timeout)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if not ok:
        sys.exit(f"错误：未生成 PDF。最后一次浏览器输出：\n{detail}")

    info = ""
    try:
        import pymupdf
        doc = pymupdf.open(out)
        r = doc[0].rect
        info = (f"页数 {doc.page_count}，页面 {r.width / MM:.1f}×{r.height / MM:.1f} mm")
        doc.close()
    except Exception:
        pass
    size_mb = os.path.getsize(out) / 1048576
    print(f"已生成：{out}")
    print(f"  {info}{'，' if info else ''}体积 {size_mb:.2f} MB")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
