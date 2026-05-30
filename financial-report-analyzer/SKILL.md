---
name: financial-report-analyzer
description: |
  从上市公司季度/年度财报PDF中提取关键财务数据与管理层观点，并生成交互式可视化HTML分析报告。
  适用场景：用户提供一家公司的多份季度财报PDF（中文简体/繁体或英文），需要提取收入、毛利、
  IFRS/非IFRS经营利润、归母净利润、自由现金流（FCF）、经营现金流（OCF）、资本开支等指标，
  并以多维图表方式呈现历史趋势；同时提炼管理层对业务、市场、展望和风险的核心判断，按时间轴展示。
  触发时机：用户说"分析财报"、"提取财务数据"、"做财务分析报告"、"可视化财报"、
  "读取PDF财报"、"整理季度数据"、"管理层怎么看"、"整理管理层观点"等，
  或者上传/指向一批财报PDF文件时，请主动使用此技能。
---

# 财报分析技能

## 概述

本技能将引导你完成以下四个阶段：
1. **扫描 & 识别**：检测财报 PDF 的语言、格式类型和所在目录
2. **财务数据提取**：用 Python（pdfplumber）从每份 PDF 抽取标准化财务指标
3. **管理层观点提取**：从管理层讨论段落提炼业务亮点、市场判断、展望目标、风险挑战
4. **可视化报告**：生成自包含的交互式 HTML 报告，包含多维图表、季度明细表和管理层观点时间轴

---

## 阶段一：扫描与识别

### 1.1 收集文件

首先确认 PDF 所在目录，列出所有文件：

```bash
ls -1 <财报目录>/*.pdf | sort
```

询问用户（如未告知）：
- 公司名称和股票代码
- 财报语言（中文简体/繁体/英文，或混合）
- 最早和最新的报告期间

### 1.2 格式分类

对每份 PDF，用 pdfplumber 读取前 3 页文字，判断格式类型：

| 类型 | 判断关键词 | 常见年份 |
|------|-----------|---------|
| **中文简体-利润表** | `营业收入`、`毛利`、`本公司权益持有人应占盈利` | 2019–2022 |
| **中文繁体-摘要表** | `財務表現摘要`、`毛利` | 2023Q1–Q2 |
| **英文-亮点表** | `FINANCIAL PERFORMANCE HIGHLIGHTS`、`Gross profit` | 2023Q3+ |
| **中文繁体-亮点表** | `財務表現摘要`（含英文数字列） | 部分季度 |

> 同一公司不同年份可能混用多种格式，需逐一判断。

---

## 阶段二：数据提取

### 2.1 安装依赖

```bash
pip install pdfplumber --break-system-packages
```

### 2.2 核心提取逻辑

使用 `references/extract_template.py` 作为起点（见下方参考文件说明）。  
关键指标及提取策略如下：

#### 收入 / 毛利 / 经营利润 / 净利润

**英文亮点表格（最常见于近年报告）**

