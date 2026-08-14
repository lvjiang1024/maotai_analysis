"""提取脚本回归自测：改动 extract_cashflow.py 后跑一遍，确认没改坏。

用法：
    python3 cashflow-quality/tests/test_extraction.py            # 快速：只跑历史上出过问题的年份（约 30 秒）
    python3 cashflow-quality/tests/test_extraction.py --full     # 完整：25 份年报全跑（约 3 分钟）
    python3 cashflow-quality/tests/test_extraction.py --years 2019 2020

退出码 0 = 通过，1 = 有回归。可直接用于 CI。

基准值来自 baseline_贵州茅台.json，每个数字都与年报原文核对过，
并与已发布报告的营收/净利润/经营现金流序列交叉验证一致。

REGRESSION_YEARS 是历史上真实踩过坑的年份，每个都对应一类格式陷阱。
快速模式只跑这些，覆盖了绝大多数会出问题的代码路径。
新发现格式问题时，请把对应年份补进这个列表，让它永久受测试保护。
"""
import argparse
import json
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = TESTS_DIR.parent
REPO_ROOT = SKILL_DIR.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

# 年份 -> 该年暴露的格式陷阱（改动相关逻辑时优先看这些年）
REGRESSION_YEARS = {
    2001: "老式资产负债表列序为「年初数 期末数」，与新式相反",
    2004: "表格布局致 extract_text 读不出连续科目名，文本预筛选假阴性",
    2008: "粗体标题被提取成重复字符（合合合合并并并并）",
    2013: "利润表与资产负债表尾部同页，且科目跨多页",
    2015: "董事会报告正文含「销售商品、提供劳务」，易误匹配到正文",
    2019: "「一、营业总收入」下挂「其中：营业收入」；归母行带序号与括号后缀",
    2020: "并表财务公司致货币资金口径断层；现金流量表表头跨页",
    2025: "最新格式",
}

TOL = 0.015  # 亿元。基准保留 2 位小数，容差略大于舍入噪声


def load_baseline():
    p = TESTS_DIR / "baseline_贵州茅台.json"
    if not p.exists():
        sys.exit(f"缺少基准文件：{p}")
    b = json.loads(p.read_text(encoding="utf-8"))
    return b, {r["年份"]: r for r in b["数据"]}


