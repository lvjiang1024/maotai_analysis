"""从 A 股上市公司年报 PDF 中提取现金流质量指标（通用版）。

用法：
    python3 extract_cashflow.py <年报目录> [--company 公司名] [--out 输出.json]
    python3 extract_cashflow.py ./财报 --company 贵州茅台
    python3 extract_cashflow.py ./财报 --years 2020 2021 2022   # 只跑指定年份

自动识别目录下文件名含 4 位年份且含「年报/财报/年度报告」的 PDF，逐份提取：
    营业收入、归母净利润、经营活动现金流量净额、销售商品提供劳务收到的现金、
    资本开支、现金分红、期末现金余额、有息负债
并派生收现比（销售收现 ÷ 营业收入）与净现比（经营现金流 ÷ 归母净利润）。

────────────────────────────────────────────────────────────────
跨年度报表格式差异——以下都是在 25 年茅台年报上踩过并修正的坑，
换一家公司大概率同样会遇到，改动提取逻辑前请先读：

1. 董事会报告正文也会出现「销售商品、提供劳务」等科目名，仅按关键词
   首次出现会抓到正文而非报表。正式报表恒在「财务报告」章节即文档后段，
   故先按位置排除前 SKIP_HEAD 比例，再取首个命中——合并报表总排在母公司报表之前。

2. 2007 年前老式资产负债表列序可能是「年初数 期末数」，与新式「期末余额 年初余额」
   相反，直接取第一个数会拿到年初值。须按表头文字顺序判断。

3. 部分 PDF 的粗体标题被 pdfplumber 提取成字符重复（「合合合合并并并并」），
   匹配前需先做去重折叠。

4. 老式利润表「五、净利润」已扣少数股东损益即归母口径；新式利润表
   「四、净利润」含少数股东损益，须另取「归属于母公司所有者的净利润」。

5. 若公司并表集团财务公司（大型国企常见），大量资金会列示于
   「存放中央银行款项」而非「货币资金」，货币资金口径会出现失真断崖。
   故现金余额优先采用现金流量表「期末现金及现金等价物余额」；
   老式报表无该行时才回退到资产负债表货币资金期末数。
────────────────────────────────────────────────────────────────
"""
import argparse
import json
import re
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("缺少依赖，请先运行：pip3 install pdfplumber")

NUM = re.compile(r"-?[\d,]+\.\d{2}")
YEAR = re.compile(r"(19|20)\d{2}")
# 报表恒在财务报告章节（文档后段），用于排除董事会报告里的同名科目
SKIP_HEAD = 0.25


def clean(s):
    return re.sub(r"\s+", "", s or "")


def dedupe(s):
    """折叠粗体标题被提取成的重复字符：合合合合并并并并 -> 合并"""
    return re.sub(r"(.)\1{1,}", r"\1", s)


def first_num(cell):
    m = NUM.findall(cell or "")
    return float(m[0].replace(",", "")) if m else None


def all_nums(cell):
    return [float(x.replace(",", "")) for x in NUM.findall(cell or "")]


def discover(pdf_dir):
    """扫描目录，返回 {年份: 路径}。文件名需含 4 位年份及年报关键词。"""
    kws = ("年报", "财报", "年度报告")
    found = {}
    for p in sorted(Path(pdf_dir).glob("*.pdf")):
        name = p.name
        if not any(k in name for k in kws):
            continue
        # 排除季报/半年报，只要年报
        if any(k in name for k in ("半年", "一季", "三季", "季度", "Q1", "Q3")):
            continue
        m = YEAR.search(name)
        if m:
            found.setdefault(int(m.group()), p)
    return found


def page_rows(pdf, idx, n=1):
    rows = []
    for i in range(idx, min(idx + n, len(pdf.pages))):
        for tb in pdf.pages[i].extract_tables():
            rows.extend(tb)
    return rows


def find_statement(pdf, needle, skip_head=SKIP_HEAD):
    """按页面文字定位合并报表首页（见文件头说明 1）。"""
    n = len(pdf.pages)
    for i in range(int(n * skip_head), n):
        t = clean(pdf.pages[i].extract_text() or "")
        if needle in t or needle in dedupe(t):
            return i
    return None


def _scan_rows(pdf, prefixes, hints, skip_head):
    for i in range(int(len(pdf.pages) * skip_head), len(pdf.pages)):
        if hints:
            t = clean(pdf.pages[i].extract_text() or "")
            if not any(h in t or h in dedupe(t) for h in hints):
                continue
        for tb in pdf.pages[i].extract_tables():
            for row in tb:
                if row and row[0] and any(clean(row[0]).startswith(p) for p in prefixes):
                    return i
    return None


def find_row_page(pdf, prefixes, hints, skip_head=SKIP_HEAD):
    """按表格行标签定位报表首页。

    比 find_statement 精确：「营业收入」在公司简介、分行业收入表里也会出现，
    只有匹配到真正的表格行标签（如「一、营业总收入」）才算命中。

    hints 是按页面文字做的粗筛，用于避免对每页都跑代价高昂的 extract_tables。
    但某些页的表格布局会让 extract_text 读不出连续的科目名（老式利润表常见），
    粗筛会假阴性，故粗筛落空时退化为全量扫描，宁可慢也不能漏。
    """
    return (_scan_rows(pdf, prefixes, hints, skip_head)
            or _scan_rows(pdf, prefixes, None, skip_head))


