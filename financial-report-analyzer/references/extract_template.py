"""
财报 PDF 数据提取通用模板
基于腾讯2019-2026财报分析经验整理

用法：
  python extract_template.py --pdf-dir /path/to/pdfs --output data.json --company 腾讯

依赖：
  pip install pdfplumber --break-system-packages
"""

import os
import re
import json
import argparse
import pdfplumber


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def read_pdf_text(fpath):
    """读取 PDF 全文（合并所有页面）"""
    with pdfplumber.open(fpath) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def to_int(s):
    """将带逗号的数字字符串转为整数"""
    if s is None:
        return None
    return int(str(s).replace(",", "").replace(" ", ""))


def infer_quarter(fname):
    """
    从文件名推断季度标签，例如：
      '2024_Q1_results.pdf'  → '2024Q1'
      'FY2023_Annual.pdf'    → '2023Q4'（全年=Q4）
      '2023_interim.pdf'     → '2023Q2'（中期=H1=Q2）
    """
    m = re.search(r"(20\d{2})[_\-\s]?[Qq]?(\d)", fname)
    if m:
        return f"{m.group(1)}Q{m.group(2)}"
    # 尝试从年度报告推断
    m = re.search(r"(20\d{2})", fname)
    if m:
        lower = fname.lower()
        if any(k in lower for k in ["annual", "fy", "full", "full-year", "全年"]):
            return f"{m.group(1)}Q4"
        if any(k in lower for k in ["interim", "h1", "half", "中期", "半年"]):
            return f"{m.group(1)}Q2"
    return fname.replace(".pdf", "")


def detect_format(text):
    """
    检测财报格式类型：
      'en_highlights'  — 英文 FINANCIAL PERFORMANCE HIGHLIGHTS 表格
      'zh_tw_summary'  — 繁体中文 財務表現摘要
      'zh_cn_income'   — 简体中文利润表
      'unknown'
    """
    tl = text.lower()
    if "financial performance highlights" in tl or "financial highlights" in tl:
        return "en_highlights"
    if "財務表現摘要" in text or "财务表现摘要" in text:
        return "zh_tw_summary"
    if "营业收入" in text or "本公司权益持有人应占盈利" in text:
        return "zh_cn_income"
    return "unknown"


# ─── 英文/繁体亮点表格提取 ────────────────────────────────────────────────────

def extract_highlights(text):
    """
    从 FINANCIAL PERFORMANCE HIGHLIGHTS 或 財務表現摘要 表格提取数值。
    单位：百万元（Million RMB）。
    """
    # 1. 定位表格起始
    hl_start = -1
    for kw in [
        "FINANCIAL PERFORMANCE HIGHLIGHTS",
        "Financial Performance Highlights",
        "FINANCIAL HIGHLIGHTS",
        "Financial Highlights",
        "財務表現摘要",
        "财务表现摘要",
    ]:
        p = text.find(kw)
        if p >= 0:
            hl_start = p
            break
    if hl_start < 0:
        return {}

    # 2. 截取至 H1/全年段落前（防止 Q2 报告把半年数据当季度数据）
    hl_end = hl_start + 4000
    for end_kw in [
        "Six months ended", "截至下列日期止六個月", "截至下列日期止六个月",
        "截至十二月三十一日止年度", "Year ended",
    ]:
        idx = text.find(end_kw, hl_start, hl_start + 4000)
        if 0 < idx < hl_end:
            hl_end = idx
    hl = text[hl_start:hl_end]

    results = {}

    def first_int(patterns, src=hl):
        for pat in patterns:
            m = re.search(pat, src, re.IGNORECASE)
            if m:
                return to_int(m.group(1))
        return None

    # 收入
    results["revenue"] = first_int([
        r"(?:Revenue|Revenues|Total revenue|总收入|收入)\s+([\d,]+)",
    ])

    # 毛利
    results["gross_profit"] = first_int([
        r"Gross profit\s+([\d,]+)",
        r"毛利\s+([\d,]+)",
    ])

    # IFRS 经营利润
    results["ifrs_op"] = first_int([
        r"Operating profit\s+([\d,]+)",
        r"經營盈利\s+([\d,]+)",
        r"经营盈利\s+([\d,]+)",
    ])

    # Non-IFRS 经营利润
    results["nifrs_op"] = first_int([
        r"Non-IFRS operating profit\s+([\d,]+)",
        r"非國際財務報告準則經營盈利\s+([\d,]+)",
        r"非国际财务报告准则经营盈利\s+([\d,]+)",
    ])

    # IFRS 归母净利润（注意跨行标签）
    results["ifrs_net"] = first_int([
        r"Profit attributable to equity\s*\nholders of the Company\s+([\d,]+)",
        r"Profit attributable to equity holders of the Company\s+([\d,]+)",
        r"本公司[权權]益持有人[应應][占佔]盈利\s+([\d,]+)",
        r"本公司[权權]益持有人\s*\n[应應][占佔]盈利\s+([\d,]+)",
    ])

    # Non-IFRS 归母净利润（注意跨行标签）
    results["nifrs_net"] = first_int([
        r"Non-IFRS profit attributable to\s*\nequity holders of the Company\s+([\d,]+)",
        r"Non-IFRS profit attributable to equity holders of the Company\s+([\d,]+)",
        r"非國際財務報告準則本公司[权權]益持有人[应應][占佔]盈利\s+([\d,]+)",
    ])

    return {k: v for k, v in results.items() if v is not None}


