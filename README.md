# PrePrintPDFProcessor-4P

把要打印的 PDF 变成**省纸、省墨、方便打印**的版本：一键把 N 页拼到一张 A4（双面打印后每张纸 2N 页）、
自动裁白边放大内容、灰度省墨、双面补页、图片降采样与字体子集化瘦身；也可以把课件重排成
“2 合 1 浓缩讲义”（A4 横向每张纸两个逻辑页，双面 4 页/张）。

核心算术：**原样单面打印 P 页 = P 张纸；N 合 1 双面打印 = ⌈P/2N⌉ 张纸。**

本仓库同时是一个 [ZCode](https://zcode.ai) 插件（`pdf-print-pack`）：装进 ZCode 后可以直接说
“把这份课件省纸打印”，或使用 `/print-pack` 命令。

## 目录结构

```text
plugins/
  marketplace.json                  # 本地开发市场目录（ZCode「添加插件市场」指向这里）
  pdf-print-pack/                   # 插件本体
    .zcode-plugin/plugin.json       # 插件清单
    README.md                       # 插件使用说明
    commands/print-pack.md          # /print-pack 一键命令
    skills/pdf-print-pack/
      SKILL.md                      # 工作流说明（拼版 / 讲义重排 / 速查）
      scripts/pack.py               # 省纸打印拼版引擎（核心）
      scripts/html2pdf.py           # Edge/Chrome 无头 HTML→PDF（讲义模式用）
      assets/handout-theme.css      # 2 合 1 讲义主题样式
      assets/handout-skeleton.html  # 讲义 HTML 骨架模板
    tests/                          # 回归测试（只依赖 pymupdf）
```

## 安装到 ZCode

1. 克隆本仓库到本地，例如 `git clone https://github.com/never-die-cold/PrePrintPDFProcessor-4P.git`。
2. 打开 **插件市场 → 添加 → 添加插件市场**，粘贴仓库内的 `plugins` 目录（绝对路径）并添加。
3. 在 **个人 → 该市场 → PDF 省纸打印 → 安装**，然后在 **设置 → 插件** 里确认已启用。
4. 新任务里输入 `/print-pack <PDF 路径>`，或直接说“帮我把这个 PDF 省纸打印”。

## 命令行直接用（不装插件也行）

```bash
pip install pymupdf

# 一键（自动判断：横排课件 3 合 1、竖排文档 2 合 1）
python plugins/pdf-print-pack/skills/pdf-print-pack/scripts/pack.py 课件.pdf

# 6 合 1 + 灰度省墨 + 补偶面
python plugins/pdf-print-pack/skills/pdf-print-pack/scripts/pack.py 课件.pdf --nup 6 --gray --pad-duplex

# 多文件按章合并（按文件名自然排序）
python plugins/pdf-print-pack/skills/pdf-print-pack/scripts/pack.py 第*.pdf -o 课程_省纸打印版.pdf

# 小册子（对折 A5、骑马钉）
python plugins/pdf-print-pack/skills/pdf-print-pack/scripts/pack.py 讲义.pdf --booklet
```

输出默认 `<输入名>_省纸打印版.pdf`，不改动输入文件；同名输出若不是本工具生成会拒绝覆盖（`--force` 才覆盖）。
完整参数见 `plugins/pdf-print-pack/skills/pdf-print-pack/SKILL.md`。

## 开发与测试

```bash
python plugins/pdf-print-pack/tests/test_pack.py        # 13 项引擎回归测试
python plugins/pdf-print-pack/tests/test_html2pdf.py    # HTML→PDF 冒烟测试（无浏览器自动跳过）
```

## 依赖

- Python 3.9+ 与 `pymupdf`（拼版引擎）
- Microsoft Edge 或 Google Chrome（仅“讲义重排”路径需要；Windows 自带 Edge）

## 许可

[MIT](LICENSE)
