"""从 A 股上市公司定期报告 PDF 中提取现金流质量指标（年报／半年报／季报）。

用法：
    python3 extract_cashflow.py <报告目录> [--company 公司名] [--periods ...] [--out 输出.json]
    python3 extract_cashflow.py ./财报 --company 贵州茅台                  # 默认只跑年报
    python3 extract_cashflow.py ./财报 --periods 全部                      # 年报+半年报+季报
    python3 extract_cashflow.py ./财报 --periods 半年报 --years 2025 2026

自动识别目录下文件名含 4 位年份及报告期关键词的 PDF，逐份提取：
    营业收入、归母净利润、经营活动现金流量净额、销售商品提供劳务收到的现金、
    资本开支、现金分红、期末现金余额、有息负债
并派生收现比（销售收现 ÷ 营业收入）与净现比（经营现金流 ÷ 归母净利润）。

半年报/季报的利润表与现金流量表取「年初至报告期末」累计数，与年报同口径可串成
累计曲线（Q1 ≤ H1 ≤ Q3 ≤ 全年）；但累计数不可与年报画在同一条线上当作同一序列。

────────────────────────────────────────────────────────────────
报表格式差异——以下都是在茅台 25 年年报及历年季报/半年报上踩过并修正的坑，
换一家公司大概率同样会遇到，改动提取逻辑前请先读：

1. 董事会报告正文也会出现「销售商品、提供劳务」等科目名，仅按关键词
   首次出现会抓到正文而非报表。故优先按「合并xxx表」标题定位，
   老式报告无该标题时才回退按 SKIP_HEAD 比例跳过文档前段。

2. 标题也出现在财务报表目录、审计报告、附注里（审计报告会写「审计了……
   资产负债表及合并资产负债表」）。故每个候选页都要做锚点行校验，
   且列序判断必须落在真正含该科目行的那一页上，否则会取到年初数。

3. 2007 年前老式资产负债表列序可能是「年初数 期末数」，与新式「期末余额 年初余额」
   相反，直接取第一个数会拿到年初值。须按表头文字顺序判断。

4. 部分 PDF 的粗体标题被 pdfplumber 提取成字符重复（「合合合合并并并并」），
   匹配前需先做去重折叠。

5. 老式利润表「五、净利润」已扣少数股东损益即归母口径；新式利润表
   「四、净利润」含少数股东损益，须另取「归属于母公司所有者的净利润」。

6. 若公司并表集团财务公司（大型国企常见），大量资金会列示于
   「存放中央银行款项」而非「货币资金」，货币资金口径会出现失真断崖。
   故现金余额优先采用现金流量表「期末现金及现金等价物余额」；
   老式报表无该行时才回退到资产负债表货币资金期末数。

7. 合并报表尾部常与「母公司xxx表」标题同页，读取上界须取母公司标题页 +1，
   否则会丢掉合并报表最后几行。同页内合并行在前，取首个匹配仍是合并值。

8. 2021 年准则修订前的季报利润表有四列（本期单季 | 上期单季 | 年初至报告期末 |
   上年同期），取第一个数会得到单季度值而非累计值，与年报口径不可比。
   须解析表头定位累计列序号，见 cumulative_index。
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


# 报告期 -> (匹配文件名的关键词, 覆盖月份跨度, 排序权重)
PERIODS = {
    "一季报": (("第一季度", "一季报", "一季度", "Q1"), "1-3月", 1),
    "半年报": (("半年报", "半年度", "中期报告", "H1"), "1-6月", 2),
    "三季报": (("第三季度", "三季报", "三季度", "Q3"), "1-9月", 3),
    "年报": (("年报", "财报", "年度报告"), "1-12月", 4),
}


def period_of(name):
    """由文件名判定报告期。年报最后判，避免「2025年第一季度财报」被误判为年报。"""
    for period in ("一季报", "半年报", "三季报", "年报"):
        if any(k in name for k in PERIODS[period][0]):
            return period
    return None


def discover(pdf_dir, periods=("年报",)):
    """扫描目录，返回 {(年份, 报告期): 路径}。

    默认只要年报，与历史行为一致；传 periods 可纳入季报/半年报。
    """
    found = {}
    for p in sorted(Path(pdf_dir).glob("*.pdf")):
        period = period_of(p.name)
        if period is None or period not in periods:
            continue
        m = YEAR.search(p.name)
        if m:
            found.setdefault((int(m.group()), period), p)
    return found


def page_rows(pdf, idx, n=1):
    rows = []
    for i in range(idx, min(idx + n, len(pdf.pages))):
        for tb in pdf.pages[i].extract_tables():
            rows.extend(tb)
    return rows


MERGED_TITLE = {"bs": "合并资产负债表", "is": "合并利润表", "cf": "合并现金流量表"}
PARENT_TITLE = {"bs": "母公司资产负债表", "is": "母公司利润表", "cf": "母公司现金流量表"}


def _cache(pdf):
    """挂在 pdf 对象上的缓存。标题扫描与表格解析代价高，且同一份 PDF 内会被反复调用。"""
    if not hasattr(pdf, "_cfq_cache"):
        pdf._cfq_cache = {}
    return pdf._cfq_cache


def title_pages(pdf, title):
    """标题出现的全部页码。标题多为粗体，需先做重复字符折叠。

    返回全部而非首个：目录、审计报告、附注里都可能出现同名文字，
    首个命中往往不是真正的报表页，须由调用方逐个校验。
    """
    c = _cache(pdf)
    key = ("title", title)
    if key not in c:
        c[key] = [i for i, page in enumerate(pdf.pages)
                  if title in dedupe(clean(page.extract_text() or ""))]
    return c[key]


def merged_start(pdf, kind):
    """「合并xxx表」标题首见页；老式报告无此标题时返回 None。"""
    hits = title_pages(pdf, MERGED_TITLE[kind])
    return hits[0] if hits else None


def parent_start(pdf, kind):
    """母公司报表起始页，用作合并报表的读取上界。

    同样要做锚点行校验：「母公司利润表」等字样也出现在附注里
    （茅台 2019 年报第 48 页附注即提到该表名），若把附注页当成母公司报表起点，
    上界会被压到合并报表中间，合并数据被提前截断。
    真正的母公司报表首页（或其次页）必含该报表的特征科目行。
    """
    c = _cache(pdf)
    key = ("parent", kind)
    if key in c:
        return c[key]
    found = None
    for p in title_pages(pdf, PARENT_TITLE[kind]):
        for i in (p, p + 1):
            if i < len(pdf.pages) and _has_anchor(page_rows(pdf, i), kind):
                found = p
                break
        if found is not None:
            break
    c[key] = found
    return found


def find_statement(pdf, needle, skip_head=SKIP_HEAD):
    """按页面文字定位合并报表首页（见文件头说明 1）。"""
    n = len(pdf.pages)
    for i in range(int(n * skip_head), n):
        t = clean(pdf.pages[i].extract_text() or "")
        if needle in t or needle in dedupe(t):
            return i
    return None


ANCHORS = {
    "bs": ("货币资金",),
    "is": ("一、营业总收入", "一、营业收入", "一、主营业务收入", "其中：营业收入"),
    "cf": ("销售商品、提供劳务收到的现金", "经营活动产生的现金流量净额"),
}


def _has_anchor(rows, kind):
    for row in rows:
        if row and row[0]:
            c = clean(row[0])
            if any(c.startswith(p) for p in ANCHORS[kind]):
                return True
    return False


def _read_window(pdf, start, span, kind):
    """读取 [start, start+span) 的表格行，以母公司报表起始页为上界。

    上界含母公司标题所在页（par+1）：合并报表的尾部常与母公司报表的开头同页，
    若把该页整页排除，会丢掉合并报表最后几行——2013 的归母净利润、
    2015 的期末现金及现金等价物余额正好落在这一页。
    同页内合并行排在母公司行之前，lookup 取首个匹配，仍拿到合并数据。
    """
    stop = start + span
    par = parent_start(pdf, kind)
    if par is not None and par > start:
        stop = min(stop, par + 1)
    rows = []
    for i in range(start, min(stop, len(pdf.pages))):
        for tb in pdf.pages[i].extract_tables():
            rows.extend(tb)
    return rows


def _anchor_page(pdf, start, stop, kind):
    """窗口内真正含该报表特征科目行的那一页。"""
    for i in range(start, stop):
        for tb in pdf.pages[i].extract_tables():
            if _has_anchor(tb, kind):
                return i
    return None


def statement_rows_at(pdf, kind, fallback_page, span=4):
    """同 statement_rows，但一并返回「锚点行所在页」。

    返回的不是窗口起始页而是锚点页——列序判断（期末在前 / 年初在前）
    必须落在真正含该科目行的那一页上。窗口起始页可能是审计报告：
    审计报告正文会写「审计了……资产负债表及合并资产负债表」，
    标题匹配会命中这句散文；该页没有「年初数/期末数」字样，
    据其判断列序会误判为期末在前，从而取到年初数
    （茅台 2001 货币资金因此取成 4.61 亿，实为 19.56 亿）。
    """
    cands = title_pages(pdf, MERGED_TITLE[kind])
    if fallback_page is not None:
        cands.append(fallback_page)
    for start in cands:
        stop = min(start + span, len(pdf.pages))
        par = parent_start(pdf, kind)
        if par is not None and par > start:
            stop = min(stop, par + 1)
        rows = _read_window(pdf, start, span, kind)
        if _has_anchor(rows, kind):
            return rows, (_anchor_page(pdf, start, stop, kind) or start)
    return [], None


def statement_rows(pdf, kind, fallback_page, span=4):
    """取某张合并报表的表格行。

    先按「合并xxx表」标题定位，再回退到既有的位置启发式；
    每个候选都必须通过锚点行校验（窗口内确实含该报表的特征科目）才采纳。

    校验不可省：目录、审计报告、附注里都会出现「合并资产负债表」等字样，
    直接取标题首见页会落在目录上，读出一片空白而非报表。

    标题定位解决的是按比例跳过跳不准的问题——SKIP_HEAD 按年报校准（报表在
    文档后半段），而半年报/季报报表位置靠前得多：2026 半年报的合并资产负债表
    在第 24 页 / 共 110 页 ≈ 22%，跳过前 25% 恰好落进合并报表内部，
    首个「货币资金」命中的是紧随其后的母公司报表，整段数据取错。
    """
    cands = title_pages(pdf, MERGED_TITLE[kind])
    if fallback_page is not None:
        cands.append(fallback_page)
    for start in cands:
        rows = _read_window(pdf, start, span, kind)
        if _has_anchor(rows, kind):
            return rows
    return []


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


CUM_HINTS = ("年初至报告期", "年初至本报告期", "前三季度", "1-9月", "1－9月",
             "1-6月", "1－6月", "1-3月", "1－3月", "年初至季度末")
QUARTER_HINTS = ("本期金额", "本报告期", "第三季度（7", "第三季度(7", "7-9月", "7－9月",
                 "4-6月", "4－6月")


def cumulative_index(rows):
    """季报利润表的累计列序号（在数值列中从 0 起算）；无需换列时返回 0。

    这是季报最危险的坑：2021 年报表准则修订前，季报利润表有四列——
      本期金额(7-9月) | 上期金额(7-9月) | 年初至报告期末(1-9月) | 上年同期(1-9月)
    取第一个数会得到「单季度」而非「年初至今累计」，与年报/半年报口径不可比。
    茅台 2020 三季报营业总收入单季 239.41 亿、累计 695.75 亿，差近 3 倍。
    2021 年后的季报只剩累计两列，此时返回 0 即可。
    """
    for row in rows:
        if not row or not row[0] or clean(row[0]) not in ("项目", "报表项目"):
            continue
        heads = [clean(c) for c in row[1:] if c and c.strip()]
        if len(heads) < 3:
            return 0                      # 只有本期/上期两列，本身就是累计口径
        for idx, h in enumerate(heads):
            if any(k in h for k in CUM_HINTS) and not any(k in h for k in QUARTER_HINTS):
                return idx
        return 0
    return 0


def lookup(rows, exact=None, prefix=None, pred=None, min_abs=1000, col_from=1, col_index=0):
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
            vals = []
            for cell in row[col_from:]:
                vals += [v for v in all_nums(cell) if abs(v) >= min_abs]
            if vals:
                # col_index>0 用于季报利润表取「年初至报告期末」累计列；
                # 列数不足时回退首列，宁可给出可核对的数也不静默返回空。
                return vals[col_index] if col_index < len(vals) else vals[0]
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


def extract(path, year, period="年报"):
    out = {"年份": year, "报告期": period, "期间": PERIODS.get(period, (None, "", 0))[1]}
    with pdfplumber.open(path) as pdf:
        # ── 合并现金流量表 ──
        # 各期现金流量表恒为「年初至报告期末」累计口径，取首列即可
        cf = find_statement(pdf, "销售商品、提供劳务")
        rows = statement_rows(pdf, "cf", cf, span=4)
        if rows:
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
        bs_fb = find_statement(pdf, "货币资金")
        rows2, bs_start = statement_rows_at(pdf, "bs", bs_fb, span=2)
        if rows2:
            # 列序须按实际读取的那一页判断（见 statement_rows_at）
            out["货币资金"] = lookup_cash(rows2, period_end_first(pdf, bs_start))
            debt = 0.0
            wide = statement_rows(pdf, "bs", bs_fb, span=4)
            for label in ("短期借款", "长期借款", "应付债券", "一年内到期的非流动负债"):
                v = lookup(wide, exact={label})
                if v:
                    debt += v
            out["有息负债"] = debt

        # ── 合并利润表 ──
        rev_prefixes = ["一、营业总收入", "一、营业收入", "一、主营业务收入"]
        is_fb = find_row_page(pdf, rev_prefixes,
                              hints=("营业总收入", "营业收入", "主营业务收入"))
        rows3 = statement_rows(pdf, "is", is_fb, span=4)
        if rows3:
            ci = cumulative_index(rows3)   # 季报须避开「单季度」列（见 cumulative_index）
            out["累计列序号"] = ci
            # 含财务/金融子公司的集团，利润表为「一、营业总收入」下挂「其中：营业收入」，
            # 总收入含利息及手续费收入。销售收现对应的是营业收入，故优先取后者。
            out["营业收入"] = (lookup(rows3, prefix=["其中：营业收入"], col_index=ci)
                           or lookup(rows3, prefix=rev_prefixes, col_index=ci))
            # 新式利润表「四/五、净利润」含少数股东损益，须取归母行（见文件头说明 4）；
            # 排除「归属于母公司所有者的综合收益总额」
            out["归母净利润"] = lookup(rows3, col_index=ci, pred=lambda c: (
                "归属于母公司" in c and "净利润" in c and "综合收益" not in c
            )) or lookup(rows3, prefix=["五、净利润", "四、净利润"], col_index=ci)
    return out


def yi(v):
    return None if v is None else round(v / 1e8, 2)


def fmt(v, w=9):
    """亿元展示；缺失显示 —，避免 None 破坏对齐"""
    return ("—" if v is None else f"{v / 1e8:,.2f}").rjust(w)


def main():
    ap = argparse.ArgumentParser(
        description="提取 A 股定期报告现金流质量指标（年报／半年报／季报）")
    ap.add_argument("pdf_dir", help="报告 PDF 所在目录")
    ap.add_argument("--company", default="", help="公司名，用于输出文件名")
    ap.add_argument("--years", nargs="*", type=int, help="只提取指定年份")
    ap.add_argument("--periods", nargs="+", default=["年报"],
                    choices=list(PERIODS) + ["全部"],
                    help="报告期，默认仅年报；「全部」= 年报+半年报+季报")
    ap.add_argument("--out", default="", help="输出 JSON 路径")
    a = ap.parse_args()

    periods = tuple(PERIODS) if "全部" in a.periods else tuple(a.periods)
    found = discover(a.pdf_dir, periods)
    if not found:
        sys.exit(f"在 {a.pdf_dir} 未找到匹配的报告 PDF"
                 f"（报告期 {list(periods)}；文件名需含 4 位年份及报告期关键词）")
    keys = sorted((k for k in found if not a.years or k[0] in a.years),
                  key=lambda k: (k[0], PERIODS[k[1]][2]))
    print(f"找到 {len(keys)} 份报告：{keys[0][0]}—{keys[-1][0]}，报告期 {list(periods)}\n")

    res = []
    for year, period in keys:
        r = extract(found[(year, period)], year, period)
        rev, prof = r.get("营业收入"), r.get("归母净利润")
        sc, ocf = r.get("销售收现"), r.get("经营现金流")
        # 现金余额优先现金流量表口径（见文件头说明 5）
        r["现金余额"] = r.get("期末现金") or r.get("货币资金")
        r["收现比%"] = round(sc / rev * 100, 1) if sc and rev else None
        r["净现比%"] = round(ocf / prof * 100, 1) if ocf and prof else None
        res.append(r)
        ratio = f"{r['收现比%']}%" if r["收现比%"] is not None else "—"
        label = f"{year} {period}" if periods != ("年报",) else str(year)
        print(f"{label:<12} 营收{fmt(rev)}  归母{fmt(prof, 8)}  经营现金流{fmt(ocf, 8)}  "
              f"销售收现{fmt(sc)}  收现比 {ratio}")

    miss = {k: [f"{r['年份']}{r['报告期']}" for r in res if r.get(k) is None]
            for k in ("营业收入", "归母净利润", "经营现金流", "销售收现", "现金余额")}
    miss = {k: v for k, v in miss.items() if v}
    if miss:
        print("\n⚠️  缺失项（需人工核对该期报告）：")
        for k, v in miss.items():
            print(f"   {k}: {v}")
    else:
        print("\n✅ 全部指标提取完整")

    if periods != ("年报",):
        print("\n⚠️  口径提醒：半年报/季报的利润表与现金流量表均为「年初至报告期末」累计数，"
              "\n    不可与年报直接同轴比较；资产负债表项为时点数，可比。")

    name = a.company or Path(a.pdf_dir).resolve().parent.name
    out = Path(a.out) if a.out else Path(f"{name}_现金流数据.json")
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已写入 {out}（{len(res)} 份报告）")


if __name__ == "__main__":
    main()