```python
import pdfplumber, re

def extract_highlights(text):
    """从 FINANCIAL PERFORMANCE HIGHLIGHTS 表格提取数值（单位：百万元）"""
    # 定位表格起始位置
    for kw in ["FINANCIAL PERFORMANCE HIGHLIGHTS", "Financial Performance Highlights",
               "財務表現摘要", "财务表现摘要"]:
        p = text.find(kw)
        if p >= 0:
            hl_start = p
            break
    else:
        return {}

    # 截取季度部分（Q2 报告需在 H1/六个月 小节前截断）
    hl_end = hl_start + 3000
    for end_kw in ["Six months ended", "截至下列日期止六個月", "截至下列日期止六个月",
                   "截至十二月三十一日止年度"]:
        idx = text.find(end_kw, hl_start, hl_start + 3000)
        if idx >= 0:
            hl_end = min(hl_end, idx)
            break
    hl = text[hl_start:hl_end]

    results = {}

    # 收入
    for pat in [r"(?:Revenue|Revenues|总收入|收入)\s+([\d,]+)",
                r"(?:Total revenue)\s+([\d,]+)"]:
        m = re.search(pat, hl)
        if m:
            results["revenue"] = int(m.group(1).replace(",", ""))
            break

    # 毛利
    m = re.search(r"Gross profit\s+([\d,]+)", hl)
    if m:
        results["gross_profit"] = int(m.group(1).replace(",", ""))

    # IFRS 经营利润
    for pat in [r"Operating profit\s+([\d,]+)", r"經營盈利\s+([\d,]+)"]:
        m = re.search(pat, hl)
        if m:
            results["ifrs_op"] = int(m.group(1).replace(",", ""))
            break

    # Non-IFRS 经营利润
    for pat in [r"Non-IFRS operating profit\s+([\d,]+)",
                r"非國際財務報告準則經營盈利\s+([\d,]+)"]:
        m = re.search(pat, hl)
        if m:
            results["nifrs_op"] = int(m.group(1).replace(",", ""))
            break

    # IFRS 归母净利润（注意跨行标签）
    for pat in [
        r"Profit attributable to equity\s*\nholders of the Company\s+([\d,]+)",
        r"本公司[权權]益持有人[应應][占佔]盈利\s+([\d,]+)",
    ]:
        m = re.search(pat, hl)
        if m:
            results["ifrs_net"] = int(m.group(1).replace(",", ""))
            break

    # Non-IFRS 归母净利润（注意跨行标签）
    for pat in [
        r"Non-IFRS profit attributable to\s*\nequity holders of the Company\s+([\d,]+)",
        r"非國際財務報告準則本公司[权權]益持有人[应應][占佔]盈利\s+([\d,]+)",
    ]:
        m = re.search(pat, hl)
        if m:
            results["nifrs_net"] = int(m.group(1).replace(",", ""))
            break

    return results
```

**中文简体利润表（早期报告，如2019–2022）**

```python
def extract_income_statement(text):
    """从中文简体利润表提取，数值单位：百万元"""
    results = {}
    for pat in [r"(?:营业收入|收入)\s*[\|│]?\s*([\d,]+)"]:
        m = re.search(pat, text)
        if m:
            results["revenue"] = int(m.group(1).replace(",", ""))
    # 同理提取其他字段...
    return results
```

#### 自由现金流（FCF）——从正文叙述提取

FCF 通常出现在管理层讨论段落，而非表格，需用正则从文本中抓取：

```python
def extract_fcf(text):
    """提取自由现金流，单位：百万元"""
    # 优先匹配 "free cash flow of/for...was RMB X billion"
    patterns = [
        r"free cash flow (?:of|for[^.\n]*?was) RMB\s*([\d,.]+)\s*billion",
        r"[Ff]ree cash flow[^.\n]*?was RMB\s*([\d,.]+)\s*billion",
        r"自由現金流[量为為][^。\n]*?人民幣([\d,.]+)億",
    ]
    for pat in patterns:
        matches = list(re.finditer(pat, text, re.IGNORECASE))
        if matches:
            val_str = matches[-1].group(1).replace(",", "")
            return round(float(val_str) * 1000)  # 转换为百万元
    return None
```

#### 经营现金流（OCF）——注意累计值陷阱

⚠️ **重要**：Q2/H1 报告和 Q4/全年报告中的现金流数据通常是**累计值**，不是单季度值。
- Q1 报告 → 单季度值，可直接使用
- Q2/H1 报告 → 上半年累计，需标记为 `null`（无法拆分单季）
- Q3/前三季度报告 → 前三季度累计，需手动从文本段落提取单季度 OCF
- Q4/全年报告 → 全年累计，需标记为 `null`

从正文叙述提取单季度 OCF：

```python
def extract_ocf_from_text(text):
    """从叙述段落提取单季度经营现金流（亿元→百万元）"""
    patterns = [
        r"operating activities of RMB\s*([\d,.]+)\s*billion",
        r"經營活動產生的現金流量淨額[^。\n]*?人民幣([\d,.]+)億",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return round(float(m.group(1).replace(",", "")) * 1000)
    return None
```

#### 资本开支（Capex）——现金支出 vs GAAP 口径

注意两种口径的区别：
- **现金资本开支**：出现在 FCF 叙述段落中，如"资本开支付款人民币XX亿"
- **GAAP 资本开支**：出现在现金流量表附注中

优先使用**现金资本开支**（与 FCF 定义一致）：

