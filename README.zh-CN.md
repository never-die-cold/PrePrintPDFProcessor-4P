# PrePrintPDFProcessor-4P

**把任何 PDF 一键排成省纸、省墨、方便打印的版本。**

[![tests](https://github.com/never-die-cold/PrePrintPDFProcessor-4P/actions/workflows/tests.yml/badge.svg)](https://github.com/never-die-cold/PrePrintPDFProcessor-4P/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**English: [README.md](README.md)**

741 页的课件原样单面打印要 741 张纸；3 合 1 + 双面只占 **124 张（省 83%）**，文件还顺带瘦身 30%。

| 处理前 | 处理后 |
| --- | --- |
| ![单张幻灯片](docs/images/slides-3in1.png) | 一张 A4 排 3 张幻灯片，逐格页标 + 页脚：`--nup 3` |
| ![单张笔记](docs/images/notes-2in1.png) | 横向 A4 并排两页：`--nup 2`（默认自动判断） |

更多示例：[小册子折页](docs/images/booklet.png) · [扫描件清理前后](docs/images/scan-enhance.png) · [2 合 1 讲义主题](docs/images/handout-theme.png)

## 能做什么

| 能力 | 说明 |
| --- | --- |
| **N 合 1 拼版** | 每张纸 2/3/4/6/8/9/12/16 页；网格与纸张朝向按源页长宽比自动选（16:9 课件→纵向 3 合 1，竖版文档→横向 2 合 1） |
| **省纸细节** | 自动裁白边并放大内容、逐格页标（`L1-01…`）、页脚“第 i 张/共 N 张”、裁切线、`--pad-duplex` 补偶面、`--rotate-back` 适配短边翻页 |
| **省墨** | `--gray` 矢量级灰度（文字仍可搜索）；`--gray-raster` 光栅灰度；`--enhance` 去底灰+去噪；`--binarize` 纯黑白 |
| **装订** | `--booklet` 对折骑马钉；`--gutter 10 --mirror` 预留装订线并在背面镜像 |
| **导航保留** | 源书签映射到新张/格（可点击，直接跳到对应格）；页标签标注每张纸始于源文档第几页 |
| **扫描件清理** | `--deskew` 行投影法自动校倾斜（±5°）；合成 3° 倾斜样张实测估计出 −3.0°，行对齐分数提升 24 倍 |
| **瘦身** | 字体子集化 + 图片降采样，带**保真闸门**：只有低清像素差 ≤0.6/255 才采用重编码结果（曾拦下一次 `rewrite_images` 丢 Pattern 资源的坏结果） |
| **预演与预览** | `--dry-run` 只报省纸账不写文件；`--preview 2` 导出低清预览图，打印前先看一眼 |
| **讲义流水线** | 把课件重排成 2 合 1 浓缩讲义（HTML + 无头浏览器打印），`check_handout.py` 自动抓出被 `.bd` 裁掉的正文 |

## 快速开始

```bash
pip install pymupdf            # 必需；pillow+numpy 可解锁扫描件清理与去歪斜

# 一条命令：自动排版、裁白边、页标、瘦身
python plugins/pdf-print-pack/skills/pdf-print-pack/scripts/pack.py 课件.pdf

# 更多控制：6 合 1 + 灰度 + 补偶 + 装订线 + 成本折算 + 预览图
python plugins/pdf-print-pack/skills/pdf-print-pack/scripts/pack.py 课件.pdf \
    --nup 6 --gray --pad-duplex --gutter 8 --mirror --cost 0.1 --preview 2

# 多文件按章合并（自然排序：第2章 在 第10章 之前）
python plugins/pdf-print-pack/skills/pdf-print-pack/scripts/pack.py 第*.pdf -o 课程.pdf

# 扫描件：去底灰、去噪、校倾斜、二值化
python plugins/pdf-print-pack/skills/pdf-print-pack/scripts/pack.py 扫描.pdf --enhance --deskew
```

输出默认 `<输入名>_省纸打印版.pdf`；绝不修改输入文件，同名输出若不是本工具生成会拒绝覆盖（`--force` 才覆盖）。

```
省纸打印 · 拼版完成
  输入    11 个文件，共 741 页（按文件名自然排序）
  排版    A4 纵向 1×3 网格，双面后每张纸 6 页，输出 247 面
  省纸    原样单面 741 张 → 省纸版双面 124 张（省 83%；若原样也双面 371 张，省 67%）
  成本    按 0.1 元/张：原样单面 74.10 元 → 省纸版 12.40 元（省 61.70 元）
  导航    书签 60 条（点击跳到对应格）；页标签按该张首个源页号标注
  体积    99.93 MB → 71.41 MB（-29%），已做图片瘦身
```

## 在 ZCode 里用（插件）

1. **插件市场 → 添加 → 添加插件市场**，粘贴仓库里 `plugins/` 目录的绝对路径；
2. 在个人市场安装 **PDF 省纸打印**，在 **设置 → 插件** 里确认启用；
3. 新任务里输入 `/print-pack <PDF 路径>`，或直接说“把这份课件省纸打印”。

## Windows 右键一键

```powershell
powershell -ExecutionPolicy Bypass -File plugins/pdf-print-pack/tools/install-sendto.ps1
```

选中若干 PDF → 右键 → **发送到 → 省纸打印**，跑完停在窗口里显示省纸账。`-Remove` 卸载。

## 讲义模式（课件 → 2 合 1 浓缩讲义）

`SKILL.md` 里有完整流程：通读课件 → 改写成浓缩笔记 → 排版成横向 A4 每张两个逻辑页 → 无头浏览器打印 → 体检：

```bash
python plugins/pdf-print-pack/skills/pdf-print-pack/scripts/html2pdf.py 讲义.html -o 讲义.pdf
python plugins/pdf-print-pack/skills/pdf-print-pack/scripts/check_handout.py 讲义.html   # 退出码 1 = 有正文被裁
```

`check_handout.py` 把溢出内容染成品红再渲染检测，报“第 N 张、左半/右半溢出”，退出码可直接当流水线闸门。

## 目录结构

```text
plugins/
  marketplace.json                    # 本地开发市场目录
  pdf-print-pack/
    .zcode-plugin/plugin.json         # 插件清单
    commands/print-pack.md            # /print-pack 命令
    skills/pdf-print-pack/
      SKILL.md                        # 工作流：拼版 / 讲义 / 速查
      scripts/pack.py                 # 拼版引擎（核心）
      scripts/html2pdf.py             # Edge/Chrome 无头 HTML→PDF
      scripts/check_handout.py        # 讲义溢出体检
      assets/                         # 2 合 1 讲义主题与 HTML 骨架
    tools/install-sendto.ps1          # Windows 发送到安装脚本
    tests/                            # 8 个测试文件，无需网络
docs/make_images.py                   # 重新生成上面的示例图（只用合成样本）
```

## 测试与 CI

```bash
python plugins/pdf-print-pack/tests/test_pack.py         # 引擎回归 26 项
python plugins/pdf-print-pack/tests/test_invariants.py   # 随机参数不变量
python plugins/pdf-print-pack/tests/test_snapshot.py     # 结构快照（golden JSON）
python plugins/pdf-print-pack/tests/test_html2pdf.py     # 以及 _extra、test_check_handout.py
python plugins/pdf-print-pack/tests/test_sendto.py       # 仅 Windows，其它平台自动跳过
ruff check plugins/pdf-print-pack
```

CI 在 **Ubuntu + Windows × Python 3.9/3.12** 上跑全套；没有浏览器的环境会自动 SKIP 相关用例，
缺 Pillow/numpy 时增强类测试也会跳过而不是失败。

## 省纸算术

| 情形 | 用纸 |
| --- | --- |
| P 页，单面 | P 张 |
| P 页，双面 | ⌈P/2⌉ 张 |
| P 页，N 合 1 双面 | ⌈⌈P/N⌉/2⌉ 张 |

`--cost <每张单价>` 会按你的纸价把差额换算成金额，直接报“省了多少元”。

## 许可

[MIT](LICENSE)
