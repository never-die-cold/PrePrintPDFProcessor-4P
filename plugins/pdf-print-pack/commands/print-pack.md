---
description: 一键把 PDF 排成省纸打印版（N 合 1 拼版、灰度省墨、双面补页、瘦身压缩），或把课件重排成 2 合 1 浓缩讲义。
argument-hint: "[PDF 文件或目录…] [--nup 2|3|4|6|8] [--gray] [--booklet] 等"
skills: pdf-print-pack
---

使用 `pdf-print-pack` 技能处理这次请求：

$ARGUMENTS

先载入 `pdf-print-pack` 技能并从技能加载信息里拿到技能目录（Base directory，必要时也可用 `${ZCODE_SKILL_DIR}`），然后默认执行“一键拼版”路径，不要先反问用户：

```bash
python "<技能目录>/scripts/pack.py" <用户指定的 PDF…>
```

- 用户没给选项时就用 `auto` 默认值（自动选 2/3 合 1、自动裁白边、自动页标与页脚、自动瘦身），按需要可加 `--gray --pad-duplex`。
- 多个文件按自然排序合并，输出 `-o <课程名>_省纸打印版.pdf` 放在源文件目录。
- 跑完把报告转述给用户：原样单面 N 张 → 省纸版双面 M 张、体积变化、打印设置建议（100% 比例、双面长边翻页）。
- 只有当用户明确说“整理成讲义 / 浓缩 / 速查 / 重排”时，才走技能里的路径 B/C（HTML 重排 + `html2pdf.py`），并遵守其中的目视验收要求。