def main():
    ap = argparse.ArgumentParser(description="现金流提取脚本回归自测")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--full", action="store_true", help="跑全部 25 个年度")
    g.add_argument("--years", nargs="+", type=int, help="只跑指定年份")
    ap.add_argument("--pdf-dir", help="基准年报目录（技能装到别处时用它指向仓库的 财报/）")
    a = ap.parse_args()

    base, expected = load_baseline()
    pdf_dir = Path(a.pdf_dir) if a.pdf_dir else REPO_ROOT / base["_年报目录"]
    if not pdf_dir.is_dir():
        sys.exit(
            f"找不到基准年报目录：{pdf_dir}\n"
            f"基准数据来自 {base['_公司']} 的年报 PDF，随 maotai_analysis 仓库分发。\n"
            f"若本技能已装到 ~/.claude/skills，请用 --pdf-dir 指向仓库中的 财报/ 目录，例如：\n"
            f"  python3 {Path(__file__).name} --pdf-dir /path/to/maotai_analysis/财报"
        )

    try:
        from extract_cashflow import discover, extract
    except ImportError as e:
        sys.exit(f"无法导入提取脚本：{e}")

    found = {k[0]: v for k, v in discover(pdf_dir, ("年报",)).items()}
    if a.years:
        years = [y for y in a.years if y in found]
    elif a.full:
        years = sorted(found)
    else:
        years = sorted(y for y in REGRESSION_YEARS if y in found)

    if not years:
        sys.exit("没有可测试的年份")

    mode = "完整" if a.full else ("指定" if a.years else "快速")
    print(f"回归自测（{mode}模式）：{len(years)} 个年度\n")

    fields = [k for k in base["数据"][0] if k != "年份"]
    failures, missing = [], []

    for y in years:
        exp = expected.get(y)
        if not exp:
            print(f"  {y}  ⚠️  基准文件中无此年份，跳过")
            continue
        got = extract(found[y], y)
        got["现金余额"] = got.get("期末现金") or got.get("货币资金")

        bad = []
        for f in fields:
            e, g_ = exp[f], got.get(f)
            g_ = None if g_ is None else round(g_ / 1e8, 2)
            if e is None and g_ is None:
                continue
            if g_ is None:
                missing.append((y, f))
                bad.append(f"{f} 缺失(基准 {e})")
            elif e is None or abs(e - g_) > TOL:
                bad.append(f"{f} 期望 {e} 实得 {g_}")

        if bad:
            failures.append((y, bad))
            print(f"  {y}  ❌  " + "；".join(bad))
            if y in REGRESSION_YEARS:
                print(f"        ↑ 该年对应陷阱：{REGRESSION_YEARS[y]}")
        else:
            note = f"  （{REGRESSION_YEARS[y]}）" if y in REGRESSION_YEARS and not a.full else ""
            print(f"  {y}  ✅{note}")

    # ── 季报／半年报（累计口径）──
    qpath = TESTS_DIR / "baseline_贵州茅台_季报.json"
    cum_rev = {}          # (年份, 报告期) -> 营业收入(亿)，供后面的单调性检查复用
    if qpath.exists() and not a.years:
        qbase = json.loads(qpath.read_text(encoding="utf-8"))
        qfound = discover(pdf_dir, ("一季报", "半年报", "三季报"))
        print("\n季报／半年报（年初至报告期末累计口径）：")
        for exp in qbase["数据"]:
            k = (exp["年份"], exp["报告期"])
            if k not in qfound:
                continue
            got = extract(qfound[k], k[0], k[1])
            got["现金余额"] = got.get("期末现金") or got.get("货币资金")
            if got.get("营业收入"):
                cum_rev[k] = got["营业收入"] / 1e8
            bad = []
            # 累计列序号是季报最关键的断言：取错列会得到单季度值而非累计值
            if exp.get("累计列序号") is not None and got.get("累计列序号") != exp["累计列序号"]:
                bad.append(f"累计列序号 期望 {exp['累计列序号']} 实得 {got.get('累计列序号')}")
            for f in [x for x in exp if x not in ("年份", "报告期", "累计列序号")]:
                e, g = exp[f], got.get(f)
                g = None if g is None else round(g / 1e8, 2)
                if e is None and g is None:
                    continue
                if g is None or e is None or abs(e - g) > TOL:
                    bad.append(f"{f} 期望 {e} 实得 {g}")
            if bad:
                failures.append((k, bad))
                print(f"  {k[0]} {k[1]}  ❌  " + "；".join(bad))
            else:
                print(f"  {k[0]} {k[1]}  ✅  （累计列序号 {exp.get('累计列序号')}）")

    # 不依赖基准的恒等式检查：卖货收到的现金含增值税，恒应 >= 不含税营收。
    # 若某年反了，通常是取到了母公司报表而非合并报表。
    print()
    viol = []
    for y in years:
        e = expected.get(y)
        if e and e["销售收现"] is not None and e["营业收入"] is not None:
            if e["销售收现"] < e["营业收入"]:
                viol.append(y)
    print("恒等式 销售收现 ≥ 营业收入：", "✅ 全部满足" if not viol else f"❌ {viol}")

    # 累计口径自洽：Q1 ≤ H1 ≤ Q3 ≤ 全年。
    # 这条能抓住「季报取到单季度值」——茅台既有数据 2021 起的三季报存的是
    # 7-9 月单季度，与 2020 年前的 1-9 月累计混在同一条曲线上，
    # 表现为 2020→2021 从 672 亿断崖跌到 256 亿，看着像崩盘其实是换了口径。
    if cum_rev:
        chain, broken = {}, []
        for (yy, pp), v in cum_rev.items():   # 复用上一段的提取结果，不重复读 PDF
            chain.setdefault(yy, {})[pp] = v
        for yy, d in sorted(chain.items()):
            seq = [d.get(k) for k in ("一季报", "半年报", "三季报")]
            seq = [(k, v) for k, v in zip(("Q1", "H1", "Q3"), seq) if v]
            fy = expected.get(yy, {}).get("营业收入")
            if fy:
                seq.append(("全年", fy))
            for (n1, v1), (n2, v2) in zip(seq, seq[1:]):
                if v1 > v2 + TOL:
                    broken.append(f"{yy} {n1}({v1:,.2f}) > {n2}({v2:,.2f})")
        print("累计口径单调性 Q1≤H1≤Q3≤全年：",
              "✅ 全部满足" if not broken else "❌ " + "；".join(broken))
        if broken:
            failures.append(("累计口径", broken))

    print()
    if failures:
        print(f"❌ 回归自测未通过：{len(failures)}/{len(years)} 个年度有偏差")
        if missing:
            print(f"   其中 {len(missing)} 项完全提取不到，多半是定位逻辑被改坏")
        return 1
    print(f"✅ 回归自测通过：{len(years)} 个年度与基准完全一致")
    if not a.full:
        print("   （快速模式。改动定位或匹配逻辑后，建议再跑一次 --full）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
