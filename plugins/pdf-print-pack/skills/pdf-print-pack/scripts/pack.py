#!/usr/bin/env python3
"""省纸打印拼版引擎（N-up imposition）。

把任意 PDF 拼成「N 合 1」省纸打印版：多页挤到一张 A4，双面打印后每张纸承载 2N 页。
支持：自动选排版（横排课件 3 合 1 / 纵排文档 2 合 1）、裁白边放大、灰度省墨、
双面补页、短边翻页补旋转、图片降采样瘦身、小册子（对折）拼版。

用法示例：
  python pack.py 课件.pdf
  python pack.py 第1章.pdf 第2章.pdf -o 合并_省纸打印版.pdf --nup 3
  python pack.py 课件.pdf --nup 6 --gray --pad-duplex --quality 70 --dpi 200
  python pack.py 笔记.pdf --booklet

依赖：pip install pymupdf
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import sys
import contextlib

MM = 72.0 / 25.4  # 1 毫米 = 72/25.4 点

PAPERS = {
    "a4": (210.0, 297.0),
    "a3": (297.0, 420.0),
    "a5": (148.0, 210.0),
    "letter": (215.9, 279.4),
}

CREATOR_TAG = "pdf-print-pack"
CHINESE_NUM = {c: i for i, c in enumerate("一二三四五六七八九十", start=1)}


def die(msg: str, code: int = 2) -> None:
    print(f"错误：{msg}", file=sys.stderr)
    raise SystemExit(code)


def log(*args) -> None:
    """进度信息一律走 stderr，保证 --json 时 stdout 只有 JSON。"""
    print(*args, file=sys.stderr)


def quiet_mupdf(pymupdf, verbose: bool) -> None:
    """压制 MuPDF 对源文件的无害告警（缺 Pattern 资源之类），--verbose 可放开。"""
    if verbose:
        return
    try:
        pymupdf.TOOLS.mupdf_display_errors(False)
        pymupdf.TOOLS.mupdf_display_warnings(False)
    except Exception:
        pass


def pymupdf_version(pymupdf) -> tuple:
    """尽力解析 PyMuPDF 版本号；解析不出来返回 (0, 0, 0)。"""
    raw = getattr(pymupdf, "version", None)
    if isinstance(raw, (tuple, list)) and raw:
        raw = raw[0]
    nums = [int(n) for n in re.findall(r"\d+", str(raw or ""))][:3]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def gate_capabilities(pymupdf, args) -> None:
    """按 PyMuPDF 能力降级或给出清晰报错（旧版本不再是一句 AttributeError）。"""
    ver = pymupdf_version(pymupdf)
    if ver < (1, 24, 0):
        log(f"  提示：PyMuPDF {'.'.join(map(str, ver))} 较旧，部分功能会自动降级"
            f"（建议 pip install -U pymupdf）")
    if args.gray and not hasattr(pymupdf.Document, "recolor"):
        die("当前 PyMuPDF 不支持矢量转灰度（需要 Document.recolor）：\n"
            "  可改用 --gray-raster，或升级：pip install -U pymupdf")
    if args.optimize != "off" and not hasattr(pymupdf.Document, "rewrite_images"):
        log("  提示：当前 PyMuPDF 不支持图片瘦身，已跳过（pip install -U pymupdf 可启用）")
        args.optimize = "off"
    if not hasattr(pymupdf.Page, "get_bboxlog"):
        if not args.no_trim:
            log("  提示：当前 PyMuPDF 无法分析内容边界，已关闭自动裁白边")
        args.no_trim = True


def load_pymupdf():
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # 兼容旧版包名
            return pymupdf
        except ImportError:
            die("未安装 PyMuPDF，请先运行：pip install pymupdf")


# ---------------------------------------------------------------- 输入排序

def cn2int(text: str) -> int:
    """把「一」「十二」这类中文数字转成整数（只处理 1..99 的常见写法）。"""
    text = text.strip()
    if not text:
        return 0
    if "十" in text:
        head, _, tail = text.partition("十")
        tens = CHINESE_NUM.get(head, 1) if head else 1
        ones = CHINESE_NUM.get(tail, 0) if tail else 0
        return tens * 10 + ones
    return CHINESE_NUM.get(text, 0)


def natural_key(path: str):
    """让“2.量子力学简介”“第2章”“10. 第7章”按自然顺序排列。"""
    name = os.path.basename(path)
    m = re.match(r"\s*(\d{1,3})\s*[\.\-_、, ]", name)
    lead = int(m.group(1)) if m else None
    mc = re.search(r"第\s*([一二三四五六七八九十]+|\d+)\s*[章讲节]", name)
    cn = 0
    if mc:
        token = mc.group(1)
        cn = int(token) if token.isdigit() else cn2int(token)
    sub = {"上": 0, "中": 1, "下": 2}
    shared = re.search(r"[（(]?\s*(上|中|下)\s*[）)]?", name)
    s = sub.get(shared.group(1), 0) if shared else 0
    return (0 if lead is not None else 1, lead or 0, cn, s, name)


def parse_pages_spec(spec: str | None, total: int) -> list[int]:
    """解析 “1-5,8,11-” 页码范围（1 起），返回 0 起页号列表（保序去重）。"""
    if not spec:
        return list(range(total))
    out: list[int] = []
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            start = int(a) if a.strip() else 1
            end = int(b) if b.strip() else total
            out += [p - 1 for p in range(start, min(end, total) + 1) if p >= 1]
        else:
            p = int(part)
            if 1 <= p <= total:
                out.append(p - 1)
    seen, res = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            res.append(p)
    return res


# ---------------------------------------------------------------- 版面分析

def _lut_enhance(hist) -> list:
    """去底灰 + 对比伸展：把接近背景的高亮压成纯白，其余线性拉到 0-255。"""
    total = sum(hist) or 1
    acc = 0
    wp = 255
    for v in range(255, -1, -1):
        acc += hist[v]
        if acc >= 0.30 * total:   # 从亮端累计 30% 处即背景白点
            wp = v
            break
    wp = max(wp, 120)
    cut = int(wp * 0.92)
    return [255 if v >= cut else min(255, round(v * 255 / max(1, cut)))
            for v in range(256)]


def _lut_binarize(hist) -> list:
    """Otsu 阈值二值化。"""
    total = sum(hist) or 1
    sum_all = sum(i * h for i, h in enumerate(hist))
    sum_b = 0.0
    w_b = 0
    best_t, best_var = 160, -1.0
    for t in range(256):
        w_b += hist[t]
        w_f = total - w_b
        if w_b == 0 or w_f == 0:
            continue
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best_var:
            best_var, best_t = var, t
    # 阈值按闭区间判墨：v <= t 归为笔画（否则最深笔画会被判成背景而消失）
    return [0 if v <= best_t else 255 for v in range(256)]


def write_gray_png(width: int, height: int, data: bytes) -> bytes:
    """最小 8 位灰度 PNG 编码器（无第三方依赖的兜底路径）。"""
    import struct
    import zlib
    raw = bytearray()
    for y in range(height):
        raw.append(0)                     # 每行滤波类型：None
        raw += data[y * width:(y + 1) * width]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    signature = bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10])
    return (signature + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def _pillow_resample(Image, name):
    """兼容新旧 Pillow：Resampling 枚举优先，旧版退回常量。"""
    res = getattr(Image, "Resampling", None)
    if res is not None and hasattr(res, name):
        return getattr(res, name)
    return getattr(Image, name)


def estimate_skew_angle(pm, max_angle: float = 5.0, step: float = 0.5):
    """行投影方差法估计倾斜角（度）。返回修正角；无 numpy/Pillow 或内容太少时返回 None。

    思路：把墨迹二值化后按候选角度旋转，行投影（每行墨量）越“峰谷分明”说明文本行越水平，
    取峰谷差异最大的角度作为修正角。
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    img = Image.frombytes("L", (pm.width, pm.height), pm.samples)
    scale = max(1, int(min(img.width, img.height) / 700))   # 降采样加速
    if scale > 1:
        img = img.resize((img.width // scale, img.height // scale),
                         _pillow_resample(Image, "BILINEAR"))
    arr = np.asarray(img, dtype=np.float32)
    mask = (arr < 160).astype(np.float32)
    if mask.sum() < 100:
        return None
    mask_img = Image.fromarray((mask * 255).astype("uint8"))
    best_a, best_score = 0.0, -1.0
    a = -max_angle
    while a <= max_angle + 1e-9:
        rot = mask_img.rotate(a, resample=_pillow_resample(Image, "BILINEAR"), fillcolor=0)
        rows = np.asarray(rot, dtype=np.float32).sum(axis=1)
        score = float(((rows[1:] - rows[:-1]) ** 2).sum())
        if score > best_score:
            best_score, best_a = score, a
        a += step
    return best_a


def clean_scan_image(pymupdf, pm, args, binarize: bool = False):
    """扫描件清理流水线：可选去歪斜 → 去噪 → 去底灰/二值化 → 编码。

    返回 (图像字节, 格式, 去歪斜角度或 None)。二值化输出 PNG（无损、体积小），其余 JPEG。
    没有 Pillow 时退回纯标准库 LUT + 自写 PNG（不做去噪与去歪斜）。
    """
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        Image = None
    angle = None
    if Image is not None:
        img = Image.frombytes("L", (pm.width, pm.height), pm.samples)
        if args.deskew:
            est = estimate_skew_angle(pm)
            if est is not None and abs(est) >= 0.2:
                # 旋转后的四角用页边颜色填充，避免出现纯白尖角
                border = img.crop((0, 0, img.width, max(1, img.height // 40)))
                fill = int(sum(border.getdata()) / max(1, border.width * border.height))
                img = img.rotate(est, resample=_pillow_resample(Image, "BICUBIC"),
                                 fillcolor=fill)
                angle = round(float(est), 2)
        if not binarize:
            img = img.filter(ImageFilter.MedianFilter(3))   # 去椒盐噪点
        hist = img.histogram()
        lut = _lut_binarize(hist) if binarize else _lut_enhance(hist)
        img = img.point(lut)
        buf = io.BytesIO()
        if binarize:
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), "png", angle
        img.save(buf, format="JPEG", quality=args.quality)
        return buf.getvalue(), "jpeg", angle
    # 无 Pillow：纯标准库 LUT + 自写 PNG（不做去噪/去歪斜）
    samples = pm.samples
    hist = [samples.count(bytes([v])) for v in range(256)]
    lut = _lut_binarize(hist) if binarize else _lut_enhance(hist)
    return write_gray_png(pm.width, pm.height, samples.translate(bytes(lut))), "png", None


def gray_sanitize(pymupdf, doc, temps: list):
    """整体转灰度：走「转灰度 → 存临时副本 → 重新打开」。

    Page/ Document.recolor 会就地改写页面资源，若与 show_pdf_page 同用，
    除首页外的页面复制会失败（source object number out of range），
    因此必须先落盘成干净副本再引用。
    """
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix="pdfpp-gray-", suffix=".pdf")
    os.close(fd)
    try:
        doc.recolor(1)  # 1 分量 = 灰度；文字仍是矢量，可搜索可选中
        doc.save(tmp, garbage=2, deflate=True, deflate_fonts=True)
    finally:
        doc.close()
    temps.append(tmp)
    return pymupdf.open(tmp)


def page_content_rect(pymupdf, page):
    """本页所有可见内容的外接矩形（无内容时返回 None）。"""
    rect = None
    try:
        entries = page.get_bboxlog()
    except Exception:
        entries = []
    for item in entries:
        try:
            b = pymupdf.Rect(item[1])
        except Exception:
            continue
        vals = (b.x0, b.y0, b.x1, b.y1)
        if not all(math.isfinite(v) for v in vals) or b.is_empty:
            continue
        rect = b if rect is None else (rect | b)
    return rect


def is_blank_page(page, entries=None) -> bool:
    """近似判断空白页：没有文字、图片，且几乎没有任何图形对象。"""
    try:
        if page.get_text().strip():
            return False
        if page.get_images():
            return False
        log = page.get_bboxlog() if entries is None else entries
        if not log:
            return True
        # 只有一个覆盖整页的填充（白色底）也视为空白
        if len(log) <= 1:
            b = page_rect = page.rect
            try:
                import pymupdf as _pm
                b = _pm.Rect(log[0][1])
            except Exception:
                pass
            if b.get_area() >= 0.99 * page_rect.get_area():
                return True
        return False
    except Exception:
        return False


def plan_trim(pymupdf, docs, page_lists, threshold: float, force: bool):
    """为每个文档规划统一的裁白边矩形（返回 {doc_index: Rect|None}）。

    统一矩形保证同一文档各页缩放一致；若所有文档页面尺寸相同，则整体用同一个
    矩形，避免合并输出里出现大小不一。仅当白边足够多（>threshold 面积占比）才裁。
    """
    infos = []  # (doc_index, page_w, page_h, union_rect, bleed_ratio, page_area)
    for di, (doc, pages) in enumerate(zip(docs, page_lists)):
        if not pages:
            continue
        union = None
        page_area = 0.0
        bleed = 0
        for pno in pages:
            page = doc[pno]
            rect = page.rect
            page_area += rect.get_area()
            crect = page_content_rect(pymupdf, page)
            if crect is None:
                continue
            crect = pymupdf.Rect(crect) & rect
            if crect.get_area() >= 0.985 * rect.get_area():
                bleed += 1
            union = crect if union is None else (union | crect)
        # 所有页面外接矩形的并集（近似）
        w = max((doc[p].rect.width for p in pages), default=0)
        h = max((doc[p].rect.height for p in pages), default=0)
        bleeds = bleed / max(1, len(pages))
        if union is None or bleeds > 0.4:
            infos.append((di, w, h, None, bleeds, page_area))
        else:
            infos.append((di, w, h, pymupdf.Rect(union), bleeds, page_area))

    same_size = True
    sizes = {(round(i[1], 1), round(i[2], 1)) for i in infos}
    if len(sizes) > 1:
        same_size = False

    result = {}
    shared = None
    if same_size and infos and all(i[3] is not None for i in infos):
        shared = infos[0][3]
        for i in infos[1:]:
            shared = shared | i[3]
    for di, w, h, union, _bleeds, _page_area in infos:
        rect = shared if (same_size and shared is not None) else union
        if rect is None or (not force and not same_size and union is None):
            result[di] = None
            continue
        page_rect = pymupdf.Rect(0, 0, w, h)
        # 留 1.5mm 安全边
        rect = pymupdf.Rect(rect.x0 - 1.5 * MM, rect.y0 - 1.5 * MM,
                            rect.x1 + 1.5 * MM, rect.y1 + 1.5 * MM) & page_rect
        if rect.is_empty:
            result[di] = None
            continue
        saved = 1.0 - rect.get_area() / page_rect.get_area()
        if force or saved > threshold:
            result[di] = rect
        else:
            result[di] = None
    return result


def median_aspect(pymupdf, docs, page_lists, sample: int = 200):
    vals = []
    for doc, pages in zip(docs, page_lists):
        step = max(1, len(pages) // max(1, sample // max(1, len(docs))))
        for pno in pages[::step]:
            r = doc[pno].rect
            if r.height > 0:
                vals.append(r.width / r.height)
    if not vals:
        return 1.0
    vals.sort()
    return vals[len(vals) // 2]


def choose_grid(nup: int, aspect: float, paper_w_mm: float, paper_h_mm: float,
                margin_mm: float, gap_mm: float):
    """选出与源页面长宽比最接近的网格（列×行、纸张朝向）。"""
    best = None
    for sheet_w_mm, sheet_h_mm, orient in (
        (paper_w_mm, paper_h_mm, "portrait"),
        (paper_h_mm, paper_w_mm, "landscape"),
    ):
        for cols in range(1, nup + 1):
            if nup % cols:
                continue
            rows = nup // cols
            cw = (sheet_w_mm - 2 * margin_mm - (cols - 1) * gap_mm) / cols
            ch = (sheet_h_mm - 2 * margin_mm - (rows - 1) * gap_mm) / rows
            if cw < 20 or ch < 20:
                continue
            cell_aspect = cw / ch
            score = abs(math.log(cell_aspect / aspect))
            # 同分时偏好：横向排（阅读顺序从左到右）、少行多列
            score += 0.01 * (cols < rows) + 0.002 * rows
            if best is None or score < best[0]:
                best = (score, cols, rows, orient, cw, ch)
    if best is None:
        die("无法为该纸张尺寸与 N 值找到合适网格")
    return best[1:]


# ---------------------------------------------------------------- 拼版输出

class LabelWriter:
    """统一的小字标签/页脚写手（内置中文黑体，避免豆腐块）。"""

    def __init__(self, pymupdf, page, size=5.4, color=(0.42, 0.42, 0.42)):
        self.page = page
        self.color = color
        self.size = size
        self.font = None
        try:
            self.font = pymupdf.Font("china-s")  # 简体中文
        except Exception:
            self.font = None
        self.writer = None
        try:
            self.writer = pymupdf.TextWriter(page.rect)
            if self.font is not None:
                self.writer.append((0, 0), "", font=self.font, fontsize=size)
        except Exception:
            self.writer = None

    def add(self, x, y, text):
        if self.writer is None:
            with contextlib.suppress(Exception):
                self.page.insert_text((x, y), text, fontsize=self.size,
                                      fontname="helv", color=self.color)
            return
        with contextlib.suppress(Exception):
            self.writer.append((x, y), text, font=self.font, fontsize=self.size)

    def flush(self):
        if self.writer is None:
            return
        with contextlib.suppress(Exception):
            self.writer.write_text(self.page, color=self.color)


def text_width(writer: LabelWriter, text: str) -> float:
    if writer.font is None:
        return len(text) * writer.size * 0.55
    try:
        return writer.font.text_length(text, fontsize=writer.size)
    except Exception:
        return len(text) * writer.size * 0.55


def build(pymupdf, args, docs, page_lists, out_path):
    paper_w, paper_h = PAPERS[args.paper]
    margin, gap = args.margin, args.gap
    aspect = median_aspect(pymupdf, docs, page_lists)

    # ---- 输出序列：[(doc_index, pno)] ----
    seq = []
    for di, pages in enumerate(page_lists):
        for pno in pages:
            seq.append((di, pno))
    total_src = len(seq)
    if total_src == 0:
        die("没有可排版的页面")

    if args.booklet:
        return build_booklet(pymupdf, args, docs, page_lists, out_path,
                             paper_w, paper_h, aspect, total_src)

    # ---- 网格 ----
    if args.grid:
        cols, rows, orient = parse_grid(args.grid)
    else:
        nup = args.nup
        nup = (3 if aspect >= 1.15 else 2) if nup == "auto" else int(nup)
        cols, rows, orient, _cw, _ch = choose_grid(nup, aspect, paper_w, paper_h,
                                                 margin, gap)
    log(f"  排版：{args.paper.upper()} {'横向' if orient == 'landscape' else '纵向'} "
        f"{cols}×{rows} 网格（每面 {cols * rows} 页，双面后每张纸 {2 * cols * rows} 页）")
    if orient == "portrait":
        sheet_w, sheet_h = paper_w * MM, paper_h * MM
    elif orient == "landscape":
        sheet_w, sheet_h = paper_h * MM, paper_w * MM
    else:
        sheet_w, sheet_h = paper_w * MM, paper_h * MM

    cell_w = (sheet_w - 2 * margin * MM - (cols - 1) * gap * MM) / cols
    cell_h = (sheet_h - 2 * margin * MM - (rows - 1) * gap * MM) / rows
    cells = []
    for r in range(rows):
        for c in range(cols):
            x0 = margin * MM + c * (cell_w + gap * MM)
            y0 = margin * MM + r * (cell_h + gap * MM)
            cells.append(pymupdf.Rect(x0, y0, x0 + cell_w, y0 + cell_h))

    # ---- 装订线（正/背面两套格子） ----
    cells_front = sheet_cells(pymupdf, args, cells, 0)
    cells_back = sheet_cells(pymupdf, args, cells, 1)

    # ---- 裁白边 ----
    clips = {}
    if not args.no_trim and not args.booklet:
        clips = plan_trim(pymupdf, docs, page_lists,
                          threshold=args.trim_threshold, force=args.trim_force)
        clipped = sum(1 for v in clips.values() if v)
        if clipped:
            log(f"  裁白边：{clipped} 个文件将放大内容（白边利用率 ≥ "
                f"{int(args.trim_threshold * 100)}%）")

    # ---- 写页 ----
    out = pymupdf.open()
    sheet_idx = -1
    cell_idx = len(cells)
    use_labels = args.label != "none"
    if use_labels and args.label == "auto":
        prefixes = [auto_label_prefix([f]) for f in args.inputs]
    else:
        prefixes = [args.label] * len(docs)
    counters = [0] * len(docs)
    label_pad = max(2, len(str(max((len(p) for p in page_lists), default=1))))
    grid_labels: list[str] = []
    placements: dict[tuple[int, int], tuple[int, int]] = {}
    sheet_first_seq: list[int] = []
    deskew_angles: list[float] = []
    rotated_pages = 0
    progress_step = max(1, total_src // 10) if total_src >= 40 else 0

    for seq_no, (di, pno) in enumerate(seq, start=1):
        if progress_step and seq_no % progress_step == 0:
            log(f"  拼版 {seq_no * 100 // total_src}%（{seq_no}/{total_src} 页）")
        if cell_idx >= len(cells):
            sheet_idx += 1
            cell_idx = 0
            out.new_page(width=sheet_w, height=sheet_h)
            sheet_first_seq.append(seq_no)
        page = out[sheet_idx]
        cur_cells = cells_back if sheet_idx % 2 else cells_front
        doc = docs[di]
        clip = None
        planned = clips.get(di)
        if planned is not None:
            clip = pymupdf.Rect(planned) & doc[pno].rect
            if clip.is_empty:
                clip = None
        cell = cur_cells[cell_idx]
        rotate = 0
        if args.auto_rotate:
            rotate = decide_rotation(doc[pno].rect if clip is None else clip, cell)
            if rotate:
                rotated_pages += 1
        try:
            if args.gray_raster:
                # 光栅灰度：整页渲染成灰度 JPEG 再贴入格子，体积与墨量都最省，
                # 代价是文字不再可搜索/选中（适合扫描件与图片型课件）
                src_rect = doc[pno].rect if clip is None else clip
                # 旋转 90° 后显示尺寸互换，--dpi 按“打印到纸上的有效分辨率”折算
                disp_w = src_rect.height if rotate else src_rect.width
                disp_h = src_rect.width if rotate else src_rect.height
                aspect = disp_w / disp_h if disp_h else 1.0
                fit_w = min(cell.width, cell.height * aspect)
                zoom = (fit_w / 72.0 * args.dpi) / disp_w if disp_w else 1.0
                matrix = pymupdf.Matrix(zoom, zoom)
                if rotate:
                    matrix = matrix * pymupdf.Matrix(rotate)
                pm = doc[pno].get_pixmap(clip=clip, matrix=matrix,
                                         colorspace=pymupdf.csGRAY, alpha=False)
                if args.enhance or args.binarize or args.deskew:
                    data, _fmt, angle = clean_scan_image(
                        pymupdf, pm, args, binarize=bool(args.binarize))
                    if angle is not None:
                        deskew_angles.append(angle)
                else:
                    data = pm.tobytes("jpeg", jpg_quality=args.quality)
                page.insert_image(cell, stream=data, keep_proportion=True)
            else:
                page.show_pdf_page(cell, doc, pno, clip=clip, rotate=rotate)
        except Exception as exc:
            log(f"  警告：第 {pno + 1} 页放置失败（{exc}），跳过")
        placements[(di, pno)] = (sheet_idx, cell_idx)
        counters[di] += 1
        if use_labels:
            grid_labels.append(f"{prefixes[di]}-{counters[di]:0{label_pad}d}")
        cell_idx += 1

    # ---- 标签 / 边框 / 裁切线 / 页脚 ----
    sheets = out.page_count
    for si in range(sheets):
        page = out[si]
        cells_si = cells_back if si % 2 else cells_front
        w = LabelWriter(pymupdf, page, size=5.4)
        if use_labels:
            for ci, cell in enumerate(cells_si):
                li = si * len(cells) + ci
                if li >= len(grid_labels):
                    break
                x = cell.x0
                y = max(cell.y0 - 1.6, 2.0)
                if y >= cell.y0:  # 没有间隙时放进格内左上角
                    y = cell.y0 + 5.0
                w.add(x, y, grid_labels[li])
        if args.footer != "none" and sheets > 1:
            text = f"第 {si + 1} 张 / 共 {sheets} 张" if args.footer == "auto" else args.footer
            tw = text_width(w, text)
            w.add((sheet_w - tw) / 2, sheet_h - margin * MM * 0.45, text)
        w.flush()
        if args.frame != "none":
            color = (0.72, 0.72, 0.72) if args.frame == "thin" else (0.45, 0.45, 0.45)
            for cell in cells_si:
                page.draw_rect(cell, color=color, width=0.35)
        if args.mark and (cols > 1 or rows > 1):
            for c in range(1, cols):
                x = margin * MM + c * (cell_w + gap * MM) - gap * MM / 2
                page.draw_line((x, margin * MM * 0.6), (x, sheet_h - margin * MM * 0.6),
                               color=(0.6, 0.6, 0.6), width=0.3,
                               dashes="[2 2] 0")
            for r in range(1, rows):
                y = margin * MM + r * (cell_h + gap * MM) - gap * MM / 2
                page.draw_line((margin * MM * 0.6, y), (sheet_w - margin * MM * 0.6, y),
                               color=(0.6, 0.6, 0.6), width=0.3,
                               dashes="[2 2] 0")

    # ---- 双面补页 / 短边翻页 ----
    padded = False
    if args.pad_duplex and out.page_count % 2 == 1:
        out.new_page(width=sheet_w, height=sheet_h)
        padded = True
    if args.rotate_back:
        for i in range(1, out.page_count, 2):
            with contextlib.suppress(Exception):
                out[i].set_rotation(180)

    return save_and_report(pymupdf, args, out, out_path, {
        "sheets": out.page_count,
        "source_pages": total_src,
        "grid": f"{cols}x{rows}",
        "orientation": orient,
        "paper": args.paper,
        "gray": bool(args.gray or args.gray_raster),
        "enhance": bool(args.enhance or args.binarize or args.deskew),
        "binarize": bool(args.binarize),
        "deskew_angles": deskew_angles,
        "rotated_pages": rotated_pages,
        "padded": padded,
        "booklet": False,
        "placements": placements,
        "sheet_first_seq": sheet_first_seq,
        "cells": cells,
        "docs": docs,
        "page_lists": page_lists,
    })


def decide_rotation(src_rect, cell, threshold: float = 0.18) -> int:
    """混排文档自动旋转：竖格放横页（或反之）明显更省地方时转 90°。"""
    if src_rect.height <= 0 or cell.height <= 0:
        return 0
    src_aspect = src_rect.width / src_rect.height
    cell_aspect = cell.width / cell.height
    upright = abs(math.log(cell_aspect / src_aspect))
    turned = abs(math.log(cell_aspect / (1.0 / src_aspect)))
    return 90 if turned + threshold < upright else 0


def sheet_cells(pymupdf, args, base_cells, page_index):
    """按装订线需求收缩格子：--gutter 在装订侧留边，--mirror 让背面（偶数面）镜像。

    装订后靠书脊的一侧会被吃掉几毫米，把该侧格子收窄即可让内容避开装订线。
    """
    g = args.gutter * MM
    if g <= 0:
        return base_cells
    side = args.gutter_side
    if args.mirror and page_index % 2 == 1:
        side = "right" if side == "left" else "left"
    out = []
    for cell in base_cells:
        rect = pymupdf.Rect(cell)
        if side == "left":
            rect.x0 += g
        else:
            rect.x1 -= g
        # 收缩过多（边距把格子挤没了）时退回原格，避免内容消失
        out.append(rect if rect.width > 15 and rect.height > 15 else pymupdf.Rect(cell))
    return out


def parse_grid(text: str):
    m = re.match(r"\s*(\d)\s*[x×]\s*(\d)\s*$", text)
    if not m:
        die(f"--grid 需要形如 2x2 的格式，收到：{text}")
    cols, rows = int(m.group(1)), int(m.group(2))
    orient = "landscape" if cols >= rows else "portrait"
    return cols, rows, orient


def auto_label_prefix(inputs):
    """从文件名里取一个短前缀，如「L1-引言.pdf」→ L1，「第2章.pdf」→ 第2章。"""
    stem = os.path.splitext(os.path.basename(inputs[0]))[0]
    stem = re.sub(r"^[\d\s\.\-_]+", "", stem).strip()
    m = re.match(r"([A-Za-z]+\d{1,3})", stem)
    if m:
        return m.group(1)
    m = re.match(r"(第\s*[一二三四五六七八九十\d]+\s*[章讲])", stem)
    if m:
        return re.sub(r"\s+", "", m.group(1))
    return (stem[:6] or "P")


def build_booklet(pymupdf, args, docs, page_lists, out_path,
                  paper_w, paper_h, aspect, total_src):
    """小册子拼版：横向 A4 对折成 A5，骑马钉顺序，双面长边翻页后中间装订。"""
    margin, gap = args.margin, args.gap
    sheet_w, sheet_h = paper_h * MM, paper_w * MM  # 横向
    n = total_src
    per_sheet = 2
    sheets_needed = math.ceil(n / (2 * per_sheet))  # 每张纸 4 面
    padded_n = sheets_needed * 2 * per_sheet
    seq = [None] * padded_n
    order = []
    for s in range(sheets_needed):
        order.append((padded_n - 2 * s, 2 * s + 1))
        order.append((2 * s + 2, padded_n - 2 * s - 1))
    flat = [p for pair in order for p in pair]
    for i, val in enumerate(flat):
        seq[i] = val - 1 if val <= n else None

    # 版面：横向 A4 左右各一个 A5 竖版格
    cell_w = (sheet_w - 2 * margin * MM - gap * MM) / 2
    cell_h = sheet_h - 2 * margin * MM
    left = pymupdf.Rect(margin * MM, margin * MM, margin * MM + cell_w, margin * MM + cell_h)
    right = pymupdf.Rect(left.x1 + gap * MM, margin * MM, left.x1 + gap * MM + cell_w,
                         margin * MM + cell_h)
    if args.gutter > 0:
        # 对折装订：中缝两侧各留出装订线，正背面天然对称，无需 --mirror
        g = args.gutter * MM
        if left.width - g > 15 and right.width - g > 15:
            left.x1 -= g
            right.x0 += g

    clips = {}
    if not args.no_trim:
        clips = plan_trim(pymupdf, docs, page_lists,
                          threshold=args.trim_threshold, force=args.trim_force)

    flat_pages = [(di, pno) for di, pages in enumerate(page_lists) for pno in pages]
    out = pymupdf.open()
    placements: dict[tuple[int, int], tuple[int, int]] = {}
    sheet_first_seq: list[int] = []
    for i in range(0, len(seq), 2):
        out.new_page(width=sheet_w, height=sheet_h)
        page = out[len(out) - 1]
        pair = seq[i:i + 2]
        if len(seq) >= 40 and i and i % 40 == 0:
            log(f"  拼版 {i * 100 // len(seq)}%（{i}/{len(seq)} 页）")
        first = next((i + slot for slot, item in enumerate(pair)
                      if item is not None and item < len(flat_pages)), None)
        sheet_first_seq.append((first + 1) if first is not None
                              else (sheet_first_seq[-1] if sheet_first_seq else 1))
        for slot, item in enumerate(pair):
            if item is None or item >= len(flat_pages):
                continue
            di, pno = flat_pages[item]
            doc = docs[di]
            planned = clips.get(di)
            clip = None
            if planned is not None:
                clip = pymupdf.Rect(planned) & doc[pno].rect
                if clip.is_empty:
                    clip = None
            try:
                page.show_pdf_page(left if slot == 0 else right, doc, pno, clip=clip)
            except Exception as exc:
                log(f"  警告：小册子第 {pno + 1} 页放置失败（{exc}）")
            placements[(di, pno)] = (i // 2, slot)
    if args.rotate_back:
        for i in range(1, out.page_count, 2):
            with contextlib.suppress(Exception):
                out[i].set_rotation(180)
    return save_and_report(pymupdf, args, out, out_path, {
        "sheets": out.page_count,
        "source_pages": total_src,
        "grid": "1x2-booklet",
        "orientation": "landscape",
        "paper": args.paper,
        "gray": bool(args.gray or args.gray_raster),
        "enhance": bool(args.enhance or args.binarize or args.deskew),
        "binarize": bool(args.binarize),
        "padded": padded_n != n,
        "booklet": True,
        "placements": placements,
        "sheet_first_seq": sheet_first_seq,
        "cells": [left, right],
        "docs": docs,
        "page_lists": page_lists,
    })


# ---------------------------------------------------------------- 保存与报告

def apply_outline(pymupdf, args, out, info) -> int:
    """把源文档书签映射到拼版后的「第几张/哪一格」，写进输出目录。"""
    if args.outline == "none":
        return 0
    max_level = None
    if args.outline != "auto":
        try:
            max_level = int(args.outline)
        except ValueError:
            die(f"--outline 只支持 auto、none 或级别数字，收到：{args.outline}")
    placements = info.get("placements") or {}
    cells = info.get("cells") or []
    entries = []
    for di, doc in enumerate(info.get("docs") or []):
        try:
            toc = doc.get_toc()
        except Exception:
            toc = []
        if not toc:
            continue
        included = info["page_lists"][di]
        included_set = set(included)
        last = max(included) if included else -1
        for lvl, title, page in toc:
            pno = page - 1
            if pno not in included_set:
                # 被 --pages 剔掉的页：改指向其后第一个仍保留的页
                if pno > last:
                    continue
                pno = next((p for p in included if p >= pno), None)
                if pno is None:
                    continue
            spot = placements.get((di, pno))
            if not spot:
                continue
            sheet_idx, cell_idx = spot
            if max_level is not None and lvl > max_level:
                continue
            dest = {"kind": pymupdf.LINK_GOTO, "page": sheet_idx}
            if 0 <= cell_idx < len(cells):
                rect = sheet_cells(pymupdf, args, [cells[cell_idx]], sheet_idx)[0]
                dest["to"] = pymupdf.Point(rect.x0 + 1, rect.y0 + 1)
            entries.append([lvl, title, sheet_idx + 1, dest])
    if not entries:
        return 0
    # 层级规范化：首条为 1 级、不得跳级（过滤或缺页后可能破坏层级）
    fixed = []
    prev = 0
    for lvl, title, page, dest in entries:
        lvl = max(1, min(lvl, prev + 1))
        fixed.append([lvl, title, page, dest])
        prev = lvl
    try:
        out.set_toc(fixed)
    except Exception as exc:
        log(f"  提示：书签写入失败（{exc}）")
        return 0
    return len(fixed)


def apply_page_labels(pymupdf, args, out, info) -> int:
    """给每张纸打页标签：标签号 = 该张第一个格对应的源页序号（1 基）。

    阅读器把标签显示在页边，翻到某张就能对上它是从源文档第几页开始的。
    """
    if args.page_labels == "none" or not hasattr(out, "set_page_labels"):
        return 0
    firsts = info.get("sheet_first_seq") or []
    if not firsts:
        return 0
    labels = [{"startpage": i, "prefix": "", "style": "D",
               "firstpagenum": max(1, int(no))} for i, no in enumerate(firsts)]
    try:
        out.set_page_labels(labels)
    except Exception as exc:
        log(f"  提示：页标签写入失败（{exc}）")
        return 0
    return len(labels)


def visual_diff(pymupdf, path_a: str, path_b: str, dpi: int = 42,
                max_pages: int = 6) -> float:
    """低清渲染两个 PDF 后比较平均像素差（0-255），作为图片瘦身的保真闸门。"""
    a = pymupdf.open(path_a)
    b = pymupdf.open(path_b)
    try:
        if a.page_count != b.page_count or a.page_count == 0:
            return 999.0
        step = max(1, a.page_count // max_pages)
        total = 0
        count = 0
        for i in range(0, a.page_count, step):
            pa = a[i].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            pb = b[i].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            if pa.width != pb.width or pa.height != pb.height:
                return 999.0
            sa, sb = pa.samples, pb.samples
            n = min(len(sa), len(sb))
            for j in range(0, n, 29):  # 抽样比较，快且够灵敏
                total += abs(sa[j] - sb[j])
                count += 1
        return total / count if count else 999.0
    finally:
        a.close()
        b.close()


def save_and_report(pymupdf, args, out, out_path, info):
    out.set_metadata({
        "title": os.path.splitext(os.path.basename(out_path))[0],
        "author": CREATOR_TAG,
        "creator": CREATOR_TAG,
        "subject": (f"{info['grid']} 拼版省纸打印版"
                    + ("（小册子）" if info["booklet"] else "")
                    + ("（灰度省墨）" if info["gray"] else "")),
        "producer": CREATOR_TAG,
    })
    outline_count = apply_outline(pymupdf, args, out, info)
    label_count = apply_page_labels(pymupdf, args, out, info)
    if args.dry_run:
        log("  预演：只报告排版结果，不写出文件")
        out.close()
        return finish_report(args, info, out_path, outline_count, label_count,
                             optimized=False, previews=[], dry_run=True)
    if not args.no_subset_fonts:
        try:
            out.subset_fonts()  # CJK 课件字体子集化，通常体积减半
        except Exception as exc:
            log(f"  提示：字体子集化跳过（{exc}）")

    big_job = info["sheets"] > 30 or sum(os.path.getsize(p)
                                         for p in args.inputs) > 20 * 1048576
    if big_job:
        log("  写出文件（大文档较慢，请稍候）…")
    plain_path = out_path + ".plain.tmp"
    # garbage=3/4 的跨对象去重在大文档上要花 1-2 分钟，只换约 10% 体积；
    # 默认用 garbage=2（逐对象清理，速度快），--compact 时才做深度去重。
    save_kw = {"garbage": 4 if args.compact else 2, "clean": True, "deflate": True,
                   "deflate_images": True, "deflate_fonts": True}
    out.save(plain_path, **save_kw)
    best_path = plain_path
    optimized = False
    if args.optimize != "off":
        try:
            cand = out_path + ".opt.tmp"
            tmp = pymupdf.open(plain_path)
            tmp.rewrite_images(dpi_threshold=int(args.dpi * 1.6),
                               dpi_target=args.dpi, quality=args.quality)
            tmp.save(cand, use_objstms=1, **save_kw)
            tmp.close()
            if os.path.getsize(cand) < os.path.getsize(plain_path) * 0.995:
                diff = visual_diff(pymupdf, plain_path, cand)
                if diff <= 0.6:
                    os.replace(cand, best_path)
                    optimized = True
                else:
                    log(f"  提示：图片瘦身候选与原件差异过大（{diff:.2f}/255），已放弃")
                    os.remove(cand)
            else:
                os.remove(cand)
        except Exception as exc:
            log(f"  提示：图片瘦身跳过（{exc}）")
    if big_job:
        log("  校验输出…")
    # 校验再落盘，避免半成品覆盖用户的输出
    try:
        check = pymupdf.open(best_path)
        pages_ok = check.page_count == info["sheets"]
        # 抽样渲染确认可打印（同时触发字体/资源错误）
        for i in range(0, check.page_count, max(1, check.page_count // 3)):
            check[i].get_pixmap(dpi=36)
        check.close()
    except Exception as exc:
        os.remove(best_path)
        die(f"输出校验失败（{exc}），已放弃写入，请反馈此问题")
    if not pages_ok:
        os.remove(best_path)
        die("输出校验失败（页数不一致），已放弃写入，请反馈此问题")
    if os.path.exists(out_path) and not args.force:
        try:
            probe = pymupdf.open(out_path)
            foreign = (probe.metadata or {}).get("creator") != CREATOR_TAG
            probe.close()
        except Exception:
            foreign = True
        if foreign:
            os.remove(best_path)
            die(f"输出文件已存在且不是本工具生成的：{out_path}\n"
                f"如需覆盖请加 --force，或用 -o 指定别的文件名")
    os.replace(best_path, out_path)
    out.close()
    previews = write_previews(pymupdf, args, out_path, info)
    return finish_report(args, info, out_path, outline_count, label_count,
                         optimized=optimized, previews=previews, dry_run=False)


def write_previews(pymupdf, args, out_path, info) -> list:
    """写出前几张的低清预览 PNG，便于打印前一键检查。"""
    if not args.preview:
        return 0
    try:
        doc = pymupdf.open(out_path)
    except Exception:
        return []
    paths = []
    try:
        count = min(max(1, args.preview), doc.page_count)
        stem = os.path.splitext(out_path)[0]
        for i in range(count):
            path = f"{stem}_预览{i + 1}.png"
            doc[i].get_pixmap(dpi=80).save(path)
            paths.append(path)
    except Exception as exc:
        log(f"  提示：预览图生成失败（{exc}）")
    finally:
        doc.close()
    return paths


def finish_report(args, info, out_path, outline_count, label_count, optimized,
                  previews, dry_run) -> dict:
    """算省纸账/成本/体积，打印人类报告或输出 JSON。dry-run 与正常路径共用。"""
    src_size = sum(os.path.getsize(p) for p in args.inputs)
    exists = os.path.exists(out_path)
    out_size = os.path.getsize(out_path) if exists else 0
    src_pages = info["source_pages"]
    sheets = info["sheets"]
    paper_duplex_now = math.ceil(sheets / 2)
    paper_duplex_orig = math.ceil(src_pages / 2)
    saved = 1 - paper_duplex_now / paper_duplex_orig if paper_duplex_orig else 0
    saved_single = (1 - paper_duplex_now / src_pages) * 100 if src_pages else 0
    size_pct = (out_size / src_size - 1) * 100 if (src_size and exists) else 0

    report = {
        "output": os.path.abspath(out_path),
        "dry_run": bool(dry_run),
        "input_files": [os.path.abspath(p) for p in args.inputs],
        "source_pages": src_pages,
        "sheets": sheets,
        "paper_sheets_duplex": paper_duplex_now,
        "paper_sheets_if_duplex_original": paper_duplex_orig,
        "paper_saved_percent": round(saved * 100, 1),
        "paper_saved_vs_single_percent": round(saved_single, 1),
        "grid": info["grid"],
        "orientation": info["orientation"],
        "booklet": info["booklet"],
        "gray": info["gray"],
        "enhance": bool(info.get("enhance")),
        "binarize": bool(info.get("binarize")),
        "deskew_angles": list(info.get("deskew_angles") or []),
        "rotated_pages": int(info.get("rotated_pages") or 0),
        "size_before_mb": round(src_size / 1048576, 2),
        "size_after_mb": round(out_size / 1048576, 2),
        "size_change_percent": round(size_pct, 1),
        "optimized_images": optimized,
        "subset_fonts": not args.no_subset_fonts,
        "outline_entries": outline_count,
        "page_label_sheets": label_count,
        "cost_per_sheet": args.cost,
        "cost_saved_vs_single": round((src_pages - paper_duplex_now) * args.cost, 2),
        "cost_saved_vs_duplex": round((paper_duplex_orig - paper_duplex_now) * args.cost, 2),
        "gutter_mm": args.gutter,
        "mirror": bool(args.mirror),
        "previews": previews,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return report

    if info["booklet"]:
        layout_txt = f"{args.paper.upper()} 对折 A5，双面后每张纸 4 个 A5 面"
    else:
        c, r = info["grid"].split("x")
        orient_txt = "横向" if info["orientation"] == "landscape" else "纵向"
        layout_txt = (f"{args.paper.upper()} {orient_txt} {c}×{r} 网格，"
                      f"双面后每张纸 {2 * int(c) * int(r)} 页")
    print()
    print("省纸打印 · " + ("排版预演" if dry_run else "拼版完成"))
    print(f"  输入    {len(args.inputs)} 个文件，共 {src_pages} 页"
          + ("（按文件名自然排序）" if not args.no_sort and len(args.inputs) > 1 else ""))
    print(f"  排版    {layout_txt}，输出 {sheets} 面"
          + ("，已补空白面便于双面" if info["padded"] else ""))
    print(f"  输出    {out_path}" + ("（预演，未写出文件）" if dry_run else ""))
    print(f"  省纸    原样单面 {src_pages} 张 → 省纸版双面 {paper_duplex_now} 张"
          f"（省 {saved_single:.0f}%；若原样也双面 {paper_duplex_orig} 张，省 "
          f"{report['paper_saved_percent']:.0f}%）")
    if args.cost > 0:
        single_cost = src_pages * args.cost
        new_cost = paper_duplex_now * args.cost
        dup_cost = paper_duplex_orig * args.cost
        print(f"  成本    按 {args.cost:g} 元/张：原样单面 {single_cost:.2f} 元 → "
              f"省纸版 {new_cost:.2f} 元（省 {single_cost - new_cost:.2f} 元；"
              f"若原样也双面省 {dup_cost - new_cost:.2f} 元）")
    if not dry_run:
        size_txt = (f"{report['size_before_mb']} MB → {report['size_after_mb']} MB"
                    f"（{'+' if size_pct >= 0 else ''}{size_pct:.0f}%）")
        if optimized:
            size_txt += "，已做图片瘦身"
        elif size_pct > 5:
            size_txt += "，可用 --quality 60 --dpi 120 再压"
        ink_note = ""
        if info.get("enhance"):
            what = "去底灰+二值化" if info.get("binarize") else "去底灰"
            angles = info.get("deskew_angles") or []
            if angles:
                mid = sorted(angles)[len(angles) // 2]
                what += f"，去歪斜 {len(angles)} 页（中位 {mid:g}°）"
            ink_note = "；扫描件清理：" + what
        print(f"  体积    {size_txt}"
              + ("；灰度省墨：开" if info["gray"] else "") + ink_note)
    nav = []
    if outline_count:
        nav.append(f"书签 {outline_count} 条（点击跳到对应格）")
    if label_count:
        nav.append("页标签按该张首个源页号标注")
    if nav:
        print("  导航    " + "；".join(nav))
    if info.get("rotated_pages"):
        print(f"  旋转    混排页自动转正 {info['rotated_pages']} 页（--auto-rotate）")
    if args.gutter > 0:
        print(f"  装订    {args.gutter:g}mm 装订线"
              + ("（背面镜像，双面长边翻页）" if args.mirror else "")
              + ("，收向中缝" if info["booklet"] else ""))
    if previews:
        print("  预览    " + "、".join(os.path.basename(p) for p in previews))
    if not dry_run:
        print("  打印    100% 比例、双面长边翻页、关闭“适合页面/适应纸张”")
    if args.rotate_back:
        print("  提示    已按短边翻页旋转背面（--rotate-back）")
    return report


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="pack.py",
        description="把 PDF 拼成省纸打印版（N 合 1 + 省墨 + 瘦身）",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("inputs", nargs="+", help="输入 PDF（可多个，按文件名自然排序）")
    p.add_argument("-o", "--out", help="输出 PDF 路径（默认：输入同目录 _省纸打印版.pdf）")
    p.add_argument("--nup", default="auto",
                   help="每张纸拼几页：auto|2|3|4|6|8|9|12|16，也接受 3in1 写法（默认 auto）")
    p.add_argument("--grid", help="手动指定网格，如 2x2、1x3（覆盖 --nup）")
    p.add_argument("--paper", default="a4", choices=sorted(PAPERS), help="纸张（默认 a4）")
    p.add_argument("--margin", type=float, default=8.0, help="页边距 mm（默认 8）")
    p.add_argument("--gap", type=float, default=3.0, help="格间距 mm（默认 3）")
    p.add_argument("--frame", default="none", choices=["none", "thin", "box"],
                   help="每格边框：none|thin|box（默认 none）")
    p.add_argument("--mark", action="store_true", help="画裁切线（虚线的格间分界）")
    p.add_argument("--label", default="auto",
                   help="每格页标：auto|none|自定义前缀（如 L1 → L1-01…）")
    p.add_argument("--footer", default="auto",
                   help="页脚：auto（第 i 张/共 N 张）|none|自定义文字")
    p.add_argument("--no-trim", action="store_true", help="不裁白边（默认自动裁）")
    p.add_argument("--trim-force", action="store_true", help="强制裁白边（忽略阈值）")
    p.add_argument("--trim-threshold", type=float, default=0.94,
                   help="白边占比超过该值才裁（默认 0.94，即省 6%% 以上才裁）")
    p.add_argument("--cost", type=float, default=0.0, metavar="元/张",
                   help="每张纸单价（元），给出本次实际省下的钱（默认 0 不显示）")
    p.add_argument("--gutter", type=float, default=0.0,
                   help="装订线 mm：在装订侧额外留边（默认 0）；小册子自动朝中缝")
    p.add_argument("--mirror", action="store_true",
                   help="双面装订：背面（偶数面）镜像装订线方向")
    p.add_argument("--gutter-side", default="left", choices=["left", "right"],
                   help="装订边在左还是右（默认 left）")
    p.add_argument("--gray", action="store_true",
                   help="转灰度省彩色墨（矢量级转换，文字仍可搜索；走临时副本，不动原文件）")
    p.add_argument("--enhance", action="store_true",
                   help="扫描件清理：去底灰+对比伸展（有 Pillow 时另做轻度去噪），隐含光栅灰度")
    p.add_argument("--auto-rotate", action="store_true",
                   help="混排文档：横页放进竖格（或反之）明显更合适时自动转 90°")
    p.add_argument("--deskew", action="store_true",
                   help="自动校正扫描倾斜（行投影法，需 Pillow；建议与 --enhance 同用）")
    p.add_argument("--binarize", action="store_true",
                   help="二值化黑白（Otsu 阈值，隐含 --enhance；适合纯文字扫描件，最省墨）")
    p.add_argument("--gray-raster", action="store_true",
                   help="光栅灰度：整页转灰度 JPEG（体积/墨量最省，文字不可搜索；--dpi/--quality 生效）")
    p.add_argument("--pad-duplex", action="store_true", help="补空白页使总面数为偶数（双面不打乱）")
    p.add_argument("--rotate-back", action="store_true",
                   help="短边翻页：把背面旋转 180°（长边翻页不要加）")
    p.add_argument("--booklet", action="store_true",
                   help="小册子拼版：对折成 A5，骑马钉顺序（忽略 --nup）")
    p.add_argument("--pages", help="只取这些页，如 1-5,8,11-（对每个输入分别生效）")
    p.add_argument("--page-labels", default="auto", choices=["auto", "none"],
                   help="输出页标签：auto 用“该张首个源页号”标注（默认）|none 关闭")
    p.add_argument("--outline", default="auto",
                   help="书签目录：auto（源有目录就保留并映射到张/格）|none|数字（保留到第几级）")
    p.add_argument("--skip-blank", action="store_true", help="跳过空白页")
    p.add_argument("--no-sort", action="store_true", help="保持命令行给出的顺序（默认按文件名自然排序）")
    p.add_argument("--password", help="加密 PDF 的打开密码")
    p.add_argument("--optimize", default="auto", choices=["auto", "off"],
                   help="图片瘦身（默认 auto：只在不增大文件且画面差异可忽略时采用）")
    p.add_argument("--dpi", type=int, default=200, help="图片降采样上限 dpi（默认 200）")
    p.add_argument("--quality", type=int, default=75, help="JPEG 重编码质量（默认 75）")
    p.add_argument("--no-subset-fonts", action="store_true",
                   help="关闭字体子集化（默认开启：CJK 课件通常体积减半）")
    p.add_argument("--force", action="store_true", help="允许覆盖已存在的非本工具输出")
    p.add_argument("--dry-run", action="store_true",
                   help="只做排版预演并报告省纸账，不写出文件")
    p.add_argument("--preview", type=int, default=0, metavar="N",
                   help="输出前 N 张的低清预览 PNG（如 --preview 2），打印前先看一眼")

    p.add_argument("--fast", action="store_true",
                   help="快速模式：跳过字体子集化与图片瘦身（大文件/批量拼版时快很多）")
    p.add_argument("--compact", action="store_true",
                   help="深度去重存盘（再省约 10%% 体积，但大文件会慢 1-2 分钟）")
    p.add_argument("--verbose", action="store_true", help="显示 MuPDF 对源文件的内部告警")
    p.add_argument("--json", action="store_true", help="以 JSON 输出结果报告")
    return p.parse_args(argv)


def main(argv=None):
    pymupdf = load_pymupdf()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    quiet_mupdf(pymupdf, args.verbose)
    gate_capabilities(pymupdf, args)
    # 3in1 / 2合1 之类的写法
    m = re.fullmatch(r"(\d+)\s*(?:in|合|:)\s*1", str(args.nup))
    if m:
        args.nup = m.group(1)
    args.margin = max(0.0, args.margin)
    args.gap = max(0.0, args.gap)
    if args.fast:
        args.no_subset_fonts = True
        args.optimize = "off"
    if args.enhance or args.binarize or args.deskew:
        args.gray_raster = True          # 清理像素必然走光栅输出
    if args.deskew:
        try:
            import PIL  # noqa: F401
        except ImportError:
            die("--deskew 需要 Pillow：pip install pillow")

    for f in args.inputs:
        if not os.path.isfile(f):
            die(f"找不到输入文件：{f}")

    files = list(args.inputs)
    if not args.no_sort and len(files) > 1:
        files = sorted(files, key=natural_key)
    # 让下游（页标前缀、报告、体积统计）与真实处理顺序一致：
    # 此前 args.inputs 仍是命令行原顺序，页标前缀会张冠李戴（同名文件互换）
    args.inputs = files

    docs, page_lists = [], []
    temps: list[str] = []
    try:
        for f in files:
            doc = pymupdf.open(f)
            if doc.needs_pass and not doc.authenticate(args.password or ""):
                die(f"PDF 需要密码或密码错误：{f}")
            if args.gray:
                log("  灰度省墨：逐份转灰度（临时副本，不动原文件）")
                doc = gray_sanitize(pymupdf, doc, temps)
            pages = parse_pages_spec(args.pages, doc.page_count)
            if args.skip_blank:
                pages = [p for p in pages if not is_blank_page(doc[p])]
            docs.append(doc)
            page_lists.append(pages)
    except SystemExit:
        raise
    except Exception as exc:
        die(f"打开 PDF 失败：{exc}")

    if not args.json:
        log(f"输入：{len(files)} 个文件，"
            f"{sum(len(p) for p in page_lists)} 页"
            + ("" if args.no_sort else "（按文件名自然排序）"))

    if not args.out:
        if len(files) == 1:
            stem = os.path.splitext(files[0])[0]
            args.out = stem + "_省纸打印版.pdf"
        else:
            folder = os.path.dirname(os.path.abspath(files[0]))
            args.out = os.path.join(folder, "合并_省纸打印版.pdf")

    if args.booklet and args.gray_raster:
        die("--booklet 暂不支持 --gray-raster，请改用 --gray")
    try:
        build(pymupdf, args, docs, page_lists, args.out)
    finally:
        for d in docs:
            with contextlib.suppress(Exception):
                d.close()
        for tmp in temps:
            with contextlib.suppress(OSError):
                os.remove(tmp)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