# ─── 简体中文利润表提取（早期报告）────────────────────────────────────────────

def extract_income_statement(text):
    """
    从简体中文合并利润表提取，适用于2019-2022年报告。
    单位：百万元。
    """
    results = {}

    def search(patterns):
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return to_int(m.group(1))
        return None

    results["revenue"] = search([
        r"(?:营业收入|总收入|收入)\s*[\t ]+(\d[\d,]+)",
    ])
    results["gross_profit"] = search([
        r"毛利\s*[\t ]+(\d[\d,]+)",
    ])
    results["ifrs_op"] = search([
        r"经营盈利\s*[\t ]+(\d[\d,]+)",
        r"营业利润\s*[\t ]+(\d[\d,]+)",
    ])
    results["nifrs_op"] = search([
        r"非国际财务报告准则经营盈利\s*[\t ]+(\d[\d,]+)",
        r"非IFRS经营利润\s*[\t ]+(\d[\d,]+)",
    ])
    results["ifrs_net"] = search([
        r"本公司权益持有人应占盈利\s*[\t ]+(\d[\d,]+)",
        r"归属于母公司股东的净利润\s*[\t ]+(\d[\d,]+)",
    ])
    results["nifrs_net"] = search([
        r"非国际财务报告准则本公司权益持有人应占盈利\s*[\t ]+(\d[\d,]+)",
    ])

    return {k: v for k, v in results.items() if v is not None}


# ─── 现金流相关提取 ───────────────────────────────────────────────────────────

def extract_fcf(text):
    """
    从正文叙述段落提取自由现金流（亿元→百万元）。
    FCF 通常不在表格里，而是在管理层讨论中以文字形式披露。
    """
    patterns = [
        r"free cash flow (?:of|for[^.\n]*?was) RMB\s*([\d,.]+)\s*billion",
        r"[Ff]ree cash flow[^.\n]*?was RMB\s*([\d,.]+)\s*billion",
        r"自由[現现]金流[量为為][^。\n]*?人民幣([\d,.]+)億",
        r"自由现金流[^。\n]*?人民币([\d,.]+)亿",
    ]
    for pat in patterns:
        matches = list(re.finditer(pat, text, re.IGNORECASE))
        if matches:
            val = float(matches[-1].group(1).replace(",", ""))
            return round(val * 1000)  # 亿 → 百万
    return None


def extract_ocf_from_text(text):
    """
    从正文叙述提取单季度经营现金流（亿元→百万元）。

    ⚠️ 重要：Q2/Q4 报告中现金流量表的 OCF 是累计值，不能直接用。
    应从段落叙述中寻找明确的单季度数字。
    如果找不到，返回 None（调用方需根据报告期判断是否应置 null）。
    """
    patterns = [
        r"operating activities of RMB\s*([\d,.]+)\s*billion",
        r"net cash (?:generated from|from) operating activities[^.\n]*?RMB\s*([\d,.]+)\s*billion",
        r"經營活動[^。\n]*?人民幣([\d,.]+)億",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1).replace(",", ""))
            return round(val * 1000)
    return None


def extract_capex(text):
    """
    提取资本开支（现金口径，亿元→百万元）。
    优先从 FCF 叙述段落中提取现金支出，而非现金流量表附注（GAAP 口径）。
    """
    patterns = [
        r"capital expenditures? (?:of|was) RMB\s*([\d,.]+)\s*billion",
        r"資本開支付款人民幣([\d,.]+)億",
        r"capital expenditure payments of RMB\s*([\d,.]+)\s*billion",
        r"购买物业、厂房及设备[^。\n]*?人民幣([\d,.]+)億",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1).replace(",", ""))
            return round(val * 1000)
    return None


