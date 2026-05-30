#!/usr/bin/env python3
"""
上市公司财务数据分析工具 — 通用版
用法：
  1. 修改 config.json 中的 company_name
  2. 将 PDF 年报/半年报放入当前目录
  3. 运行: python3 financial_analysis.py

输出: 财务分析报告.html, 财务分析报告.md, 财务数据.xlsx, charts/
"""

import os, re, json, sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import seaborn as sns
from pdfplumber import open as open_pdf
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')


# ============================================================
# 配置加载
# ============================================================
def load_config():
    """从 config.json 加载公司名称"""
    if os.path.exists('config.json'):
        with open('config.json', 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    else:
        cfg = {}
    cfg.setdefault('company_name', os.path.basename(os.getcwd()))
    cfg.setdefault('company_short', cfg['company_name'])
    return cfg

CONFIG = load_config()
COMPANY = CONFIG['company_name']
COMPANY_SHORT = CONFIG['company_short']


# ============================================================
# 跨平台中文字体自动检测
# ============================================================
def _detect_chinese_font():
    candidates = [
        'Heiti TC', 'STHeiti', 'PingFang HK', 'Hiragino Sans GB',  # macOS
        'SimHei', 'Microsoft YaHei', 'FangSong', 'KaiTi',           # Windows
        'Noto Sans CJK SC', 'Noto Sans SC', 'WenQuanYi Micro Hei', # Linux
        'Lantinghei SC', 'Songti SC', 'Kaiti SC', 'STFangsong',
    ]
    available = sorted(set(f.name for f in fm.fontManager.ttflist))
    detected = [f for f in candidates if f in available]
    if not detected:
        fm._load_fontmanager(try_read_cache=False)
        available = sorted(set(f.name for f in fm.fontManager.ttflist))
        detected = [f for f in candidates if f in available]
    return detected if detected else ['sans-serif']

_chinese_fonts = _detect_chinese_font()
plt.rcParams['font.sans-serif'] = _chinese_fonts
plt.rcParams['axes.unicode_minus'] = False


# ============================================================
# 分析器
# ============================================================
class FinancialAnalyzer:
    def __init__(self, pdf_dir='.'):
        self.pdf_dir = pdf_dir
        self.company = COMPANY
        self.pdf_files = self._get_pdf_files()
        self.financial_data = pd.DataFrame()

    def _get_pdf_files(self):
        pdf_files = []
        for f in os.listdir(self.pdf_dir):
            if f.endswith('.pdf') and ('财报' in f or '半年度报告' in f or '年报' in f or '半年报' in f):
                pdf_files.append(os.path.join(self.pdf_dir, f))
        return sorted(pdf_files)

    def _parse_report_date(self, filename):
        patterns = [
            r'(\d{4})年(?:半年度)?(?:财报|年报|半年报|报告)',
            r'(\d{4})年.*?报',
            r'(\d{4})'
        ]
        for p in patterns:
            m = re.search(p, filename)
            if m:
                year = int(m.group(1))
                half = any(k in filename for k in ['半年', '半年度'])
                return year, half
        return None, None

    def _extract_financial_data(self, file_path, year, is_half_year):
        data = {
            '年份': year,
            '是否半年报': is_half_year,
            '报告期': '半年报' if is_half_year else '年报'
        }

        def _rm_spaces(s):
            return s.replace(' ', '').replace('\n', '') if s else ''

        try:
            with open_pdf(file_path) as pdf:
                for page_idx in range(4, min(9, len(pdf.pages))):
                    tables = pdf.pages[page_idx].extract_tables()
                    for table in tables:
                        if not table:
                            continue
                        for row in table:
                            row_text = ' '.join([str(c) if c else '' for c in row])
                            clean = _rm_spaces(row_text)

                            if clean.startswith('营业收入') and data.get('营业收入') is None:
                                data['营业收入'] = self._parse_first_number(row)
                            elif clean.startswith('归属于上市公司股东的净利润') and '扣除' not in clean and data.get('净利润') is None:
                                data['净利润'] = self._parse_first_number(row)
                            elif clean.startswith('归属于上市公司股东的净资产') and data.get('净资产') is None:
                                data['净资产'] = self._parse_first_number(row)
                            elif clean.startswith('总资产') and data.get('总资产') is None:
                                data['总资产'] = self._parse_first_number(row)
                            elif '基本每股收益' in clean and '扣除非' not in clean and data.get('每股收益') is None:
                                data['每股收益'] = self._parse_first_number(row)
                            elif '加权平均净资产收益率' in clean and '扣除非' not in clean and data.get('净资产收益率') is None:
                                v = self._parse_first_number(row)
                                if v and 10 < v < 50:
                                    data['净资产收益率'] = v

        except Exception as e:
            print(f"  Error: {e}")

        for key in ['营业收入', '净利润', '总资产', '净资产', '每股收益', '净资产收益率']:
            if key not in data:
                data[key] = None

        return data

    def _parse_first_number(self, row):
        for cell in row[1:]:
            if cell:
                val = str(cell).replace(',', '').replace('%', '').strip()
                try:
                    return float(val)
                except ValueError:
                    continue
        return None

    def extract_all_data(self):
        all_data = []
        for fp in self.pdf_files:
            fn = os.path.basename(fp)
            year, half = self._parse_report_date(fn)
            period = "半年报" if half else "年报"
            print(f"  [{period}] {fn} ({year}年)")
            if year is None:
                print(f"    ⚠ 无法解析年份，跳过")
                continue
            row = self._extract_financial_data(fp, year, half)
            missing = [k for k in ['营业收入','净利润','总资产','净资产'] if row.get(k) is None]
            if missing:
                print(f"    ⚠ 未提取到: {', '.join(missing)}")
            all_data.append(row)
        self.financial_data = pd.DataFrame(all_data)
        return self.financial_data

    def clean_data(self):
        df = self.financial_data.copy()
        for col in ['营业收入', '净利润', '总资产', '净资产', '每股收益', '净资产收益率']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.drop_duplicates().sort_values(['年份', '是否半年报']).reset_index(drop=True)
        self.financial_data = df
        return df

    def calculate_growth_rates(self):
        df = self.financial_data.copy()
        annual = df[~df['是否半年报']].sort_values('年份').copy()
        half = df[df['是否半年报']].sort_values('年份').copy()

        cols = ['营业收入', '净利润', '总资产', '净资产', '每股收益', '净资产收益率']
        for col in cols:
            if col in annual.columns:
                annual[f'{col}_增长率'] = annual[col].pct_change() * 100
        for col in cols:
            if col in half.columns:
                half[f'{col}_增长率'] = half[col].pct_change() * 100

        self.growth_data = pd.concat([annual, half]).sort_values(['年份', '是否半年报'])
        return self.growth_data

    def generate_charts(self):
        os.makedirs('charts', exist_ok=True)
        annual = self.financial_data[~self.financial_data['是否半年报']]
        if len(annual) > 0:
            self._plot_trend(annual)
            self._plot_corr(annual)
            self._plot_ratios(annual)
        if hasattr(self, 'growth_data') and len(self.growth_data) > 0:
            growth_annual = self.growth_data[~self.growth_data['是否半年报']]
            self._plot_growth(growth_annual)
        print("  图表已生成: charts/")

    def _plot_trend(self, df):
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        axes = axes.flatten()
        metrics = ['营业收入', '净利润', '总资产', '净资产']
        colors = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#f9ca24']
        for i, m in enumerate(metrics):
            if m in df.columns and df[m].notna().any():
                axes[i].plot(df['年份'], df[m], marker='o', color=colors[i], linewidth=3)
                axes[i].set_title(f'{m}(亿元)', fontsize=14, fontweight='bold')
                axes[i].set_xlabel('年份')
                axes[i].grid(True, alpha=0.3)
                axes[i].set_xticks(df['年份'])
        plt.tight_layout()
        plt.savefig('charts/年度财务指标趋势图.png', dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_growth(self, df):
        growth_cols = [c for c in df.columns if '_增长率' in c]
        if not growth_cols:
            return
        n = len(growth_cols)
        rows = (n + 2) // 3
        fig, axes = plt.subplots(rows, 3, figsize=(18, 5 * rows))
        axes = axes.flatten() if n > 1 else [axes]
        for i, col in enumerate(growth_cols):
            if df[col].notna().any():
                axes[i].bar(df['年份'], df[col], color='#6c5ce7', alpha=0.7)
                axes[i].set_title(col.replace('_', ' '), fontsize=12, fontweight='bold')
                axes[i].set_xlabel('年份')
                axes[i].set_ylabel('增长率(%)')
                axes[i].grid(True, alpha=0.3)
                axes[i].set_xticks(df['年份'])
                axes[i].axhline(y=0, color='red', linestyle='--', alpha=0.7)
        for j in range(n, len(axes)):
            axes[j].set_visible(False)
        plt.tight_layout()
        plt.savefig('charts/财务指标增长率.png', dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_corr(self, df):
        num_cols = ['营业收入', '净利润', '总资产', '净资产', '每股收益', '净资产收益率']
        existing = [c for c in num_cols if c in df.columns and df[c].notna().all()]
        if len(existing) >= 2:
            corr = df[existing].corr()
            plt.figure(figsize=(10, 8))
            sns.heatmap(corr, annot=True, cmap='coolwarm', center=0,
                       square=True, fmt='.2f')
            plt.title('财务指标相关性矩阵', fontsize=14, fontweight='bold')
            plt.savefig('charts/财务指标相关性矩阵.png', dpi=300, bbox_inches='tight')
            plt.close()

    def _plot_ratios(self, df):
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        if '净资产收益率' in df.columns:
            axes[0].plot(df['年份'], df['净资产收益率'], marker='o', color='#fd79a8', linewidth=3)
            axes[0].set_title('净资产收益率(ROE)', fontsize=14, fontweight='bold')
            axes[0].grid(True, alpha=0.3)
            axes[0].set_xticks(df['年份'])
        if '每股收益' in df.columns:
            axes[1].plot(df['年份'], df['每股收益'], marker='o', color='#a29bfe', linewidth=3)
            axes[1].set_title('每股收益(EPS)', fontsize=14, fontweight='bold')
            axes[1].grid(True, alpha=0.3)
            axes[1].set_xticks(df['年份'])
        plt.tight_layout()
        plt.savefig('charts/财务比率分析.png', dpi=300, bbox_inches='tight')
        plt.close()

    def generate_markdown_report(self):
        lines = []
        lines.append(f"# {self.company}财务数据分析报告")
        lines.append(f"生成日期: {datetime.now().strftime('%Y年%m月%d日')}")
        lines.append("")

        annual = self.financial_data[~self.financial_data['是否半年报']].sort_values('年份')
        if len(annual) > 0:
            latest = annual.iloc[-1]
            lines.append("## 一、最新年报摘要")
            lines.append("")
            lines.append("| 指标 | 数值 |")
            lines.append("|------|------|")
            for k, unit in [('营业收入', '亿元'), ('净利润', '亿元'), ('总资产', '亿元'),
                           ('净资产', '亿元'), ('每股收益', '元'), ('净资产收益率', '%')]:
                if k in annual.columns and pd.notna(latest.get(k)):
                    v = latest[k] if k in ['每股收益', '净资产收益率'] else latest[k] / 1e8
                    lines.append(f"| {k} | {v:.2f}{unit} |")
            lines.append("")

        if hasattr(self, 'growth_data') and len(annual) > 1:
            growth_annual = self.growth_data[~self.growth_data['是否半年报']].sort_values('年份')
            latest_g = growth_annual.iloc[-1]
            lines.append("## 二、同比增长率")
            lines.append("")
            lines.append("| 指标 | 增长率 |")
            lines.append("|------|--------|")
            for k in ['营业收入', '净利润', '总资产', '净资产', '每股收益', '净资产收益率']:
                gcol = f'{k}_增长率'
                if gcol in growth_annual.columns and pd.notna(latest_g.get(gcol)):
                    arrow = "↑" if latest_g[gcol] > 0 else "↓"
                    lines.append(f"| {k} | {arrow} {latest_g[gcol]:.2f}% |")
            lines.append("")

        lines.append("## 三、趋势分析")
        lines.append("")
        if len(annual) >= 2:
            for k, desc in [('营业收入', '营收规模'), ('净利润', '净利润'),
                           ('净资产收益率', '净资产收益率(ROE)')]:
                if k in annual.columns and annual[k].notna().all():
                    vals = annual[k].values
                    if k in ['净资产收益率']:
                        lines.append(f"- **{desc}**: {vals[0]:.2f}% → {vals[-1]:.2f}%")
                    else:
                        lines.append(f"- **{desc}**: {vals[0]/1e8:.2f}亿 → {vals[-1]/1e8:.2f}亿")
        lines.append("")

        lines.append("## 四、风险提示")
        lines.append("- 宏观经济环境变化可能影响消费需求")
        lines.append("- 行业政策调整可能影响定价和竞争格局")
        lines.append("- 原材料及人工成本上升可能压缩利润空间")

        with open('财务分析报告.md', 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return '\n'.join(lines)

    def save_data_to_excel(self):
        writer = pd.ExcelWriter('财务数据.xlsx', engine='xlsxwriter')
        self.financial_data.to_excel(writer, sheet_name='原始数据', index=False)
        if hasattr(self, 'growth_data'):
            self.growth_data.to_excel(writer, sheet_name='增长率数据', index=False)
        writer.close()
        print("  数据已保存: 财务数据.xlsx")


# ============================================================
# 主入口
# ============================================================
def main():
    print("=" * 56)
    print(f"  {COMPANY}财务数据分析工具")
    print(f"  中文字体: {_chinese_fonts[0]}")
    print("=" * 56)

    a = FinancialAnalyzer('.')

    print(f"\n📄 发现 {len(a.pdf_files)} 个PDF报告文件:")
    for fp in a.pdf_files:
        print(f"    - {os.path.basename(fp)}")
    if not a.pdf_files:
        print("  ⚠ 未找到PDF财报文件！请将年报PDF放入当前目录。")
        print("  支持的文件名格式: XXXX年财报.pdf, XXXX年半年报.pdf 等")
        return

    print("\n1️⃣  提取财务数据...")
    a.extract_all_data()

    print("\n2️⃣  数据清洗...")
    a.clean_data()
    n_annual = len(a.financial_data[~a.financial_data['是否半年报']])
    n_half = len(a.financial_data[a.financial_data['是否半年报']])
    print(f"  共 {len(a.financial_data)} 条记录 ({n_half} 半年报 + {n_annual} 年报)")

    print("\n3️⃣  计算增长率...")
    a.calculate_growth_rates()

    print("\n4️⃣  生成图表...")
    a.generate_charts()

    print("\n5️⃣  生成Markdown报告...")
    a.generate_markdown_report()
    print("  报告已生成: 财务分析报告.md")

    print("\n6️⃣  保存Excel...")
    a.save_data_to_excel()

    print("\n7️⃣  生成HTML报告...")
    from generate_html_report import generate_html_report
    generate_html_report(a.financial_data, a.growth_data, a.company)
    print("  报告已生成: 财务分析报告.html")

    print("\n" + "=" * 56)
    print(f"  ✅ {COMPANY}财务分析完成!")
    print("  生成文件: 财务分析报告.html, 财务分析报告.md, 财务数据.xlsx, charts/")
    print("=" * 56)


if __name__ == "__main__":
    main()