def lookup(rows, exact=None, prefix=None, pred=None, min_abs=1000, col_from=1):
    """取首个匹配行的首个数值。

    pred 用于标签写法不固定的科目——如归母净利润在不同年份可能是
    「归属于母公司所有者的净利润」「1.归属于母公司股东的净利润（净亏损以"-"号填列）」，
    带序号前缀和括号后缀，精确匹配和前缀匹配都对不上。
    """
    for row in rows:
        if not row or not row[0]:
            continue
        c0 = clean(row[0])
        hit = ((exact and c0 in exact)
               or (prefix and any(c0.startswith(p) for p in prefix))
               or (pred and pred(c0)))
        if hit:
            for cell in row[col_from:]:
                v = first_num(cell)
                if v is not None and abs(v) >= min_abs:
                    return v
    return None


def period_end_first(pdf, idx):
    """判断报表数值列是「期末在前」还是「年初在前」（见文件头说明 2）。"""
    t = dedupe(clean(pdf.pages[idx].extract_text() or ""))
    end = min([p for p in (t.find("期末数"), t.find("期末余额")) if p != -1] or [10 ** 9])
    beg = min([p for p in (t.find("年初数"), t.find("期初数"), t.find("年初余额")) if p != -1] or [10 ** 9])
    return end <= beg


def lookup_cash(rows, end_first):
    for row in rows:
        if not row or not row[0] or clean(row[0]) != "货币资金":
            continue
        vals = []
        for cell in row[1:]:
            vals.extend([v for v in all_nums(cell) if abs(v) >= 1000])
        if vals:
            return vals[0] if end_first else (vals[1] if len(vals) > 1 else vals[0])
    return None


def extract(path, year):
    out = {"年份": year}
    with pdfplumber.open(path) as pdf:
        # ── 合并现金流量表 ──
        cf = find_statement(pdf, "销售商品、提供劳务")
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

        # ── 合并资产负债表 ──
        bs = find_statement(pdf, "货币资金")
        if bs is not None:
            rows2 = page_rows(pdf, bs, n=2)
            out["货币资金"] = lookup_cash(rows2, period_end_first(pdf, bs))
            debt = 0.0
            wide = page_rows(pdf, bs, n=4)
            for label in ("短期借款", "长期借款", "应付债券", "一年内到期的非流动负债"):
                v = lookup(wide, exact={label})
                if v:
                    debt += v
            out["有息负债"] = debt

        # ── 合并利润表 ──
        rev_prefixes = ["一、营业总收入", "一、营业收入", "一、主营业务收入"]
        is_ = find_row_page(pdf, rev_prefixes,
                            hints=("营业总收入", "营业收入", "主营业务收入"))
        if is_ is not None:
            rows3 = page_rows(pdf, is_, n=4)
            # 含财务/金融子公司的集团，利润表为「一、营业总收入」下挂「其中：营业收入」，
            # 总收入含利息及手续费收入。销售收现对应的是营业收入，故优先取后者。
            out["营业收入"] = (lookup(rows3, prefix=["其中：营业收入"])
                           or lookup(rows3, prefix=rev_prefixes))
            # 新式利润表「四/五、净利润」含少数股东损益，须取归母行（见文件头说明 4）；
            # 排除「归属于母公司所有者的综合收益总额」
            out["归母净利润"] = lookup(rows3, pred=lambda c: (
                "归属于母公司" in c and "净利润" in c and "综合收益" not in c
            )) or lookup(rows3, prefix=["五、净利润", "四、净利润"])
    return out


def yi(v):
    return None if v is None else round(v / 1e8, 2)


def fmt(v, w=9):
    """亿元展示；缺失显示 —，避免 None 破坏对齐"""
    return ("—" if v is None else f"{v / 1e8:,.2f}").rjust(w)


def main():
    ap = argparse.ArgumentParser(description="提取 A 股年报现金流质量指标")
    ap.add_argument("pdf_dir", help="年报 PDF 所在目录")
    ap.add_argument("--company", default="", help="公司名，用于输出文件名")
    ap.add_argument("--years", nargs="*", type=int, help="只提取指定年份")
    ap.add_argument("--out", default="", help="输出 JSON 路径")
    a = ap.parse_args()

    found = discover(a.pdf_dir)
    if not found:
        sys.exit(f"在 {a.pdf_dir} 未找到年报 PDF（文件名需含 4 位年份及「年报/财报/年度报告」）")
    years = sorted(y for y in found if not a.years or y in a.years)
    print(f"找到 {len(years)} 份年报：{years[0]}—{years[-1]}\n")

    res = []
    for y in years:
        r = extract(found[y], y)
        rev, prof = r.get("营业收入"), r.get("归母净利润")
        sc, ocf = r.get("销售收现"), r.get("经营现金流")
        # 现金余额优先现金流量表口径（见文件头说明 5）
        r["现金余额"] = r.get("期末现金") or r.get("货币资金")
        r["收现比%"] = round(sc / rev * 100, 1) if sc and rev else None
        r["净现比%"] = round(ocf / prof * 100, 1) if ocf and prof else None
        res.append(r)
        ratio = f"{r['收现比%']}%" if r["收现比%"] is not None else "—"
        print(f"{y}  营收{fmt(rev)}  归母{fmt(prof, 8)}  经营现金流{fmt(ocf, 8)}  "
              f"销售收现{fmt(sc)}  收现比 {ratio}")

    miss = {k: [r["年份"] for r in res if r.get(k) is None]
            for k in ("营业收入", "归母净利润", "经营现金流", "销售收现", "现金余额")}
    miss = {k: v for k, v in miss.items() if v}
    if miss:
        print("\n⚠️  缺失项（需人工核对该年年报）：")
        for k, v in miss.items():
            print(f"   {k}: {v}")
    else:
        print("\n✅ 全部指标提取完整")

    name = a.company or Path(a.pdf_dir).resolve().parent.name
    out = Path(a.out) if a.out else Path(f"{name}_现金流数据.json")
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已写入 {out}（{len(res)} 个年度）")


if __name__ == "__main__":
    main()