```python
def extract_capex(text):
    patterns = [
        r"capital expenditure[s]? (?:of|was) RMB\s*([\d,.]+)\s*billion",
        r"資本開支付款人民幣([\d,.]+)億",
        r"capital expenditures of RMB\s*([\d,.]+)\s*billion",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return round(float(m.group(1).replace(",", "")) * 1000)
    return None
```

### 2.3 批量处理所有 PDF

```python
import os, json, pdfplumber

def process_all_pdfs(pdf_dir):
    results = []
    for fname in sorted(os.listdir(pdf_dir)):
        if not fname.endswith(".pdf"):
            continue
        quarter = infer_quarter_from_filename(fname)  # 从文件名推断季度
        fpath = os.path.join(pdf_dir, fname)
        with pdfplumber.open(fpath) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        
        row = {"quarter": quarter, "source": "P"}  # P = PDF直接提取
        row.update(extract_highlights(text) or extract_income_statement(text))
        row["fcf"]   = extract_fcf(text)
        row["capex"] = extract_capex(text)
        row["ocf"]   = extract_ocf_from_text(text)  # Q2/Q4 需后处理置 null
        results.append(row)
    
    return results

def infer_quarter_from_filename(fname):
    """从文件名推断季度，如 '2024Q1.pdf' → '2024Q1'"""
    m = re.search(r"(20\d{2})[Qq]?(\d)", fname)
    if m:
        return f"{m.group(1)}Q{m.group(2)}"
    return fname.replace(".pdf", "")
```

### 2.4 数据验证

提取完成后执行合理性检查：

```python
def validate(row):
    warnings = []
    r = row.get("revenue", 0)
    gp = row.get("gross_profit", 0)
    if gp and r and not (0.2 < gp/r < 0.9):
        warnings.append(f"{row['quarter']}: 毛利率异常 {gp/r:.1%}")
    op = row.get("nifrs_op", 0)
    if op and r and not (0.1 < op/r < 0.7):
        warnings.append(f"{row['quarter']}: Non-IFRS经营利润率异常 {op/r:.1%}")
    return warnings
```

---

## 阶段三：生成可视化 HTML 报告

### 3.1 报告结构

生成一个**单文件自包含的 HTML**，包含以下 Tab 页：

| Tab | 内容 |
|-----|------|
| 📈 总览 | 季度收入+利润趋势、同比增速、利润率走势 |
| 💼 收入与毛利 | 分业务收入堆叠图、收入+毛利折线、毛利率历史走势 |
| 💰 利润分析 | IFRS/Non-IFRS 经营利润+净利润，利润率趋势 |
| 🌊 自由现金流 | FCF 柱图、资本开支、FCF vs 净利润、OCF分解 |
| 📅 年度汇总 | 年度收入+利润、毛利率、收入增速 |
| 📋 季度明细表 | 所有指标的完整数据表格 |
| 💬 管理层观点 | 按季度时间轴展示管理层核心判断，支持维度筛选和关键词搜索 |

### 3.2 关键实现要点

**懒加载图表（解决隐藏 Tab 图表不显示的问题）**

```javascript
// 每个 Tab 的内容在第一次切换时才初始化（图表 + 管理层时间轴均适用）
const _chartsReady = {};
function show(sec) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));
  document.getElementById('sec-' + sec).classList.add('active');
  event.target.classList.add('active');
  if (!_chartsReady[sec]) {
    _chartsReady[sec] = true;
    const fns = { revenue: initRevenueCharts, profit: initProfitCharts,
                  fcf: initFcfCharts, annual: initAnnualCharts,
                  mgmt: initMgmtTimeline };  // 管理层时间轴也懒加载
    if (fns[sec]) fns[sec]();
  }
}
// 总览 Tab 在页面加载时直接初始化（它是默认可见的）
window.addEventListener('load', () => { buildTables(); initOverviewCharts(); });
```

**数据单位统一**
- 季度数据：百万元（Million RMB）
- 年度汇总数据：亿元（100 Million RMB）
- 图表 tooltip 显示时按需换算

**数据来源标注**
- 每行数据用 `source` 字段标记（`'P'` = PDF直接提取，`'E'` = 估算）
- 表格中对估算数据加 `<span class="tag est">估算</span>` 标签