# ─── 主流程 ───────────────────────────────────────────────────────────────────

def process_pdf(fpath):
    """处理单个 PDF，返回提取结果字典"""
    fname = os.path.basename(fpath)
    quarter = infer_quarter(fname)
    text = read_pdf_text(fpath)
    fmt = detect_format(text)

    print(f"  {fname} → {quarter} [{fmt}]")

    # 根据格式选择提取函数
    if fmt in ("en_highlights", "zh_tw_summary"):
        data = extract_highlights(text)
    elif fmt == "zh_cn_income":
        data = extract_income_statement(text)
        hl = extract_highlights(text)  # 可能也有摘要表
        data.update({k: v for k, v in hl.items() if k not in data})
    else:
        # 未知格式：两种方法都试一遍
        data = extract_highlights(text)
        if not data:
            data = extract_income_statement(text)

    data["quarter"] = quarter
    data["source"] = "P"  # PDF直接提取

    # 现金流（这些方法对所有格式通用）
    data["fcf"] = extract_fcf(text)
    data["capex"] = extract_capex(text)
    data["ocf"] = extract_ocf_from_text(text)

    # ⚠️ 提示：Q2 和 Q4 的 OCF 通常是累计值，需人工确认后置 null
    q_num = quarter[-1] if quarter else ""
    if q_num in ("2", "4") and data.get("ocf"):
        print(f"    ⚠️  {quarter} OCF={data['ocf']} 可能是累计值，请核实后决定是否置 null")

    return data


def validate(rows):
    """数据合理性检查"""
    warnings = []
    for row in rows:
        q = row.get("quarter", "?")
        r = row.get("revenue") or 0
        gp = row.get("gross_profit") or 0
        op = row.get("nifrs_op") or 0
        if r > 0 and gp > 0 and not (0.15 < gp / r < 0.95):
            warnings.append(f"{q}: 毛利率异常 {gp/r:.1%} (gp={gp}, rev={r})")
        if r > 0 and op > 0 and not (0.05 < op / r < 0.75):
            warnings.append(f"{q}: Non-IFRS经营利润率异常 {op/r:.1%}")
    return warnings


def main():
    parser = argparse.ArgumentParser(description="财报PDF批量数据提取")
    parser.add_argument("--pdf-dir", required=True, help="PDF所在目录")
    parser.add_argument("--output", default="quarterly_data.json", help="输出JSON文件路径")
    parser.add_argument("--company", default="company", help="公司名称（用于输出文件命名）")
    args = parser.parse_args()

    pdf_files = sorted(
        os.path.join(args.pdf_dir, f)
        for f in os.listdir(args.pdf_dir)
        if f.lower().endswith(".pdf")
    )

    if not pdf_files:
        print(f"❌ 未找到 PDF 文件：{args.pdf_dir}")
        return

    print(f"📂 找到 {len(pdf_files)} 份 PDF，开始提取...\n")
    results = []
    for fpath in pdf_files:
        try:
            row = process_pdf(fpath)
            results.append(row)
        except Exception as e:
            print(f"  ❌ 处理失败 {os.path.basename(fpath)}: {e}")

    # 按季度排序
    results.sort(key=lambda r: r.get("quarter", ""))

    # 合理性检查
    warnings = validate(results)
    if warnings:
        print("\n⚠️  数据合理性警告：")
        for w in warnings:
            print(f"   {w}")

    # 输出
    out_path = args.output.replace("company", args.company)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 已保存 {len(results)} 条记录 → {out_path}")

    # 打印摘要表
    print("\n季度 | 收入 | 毛利率 | NonIFRS利润率 | FCF")
    print("-" * 60)
    for r in results:
        rev = r.get("revenue") or 0
        gp  = r.get("gross_profit") or 0
        op  = r.get("nifrs_op") or 0
        fcf = r.get("fcf")
        gm_str  = f"{gp/rev:.1%}" if rev > 0 and gp > 0 else "?"
        op_str  = f"{op/rev:.1%}" if rev > 0 and op > 0 else "?"
        fcf_str = f"{fcf/100:.0f}亿" if fcf else "?"
        print(f"{r.get('quarter','?'):8} | {rev:>8,} | {gm_str:>6} | {op_str:>13} | {fcf_str}")


if __name__ == "__main__":
    main()
