"""提取分产品销量与吨价（茅台酒 / 系列酒）。

数据源是年报「产品情况」表：产品档次 | 产量(吨) | 销量(吨) | 销售收入(万元)。
注意：「产销量情况分析表」只披露"酒类"合计销量（2025 年为 85,104.14 吨），
不分产品；分产品数据在另一张「产品情况」表里，两者可相互勾稽
（46,750.66 ＋ 38,353.48 = 85,104.14）。

吨价 = 销售收入 ÷ 销量（万元/吨）。
"""
import json, re, sys
sys.path.insert(0, 'cashflow-quality/scripts')
import extract_cashflow as E
import pdfplumber

NUM = re.compile(r"-?[\d,]+\.\d{2}")
MOUTAI = ('茅台酒',)
SERIES = ('其他系列酒', '系列酒', '酱香系列酒')


def _header_map(tb):
    """从表头定位「销量」与「销售收入」所在列号。

    不能按固定位置取数：2016 年表在销量后多一列「同比（%）」，
    列序为 产量|同比|销量|同比|产销率|销售收入，而 2025 年为
    产量|同比|销量|产销率|销售收入。按位置取会把同比当成销售收入。
    另外「产销率」单元格常为空，把整行压成数字列表会进一步错位。
    """
    for r in tb[:4]:
        if not r:
            continue
        cells = [E.clean(c or '') for c in r]
        idx = {}
        for j, c in enumerate(cells):
            if '销量' in c and '销量' not in idx:
                idx['销量'] = j
            elif '产量' in c and '产量' not in idx:
                idx['产量'] = j
            elif '销售收入' in c and '销售收入' not in idx:
                idx['销售收入'] = j
        if '销量' in idx and '销售收入' in idx:
            return idx
    return None


def _num(cell):
    """单元格内的数字可能被换行拆开（2016 年报的 "3,\n671,441.33"），
    正则匹配不跨行会只取到后半段，367 亿读成 67 亿。故先折叠空白。"""
    m = NUM.findall(E.clean(cell))
    return float(m[0].replace(',', '')) if m else None


def _rows_from(tb, out, page_idx, idx):
    for r in tb:
        if not r or not r[0]:
            continue
        c = E.clean(r[0])
        key = '茅台酒' if c in MOUTAI else ('系列酒' if c in SERIES else None)
        if not key or key in out:
            continue
        vol = _num(r[idx['销量']]) if idx['销量'] < len(r) else None
        rev = _num(r[idx['销售收入']]) if idx['销售收入'] < len(r) else None
        prod = _num(r[idx['产量']]) if idx.get('产量', 99) < len(r) else None
        if vol and rev and vol > 1000 and rev > 1000:
            out[key] = {'产量吨': prod, '销量吨': vol,
                        '销售收入万元': rev, '页': page_idx}


def parse_products(path):
    """返回 {'茅台酒': {...}, '系列酒': {...}}。

    表可能跨页——2022 年报茅台酒在第 13 页、其他系列酒在第 14 页，
    续页往往没有表头，故沿用表头页的列映射再扫描其后一页。
    """
    out = {}
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            idx = None
            for tb in tables:
                m = _header_map(tb)
                if m:
                    idx = m
                    _rows_from(tb, out, i, m)
            if idx is None:
                continue
            if len(out) < 2 and i + 1 < len(pdf.pages):   # 续页无表头，沿用列映射
                for tb in pdf.pages[i + 1].extract_tables():
                    _rows_from(tb, out, i + 1, idx)
            if out:
                break
    return out


def main():
    years = [int(a) for a in sys.argv[1:]] or list(range(2015, 2026))
    rows = []
    for y in years:
        try:
            d = parse_products(f'财报/{y}年财报.pdf')
        except FileNotFoundError:
            continue
        rows.append((y, d))
    print(f"{'年份':<6}{'茅台酒销售额':>12}{'销量(吨)':>12}{'吨价':>8}"
          f"{'系列酒销售额':>13}{'销量(吨)':>12}{'吨价':>8}")
    print('─' * 74)
    res = []
    for y, d in rows:
        m, s = d.get('茅台酒'), d.get('系列酒')
        rec = {'年份': y}
        cells = []
        for key, dd in (('茅台酒', m), ('系列酒', s)):
            if dd:
                rev = dd['销售收入万元'] / 1e4          # 万元 -> 亿元
                vol = dd['销量吨']
                pt = rev * 1e4 / vol / 1e4 if vol else None   # 亿元->万元 再除吨
                pt = rev * 10000 / vol if vol else None       # 万元/吨
                rec[key] = {'销售额亿': round(rev, 2), '销量吨': vol,
                            '吨价万元每吨': round(pt, 1) if pt else None}
                cells += [f'{rev:>12,.2f}', f'{vol:>12,.2f}', f'{pt:>8,.1f}']
            else:
                rec[key] = None
                cells += [f'{"—":>12}', f'{"—":>12}', f'{"—":>8}']
        res.append(rec)
        print(f'{y:<6}' + ''.join(cells))
    json.dump(res, open('/tmp/volume_price.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