### 3.3 HTML 模板结构

```html
<!-- 数据层（在 <script> 标签中） -->
<script>
// 季度数据：[季度, 收入, 毛利, IFRS经营利润, IFRS净利, NonIFRS经营利润, NonIFRS净利, FCF, OCF, Capex, 数据来源]
const Q = [
  ['2024Q1', 159501, 83870, 52556, 41889, 58619, 50265, 51900, 72350, 14359, 'P'],
  // ...
];

// 年度汇总数据
const annual = [
  {yr:'2024', rev:6603, gp:3492, nifrsOp:2378, nifrsNet:2227, ifrsNet:1941, gm:52.9},
  // ...
];
</script>

<!-- 图表层：使用 Chart.js（从 CDN 加载） -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
```

---

## 常见陷阱与处理方法

| 陷阱 | 原因 | 解决方案 |
|------|------|---------|
| 数据提取为空 | 关键词大小写不匹配 | 统一 `text.lower()` 匹配，或逐一列举大/小写变体 |
| Q2 报告取到 H1 数据 | 摘要表包含季度和半年两段 | 找到"六个月"/"Six months"的位置，截断提取范围 |
| OCF 是累计值 | Q2/Q4 报告现金流表是累计 | Q2、Q4 的 OCF 置 `null`；Q3 从正文叙述单独提取 |
| Capex 口径不一致 | 表格用 GAAP，正文用现金支出 | 优先正文叙述中的现金支出数字 |
| 跨行标签匹配失败 | 标签文字分两行显示 | 正则中加 `\s*\n` 匹配换行，如 `r"Profit attributable to equity\s*\nholders"` |
| 早年报告格式不同 | 2019–2021 年报为整合利润表格式 | 按报告年份分支处理，见格式分类表 |
| 年报重述历史数据 | 会计政策变更导致比较期数据调整 | 优先使用最新年报中的"比较期"列作为历史数据来源 |

---

---

## 阶段二补充：管理层观点提取与归类

这是报告中 **💬 管理层观点** Tab 的数据来源。目标是从每份季度财报的管理层讨论原文中，提炼管理层对公司的真实判断——他们如何评价自身业务，怎么看待市场，对未来持何种态度，以及承认了哪些风险。

### 四个维度的定义

| 维度 | 字段名 | 提炼什么 |
|------|--------|---------|
| **业务亮点与战略方向** | `highlights` | 本季度重要产品进展、增长亮点、新推出的战略举措、值得关注的数据里程碑 |
| **市场环境与竞争判断** | `market` | 管理层对行业趋势、监管政策、竞争格局的定性判断，对宏观环境的看法 |
| **展望与目标** | `outlook` | 对未来季度或中长期的预期、计划加大投入的方向、明确的增长驱动力 |
| **风险与挑战** | `risks` | 管理层主动提及或承认的不确定性、压力点、短期下行因素 |

**提炼原则：**
- 每个维度 3–5 条，每条 15–40 字
- 保留管理层的原始措辞和语气，不要转述为第三人称分析
- 只提炼管理层**主动表达**的判断，不要根据财务数据自行推断
- 如原文某维度内容极少，可少于 3 条，不要为凑数而编造
- 避免套话（如"我们将持续努力"），优先保留有具体信息量的表述

### 3.A 定位管理层讨论段落

管理层讨论段落通常以"业务回顾"、"Business Review"、"管理层讨论及分析"等关键词开头：

```python
START_KEYWORDS = [
    "业务回顾", "業務回顧", "管理层讨论", "管理層討論",
    "BUSINESS REVIEW", "Business Review",
    "战略进展", "戰略進展",
]
END_KEYWORDS = [
    "财务报表", "財務報表", "独立审阅报告", "獨立審閱報告",
    "合并损益", "綜合損益", "CONSOLIDATED",
]

def extract_mgmt_text(fpath, max_chars=8000):
    with pdfplumber.open(fpath) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    start = -1
    for kw in START_KEYWORDS:
        p = text.find(kw)
        if p >= 0 and (start < 0 or p < start):
            start = p
    if start < 0:
        start = 0  # 找不到则从头取
    window = text[start: start + 15000]
    end = len(window)
    for kw in END_KEYWORDS:
        p = window.find(kw, 500)
        if 0 < p < end:
            end = p
    return window[:end][:max_chars]
```

