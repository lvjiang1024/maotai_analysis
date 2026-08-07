# 上市公司财务分析工具（通用版）

## 新项目启动步骤

将以下 3 个文件拷贝到新项目目录即可使用：

```
新项目目录/
├── config.json                # 修改公司名称
├── CLAUDE.md                  # 本文件
├── financial_analysis.py      # 核心分析脚本
├── generate_html_report.py    # HTML报告生成器
└── (放入PDF年报文件)
```

## 第一步：修改 config.json

```json
{
  "company_name": "公司全称（如：贵州茅台）",
  "company_short": "公司简称（如：茅台）"
}
```

## 第二步：放入 PDF 年报

将上市公司 PDF 年报/半年报放入目录。文件名需包含"财报""年报""半年报""半年度报告"等关键词，年份需在文件名中可识别。

支持的文件名示例：
- `2024年财报.pdf`
- `2025年半年报.pdf`
- `XX公司：2025年半年度报告.pdf`

## 第三步：运行

```bash
pip3 install pandas matplotlib seaborn pdfplumber xlsxwriter openpyxl
python3 financial_analysis.py
```

## 自动执行的 7 个步骤

1. 扫描目录中所有 PDF 财报文件
2. 从 PDF 表格中提取 6 个核心指标（营收、净利润、总资产、净资产、EPS、ROE）
3. 数据清洗 + 计算同比增长率
4. 生成 4 张图表（趋势图、增长率、相关性矩阵、ROE/EPS）
5. 生成 Markdown 格式摘要报告
6. 保存 Excel 数据文件（原始数据 + 增长率）
7. 生成专业 HTML 报告（图文并茂）

## 输出文件

| 文件 | 说明 |
|------|------|
| 财务分析报告.html | 精美 HTML 报告，浏览器打开 |
| 财务分析报告.md | Markdown 摘要报告 |
| 财务数据.xlsx | Excel 数据（原始数据 + 增长率两个 sheet） |
| charts/ | 4 张 PNG 图表（300dpi） |

## 可复用能力：现金流质量分析

`cashflow-quality/` 是一个独立技能，用于验证账面利润有没有真金白银支撑——
提取经营现金流、销售收现、资本开支、现金分红、现金余额、有息负债，
计算收现比与净现比，并生成 4 张图表。可用于任何 A 股公司：

```bash
python3 cashflow-quality/scripts/extract_cashflow.py <年报目录> --company <公司名>
```

`cashflow-quality/SKILL.md` 里整理了 9 个跨年度报表格式陷阱（列序颠倒、
营业总收入 ≠ 营业收入、财务公司并表导致的现金口径断层等），换公司做提取前建议先读。
执行 `cp -R cashflow-quality ~/.claude/skills/` 可装为个人技能，所有项目自动可用。

**改动提取脚本后务必跑回归自测**，这类错误往往不报错、只是悄悄取到相邻科目：

```bash
python3 cashflow-quality/tests/test_extraction.py          # 快速，约 30 秒
python3 cashflow-quality/tests/test_extraction.py --full   # 25 份年报全跑，约 3 分钟
```

## 数据提取说明

脚本从 PDF 财报第 5-9 页的表格中提取以下中国上市公司标准财务指标：
- **营业收入** — 匹配行首
- **归属于上市公司股东的净利润** — 匹配行首，排除"扣除非"
- **归属于上市公司股东的净资产** — 匹配行首
- **总资产** — 匹配行首
- **基本每股收益** — 匹配行中，排除"扣除非"
- **加权平均净资产收益率** — 匹配行中，值域 10-50%

以上指标名称为 A 股上市公司财报标准格式，适用于绝大多数中国上市公司。

## 字体配置

脚本自动检测系统中可用的中文字体：
- macOS：Heiti TC / STHeiti / PingFang HK
- Windows：SimHei / Microsoft YaHei
- Linux：Noto Sans CJK SC / WenQuanYi Micro Hei

若图表中文显示为方块，运行前删除 matplotlib 缓存：
```bash
rm -rf ~/.matplotlib/fontList*.cache
```

## 依赖

```bash
pip3 install pandas matplotlib seaborn pdfplumber xlsxwriter openpyxl
```