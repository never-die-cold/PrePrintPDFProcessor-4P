#!/usr/bin/env python3
"""结构快照测试：固定输入 → 固定结构（张数/网格/页标/书签/页标签），防止无声漂移。

只比较结构与文字，不比较像素，因此跨平台稳定。
  python tests/test_snapshot.py            # 与 golden/snapshot.json 比对
  python tests/test_snapshot.py --update   # 重新生成快照（人工确认差异合理后再提交）
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
PACK_PY = os.path.abspath(os.path.join(
    HERE, "..", "skills", "pdf-print-pack", "scripts", "pack.py"))
GOLDEN = os.path.join(HERE, "golden", "snapshot.json")
MM = 72 / 25.4


def build_snapshot(tmp_dir: str) -> dict:
    """用固定输入跑一遍，收集结构指纹。"""
    src = os.path.join(tmp_dir, "K1-结构样本.pdf")
    doc = pymupdf.open()
    for k in range(1, 13):
        page = doc.new_page(width=210 * MM, height=297 * MM)
        page.insert_text((40, 80), f"MARKER {k:03d} ", fontsize=12)
        page.insert_text((40, 120), f"正文第 {k} 页内容。" * 6, fontsize=9)
    doc.set_toc([[1, "第一章 绪论", 1], [2, "1.1 小节", 3], [1, "第二章 方法", 7]])
    doc.save(src)
    doc.close()

    out = os.path.join(tmp_dir, "out.pdf")
    proc = subprocess.run(
        [sys.executable, PACK_PY, src, "-o", out, "--nup", "4",
         "--frame", "thin", "--mark", "--fast", "--json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise AssertionError(f"pack.py 失败：{proc.stderr}")
    report = json.loads(proc.stdout)

    doc = pymupdf.open(out)
    try:
        text = "\n".join(page.get_text() for page in doc)
        snapshot = {
            "grid": report["grid"],
            "orientation": report["orientation"],
            "sheets": doc.page_count,
            "page_size_mm": [round(doc[0].rect.width / MM, 1),
                             round(doc[0].rect.height / MM, 1)],
            "labels": sorted(set(re.findall(r"K1-\d\d", text))),
            "markers_in_order": [int(m) for m in re.findall(r"MARKER (\d{3})", text)],
            "toc": [[t[0], t[1], t[2]] for t in doc.get_toc()],
            "page_labels": [x["firstpagenum"] for x in doc.get_page_labels()],
        }
    finally:
        doc.close()
    return snapshot


def diff(old, new, path="$") -> list:
    """给出可读的差异列表。"""
    out = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            if key not in old:
                out.append(f"{path}.{key}: 新增 {new[key]!r}")
            elif key not in new:
                out.append(f"{path}.{key}: 删除 {old[key]!r}")
            else:
                out += diff(old[key], new[key], f"{path}.{key}")
    elif old != new:
        out.append(f"{path}: {old!r} → {new!r}")
    return out


def main() -> int:
    update = "--update" in sys.argv[1:]
    with tempfile.TemporaryDirectory() as td:
        current = build_snapshot(td)

    if update or not os.path.exists(GOLDEN):
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(current, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"  {'更新' if update else '创建'}快照：{GOLDEN}")
        print("  PASS  test_structure_snapshot")
        return 0

    with open(GOLDEN, encoding="utf-8") as fh:
        expected = json.load(fh)
    differences = diff(expected, current)
    if differences:
        print("  FAIL  test_structure_snapshot：结构发生变化")
        for line in differences:
            print(f"        {line}")
        print("        确认是有意改动后运行：python tests/test_snapshot.py --update")
        return 1
    print("  PASS  test_structure_snapshot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
