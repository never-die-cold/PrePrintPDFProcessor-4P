# PDF 省纸打印助手（pdf-print-pack）

把“要打印的 PDF 太费纸、太费墨、太大、版式不适合打印”变成一条命令。
核心算术：**原样单面打印 P 页 = P 张纸；N 合 1 双面打印 = ⌈P/2N⌉ 张纸**。

## 能力

- **一键 N 合 1 拼版**：2/3/4/6/8/9/12/16 页拼到一张 A4，自动判断横排课件（3 合 1，与《数电课件_3合1_讲义版.pdf》同规格）与纵排文档（2 合 1，双面 4 页/张）。
- **省纸细节**：自动裁白边并放大内容、每格页标（`L1-01…`）、格间虚线裁切线、页脚“第 i 张/共 N 张”、`--pad-duplex` 补偶面、`--rotate-back` 适配短边翻转。
- **省墨**：`--gray` 矢量级灰度转换（文字保持清晰、可搜索）；`--gray-raster` 整页灰度 JPEG（体积最小，文字不可搜索，适合扫描件）。
- **瘦身**：图片降采样 ≤200dpi 与 JPEG 重编码，只在体积变小且画面差异可忽略（自动像素级校验）时采用；字体自动子集化。报告给出前后体积。
- **小册子**：`--booklet` 对折 A5、骑马钉顺序，双面长边翻转后沿中线装订。
- **讲义重排**（技能路径 B）：按仓库既有《…_学习讲义_2合1省纸打印版》版式把课件改写成浓缩讲义；主题 CSS、HTML 骨架、Edge 无头打印脚本都在 `skills/pdf-print-pack/` 内。

## 快速开始

```bash
# 一键（推荐先跑这个）
python skills/pdf-print-pack/scripts/pack.py 课件.pdf

# 常用组合
python skills/pdf-print-pack/scripts/pack.py 课件.pdf --nup 6 --gray --pad-duplex
python skills/pdf-print-pack/scripts/pack.py 第*.pdf -o 课程_省纸打印版.pdf
python skills/pdf-print-pack/scripts/pack.py 讲义.pdf --booklet
```

安装后在 ZCode 里也可以直接输入 `/print-pack <PDF 路径>`，或直接说“帮我把这个 PDF 省纸打印”。

## Windows 右键「发送到」一键

```powershell
powershell -ExecutionPolicy Bypass -File tools/install-sendto.ps1
# 卸载：同上加 -Remove
```

安装后在资源管理器里选中一个或多个 PDF → 右键 → **发送到 → 省纸打印**，即完成拼版并停在窗口里显示省纸账。

## 依赖

- Python 3 + `pip install pymupdf`（拼版）
- Microsoft Edge 或 Google Chrome（仅讲义重排需要；Windows 自带 Edge）

## 输出约定

- 输出 `<输入名>_省纸打印版.pdf`，绝不修改输入文件；同名输出若不是本工具生成的会拒绝覆盖（`--force` 才覆盖）。
- 报告示例：`原样双面 193 张 → 省纸版双面 49 张（省 75%）`。
