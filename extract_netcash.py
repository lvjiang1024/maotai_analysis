"""提取历年净现金所需的资产负债表科目，输出时间序列。

净现金 = 现金及现金等价物 + 短期可变现金融资产 − 负债合计 − 少数股东权益

关键：2007 年前老式资产负债表列序为「年初数 期末数」，与新式「期末余额 年初余额」
相反，直接取第一个数会拿到年初值（茅台 2001 年资产总计会得到 12.7 亿而非期末 34.63 亿）。
故所有时点科目都按 period_end_first 判断列序。
"""
import json, re, sys
sys.path.insert(0, 'cashflow-quality/scripts')
import extract_cashflow as E
import pdfplumber

NUM = re.compile(r"-?[\d,]+\.\d{2}")

# 短期可变现金融资产——跨年代科目名不同（2018 新金融工具准则前后）
SHORT_ASSETS = ['交易性金融资产', '短期投资', '应收款项融资', '债权投资', '其他债权投资',
                '可供出售金融资产', '持有至到期投资', '一年内到期的非流动资产']


def bs_value(rows, label, end_first):
    """取资产负债表某科目的期末值，按列序决定取第几个数。"""
    for r in rows:
        if not r or not r[0] or E.clean(r[0]) != label:
            continue
        vals = []
        for cell in r[1:]:
            vals += [float(x.replace(',', '')) for x in NUM.findall(cell or '')
                     if abs(float(x.replace(',', ''))) >= 1000]
        if vals:
            return vals[0] if end_first else (vals[1] if len(vals) > 1 else vals[0])
    return None


def equity_total(rows, end_first):
    """所有者权益合计。2020 年起标签写作「所有者权益（或股东权益）合计」，
    精确匹配失效，故用谓词；须排除「归属于母公司…合计」。"""
    for r in rows:
        if not r or not r[0]:
            continue
        c = E.clean(r[0])
        if '权益' in c and c.endswith('合计') and '归属于母公司' not in c and '少数股东' not in c:
            vals = []
            for cell in r[1:]:
                vals += [float(x.replace(',', '')) for x in NUM.findall(cell or '')
                         if abs(float(x.replace(',', ''))) >= 1000]
            if vals:
                return vals[0] if end_first else (vals[1] if len(vals) > 1 else vals[0])
    return None


def extract_bs(path, year):
    with pdfplumber.open(path) as pdf:
        fb = E.find_statement(pdf, '货币资金')
        # 列序必须按「实际读取的那一页」判断：老式报告无「合并资产负债表」标题，
        # 若拿审计报告页去找表头会一无所获而默认「期末在前」，导致整列取成年初数
        # （茅台 2001—2004 即如此，2002 会取到 2001 年末的 34.6 亿）。
        rows, pg = E.statement_rows_at(pdf, 'bs', fb, span=4)
        ef = E.period_end_first(pdf, pg)
        out = {'年份': year, '期末在前': ef, '锚点页': pg}
        for k in ('资产总计', '资产合计', '负债合计', '少数股东权益'):
            v = bs_value(rows, k, ef)
            if v is not None:
                out[k] = v
        eq = equity_total(rows, ef)
        if eq is not None:
            out['所有者权益合计'] = eq
        short = {}
        for k in SHORT_ASSETS:
            v = bs_value(rows, k, ef)
            if v:
                short[k] = v
        out['短期金融资产明细'] = {k: round(v / 1e8, 2) for k, v in short.items()}
        out['短期金融资产'] = sum(short.values())
        return out


def main():
    cf = {r['年份']: r for r in json.load(open('贵州茅台_现金流数据.json', encoding='utf-8'))}
    found = {k[0]: v for k, v in E.discover('财报', ('年报',)).items()}
    res = []
    for y in sorted(found):
        b = extract_bs(found[y], y)
        assets = b.get('资产总计') or b.get('资产合计')
        equity = b.get('所有者权益合计')
        liab = b.get('负债合计')
        minority = b.get('少数股东权益') or 0.0
        # 现金优先用现金流量表口径（与净现金一节一致）
        c = cf.get(y, {})
        cash = c.get('期末现金') or c.get('货币资金')
        short = b['短期金融资产']
        net = (cash + short - liab - minority) if (cash and liab is not None) else None
        # 会计恒等式：资产总计 = 负债合计 + 所有者权益合计
        ok = None
        if assets and liab is not None and equity:
            ok = abs(assets - (liab + equity)) / assets < 0.005
        res.append({'年份': y, '现金及等价物': cash, '短期金融资产': short,
                    '负债合计': liab, '少数股东权益': minority, '净现金': net,
                    '资产总计': assets, '所有者权益合计': equity,
                    '恒等式': ok, '期末在前': b['期末在前'], '锚点页': b['锚点页'],
                    '短期金融资产明细': b['短期金融资产明细']})
    json.dump(res, open('/tmp/netcash_series.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    f = lambda v: '—' if v is None else f'{v/1e8:>9,.1f}'
    print(f"{'年份':<6}{'现金等价物':>11}{'短期金融':>10}{'负债合计':>10}{'少数股东':>10}"
          f"{'净现金':>11}  恒等式 列序")
    print('─' * 78)
    for r in res:
        eq = '✅' if r['恒等式'] else ('❌' if r['恒等式'] is False else '—')
        col = '期末在前' if r['期末在前'] else '年初在前'
        print(f"{r['年份']:<6}{f(r['现金及等价物'])}{f(r['短期金融资产'])}{f(r['负债合计'])}"
              f"{f(r['少数股东权益'])}{f(r['净现金'])}    {eq}  {col}")


if __name__ == '__main__':
    main()