### 3.B AI 归类四个维度

将提取的管理层文本输入 Claude 进行结构化归类。**推荐直接在对话中批量处理**（每次 4–5 个季度），避免 CLI 工具依赖：

**提示词模板：**

```
以下是{公司名}{季度}财报管理层讨论原文。

请从四个维度提炼管理层的核心判断，每个维度3-5条，每条15-40字。
要求：保留管理层原始语气和措辞；只提炼管理层主动表达的判断，
不根据财务数字自行推断；如某维度原文内容少，可少于3条，不要编造。

维度说明：
- highlights（业务亮点与战略方向）：重要产品进展、增长亮点、战略举措、里程碑数据
- market（市场环境与竞争判断）：对行业趋势、监管政策、竞争格局、宏观环境的定性判断
- outlook（展望与目标）：对未来的预期、计划加大投入的方向、明确的增长驱动力
- risks（风险与挑战）：主动承认的不确定性、压力点、短期下行因素

输出严格JSON格式（不输出其他内容）：
{
  "highlights": ["...", "..."],
  "market":     ["...", "..."],
  "outlook":    ["...", "..."],
  "risks":      ["...", "..."]
}

原文：
{管理层讨论文本，约3000-6000字}
```

**质量检查要点：**
- `highlights` 里不应出现"我们将努力"这类无信息量表述
- `risks` 里应是管理层**承认**的风险，而非外部分析师的判断
- `outlook` 里如有明确数字或时间节点（如"2024年回购超1000亿港元"）要保留
- 如管理层在某维度表述很少（例如早年报告鲜少提风险），`risks` 可以只有1-2条

### 3.C 管理层时间轴 HTML 结构

管理层观点 Tab 使用以下结构，数据存为 `MGMT_DATA` JS 对象：

```javascript
// 数据格式
const MGMT_DATA = {
  "2024Q1": {
    highlights: ["AI驱动广告升级，向所有广告主推出生成式AI素材工具", ...],
    market:     ["小游戏流水同比增长30%，理财业务快速增长", ...],
    outlook:    ["持续投资AI技术、平台升级和高价值内容", ...],
    risks:      ["本土游戏收入因收入递延效应同比下降", ...]
  },
  // ...
};

// 初始化（懒加载）
function initMgmtTimeline() {
  // 渲染左侧年份导航 + 右侧季度卡片
  // 支持：维度筛选（highlights/market/outlook/risks）、关键词搜索、点击展开
}
```

**时间轴 UI 功能：**
- 左侧按年份分组的季度导航栏
- 顶部维度筛选按钮（全部 / 业务亮点 / 市场竞争 / 展望目标 / 风险挑战）
- 关键词搜索框（高亮匹配文本，自动展开匹配季度）
- 每季度卡片可折叠，两列布局展示四个维度

---

## 输出文件

生成以下文件保存到用户指定目录：

- `{公司名}_财务分析报告.html`：完整可视化报告（单文件，可直接双击打开），包含7个 Tab
- `{公司名}_quarterly_data.json`：提取的原始财务季度数据（便于后续复用）
- `{公司名}_mgmt_data.json`：管理层观点结构化数据（便于后续复用）

---

## 参考文件

- `references/extract_template.py`：完整的 Python 提取脚本模板（含所有格式处理分支）

---

## 快速上手示例

用户说："帮我分析一下微软的季度财报，PDF 文件在 ~/Downloads/MSFT/ 目录"

执行流程：
1. `ls ~/Downloads/MSFT/*.pdf` 列出文件
2. 读取 1-2 份 PDF 判断语言和格式
3. 运行财务提取脚本，结果存入 JSON
4. 检查异常值并修正（尤其 OCF 累计值和 Capex 口径）
5. 逐批读取每季度管理层讨论原文，在对话中归类为四维度 JSON
6. 将财务数据 + 管理层数据填充 HTML 模板（7 个 Tab）
7. 输出 `微软_财务分析报告.html` 并呈现给用户
