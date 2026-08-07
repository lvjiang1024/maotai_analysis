"""从年报 PDF 中提取现金流质量相关科目，供报告「现金流质量」页使用。

用法：python3 extract_cashflow.py            # 提取 2001—2025 全部年份
      python3 extract_cashflow.py 2013 2020  # 只提取指定年份
结果写入 贵州茅台_现金流数据.json。

跨 25 年的年报格式差异，以下几点是踩过的坑：
- 董事会报告里也会出现「销售商品、提供劳务」等字样（2015/2016/2018 尤其明显），
  只按关键词首次出现会抓到正文而非报表；正式报表恒在「财务报告」章节即文档后段，
  故先按位置排除前 25%，再取首个命中——合并报表总排在母公司报表之前
- 2001/2002 资产负债表列序为「年初数 期末数」，与后续年份相反，需按表头判断
- 部分年份粗体标题被 pdfplumber 提取成字符重复（「合合合合并并并并」），需去重后再匹配
- 2020 年起并表集团财务公司，大量资金列示于「存放中央银行款项」而非「货币资金」，
  故现金余额统一采用现金流量表「期末现金及现金等价物余额」；
  2001—2006 老格式无该行，回退到资产负债表货币资金期末数
"""
import json
import re
import sys
from pathlib import Path

import pdfplumber

BASE = Path(__file__).resolve().parent
PDF_DIR = BASE / "财报"
NUM = re.compile(r"-?[\d,]+\.\d{2}")


def clean(s):
    return re.sub(r"\s+", "", s or "")


def dedupe(s):
    return re.sub(r"(.)\1{1,}", r"\1", s)


def first_num(cell):
    m = NUM.findall(cell or "")
    return float(m[0].replace(",", "")) if m else None


def all_nums(cell):
    return [float(x.replace(",", "")) for x in NUM.findall(cell or "")]


def page_rows(pdf, idx, n=1):
    rows = []
    for i in range(idx, min(idx + n, len(pdf.pages))):
        for tb in pdf.pages[i].extract_tables():
            rows.extend(tb)
    return rows


def find_statement(pdf, needle, min_frac=0.25):
    """定位合并报表首页。

    只匹配 needle 不够——董事会报告里也会讨论这些科目（2015/2016/2018 即如此）。
    但正式报表恒位于「财务报告」章节，在文档后段；而董事会报告在前段。
    故先按位置排除前 min_frac 部分，再取首个命中——合并报表总排在母公司报表之前。
    """
    n = len(pdf.pages)
    lo = int(n * min_frac)
    for i in range(lo, n):
        t = clean(pdf.pages[i].extract_text() or "")
        if needle in t or needle in dedupe(t):
            return i
    return None


def lookup(rows, exact=None, prefix=None, min_abs=1000, col_from=1):
    for row in rows:
        if not row or not row[0]:
            continue
        c0 = clean(row[0])
        hit = (exact and c0 in exact) or (prefix and any(c0.startswith(p) for p in prefix))
        if hit:
            for cell in row[col_from:]:
                v = first_num(cell)
                if v is not None and abs(v) >= min_abs:
                    return v
    return None


def bs_period_end_first(pdf, bs_idx):
    """判断资产负债表数值列是「期末在前」还是「年初在前」"""
    t = clean(pdf.pages[bs_idx].extract_text() or "")
    t = dedupe(t)
    pos_end = min([p for p in [t.find("期末数"), t.find("期末余额")] if p != -1] or [10 ** 9])
    pos_beg = min([p for p in [t.find("年初数"), t.find("期初数"), t.find("年初余额")] if p != -1] or [10 ** 9])
    return pos_end <= pos_beg


def lookup_cash(rows, period_end_first):
    """货币资金：按列序取期末数"""
    for row in rows:
        if not row or not row[0]:
            continue
        if clean(row[0]) != "货币资金":
            continue
        vals = []
        for cell in row[1:]:
            vals.extend([v for v in all_nums(cell) if abs(v) >= 1000])
        if not vals:
            continue
        return vals[0] if period_end_first else vals[1] if len(vals) > 1 else vals[0]
    return None


def extract(year):
    p = PDF_DIR / f"{year}年财报.pdf"
    if not p.exists():
        return None
    out = {"年份": year}
    with pdfplumber.open(p) as pdf:
        cf = find_statement(pdf, "销售商品、提供劳务")
        out["_cf_page"] = cf
        if cf is not None:
            rows = page_rows(pdf, cf, n=4)
            out["销售收现"] = lookup(rows, exact={"销售商品、提供劳务收到的现金"})
            out["经营现金流"] = lookup(rows, exact={"经营活动产生的现金流量净额"})
            out["资本开支"] = lookup(rows, exact={
                "购建固定资产、无形资产和其他长期资产支付的现金",
                "购建固定资产、无形资产和其他长期资产所支付的现金",
            })
            out["分红支出"] = lookup(rows, exact={
                "分配股利、利润或偿付利息支付的现金",
                "分配股利、利润或偿付利息所支付的现金",
            })
            out["期末现金"] = lookup(rows, prefix=["六、期末现金及现金等价物余额", "期末现金及现金等价物余额"])

        bs = find_statement(pdf, "货币资金")
        out["_bs_page"] = bs
        if bs is not None:
            rows = page_rows(pdf, bs, n=2)
            out["货币资金"] = lookup_cash(rows, bs_period_end_first(pdf, bs))
            debt = 0.0
            for label in ["短期借款", "长期借款", "应付债券", "一年内到期的非流动负债"]:
                v = lookup(page_rows(pdf, bs, n=4), exact={label})
                if v:
                    debt += v
            out["有息负债"] = debt
    return out


if __name__ == "__main__":
    years = [int(a) for a in sys.argv[1:]] or list(range(2001, 2026))
    res = []
    for y in years:
        r = extract(y)
        res.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    outp = BASE / "贵州茅台_现金流数据.json"
    outp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已写入 {outp.name}（{len(res)} 个年度）")
