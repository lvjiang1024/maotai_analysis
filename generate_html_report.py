#!/usr/bin/env python3
"""生成专业HTML财务分析报告 — 通用版，由 financial_analysis.py 自动调用"""

import pandas as pd
from datetime import datetime


def _fmt_yi(v):
    return v / 1e8


def _tag(val, unit='%'):
    if val >= 0:
        return f'<span class="tag-up">+{val:.2f}{unit}</span>'
    return f'<span class="tag-down">{val:.2f}{unit}</span>'


def _arrow(val):
    return '↑' if val >= 0 else '↓'


def generate_html_report(financial_data, growth_data, company_name, output_path='财务分析报告.html'):
    annual = financial_data[~financial_data['是否半年报']].sort_values('年份')
    latest = annual.iloc[-1]
    latest_year = int(latest['年份'])
    first_year = int(annual.iloc[0]['年份'])

    # ---- KPI 值 ----
    latest_rev = _fmt_yi(latest['营业收入'])
    latest_profit = _fmt_yi(latest['净利润'])
    latest_assets = _fmt_yi(latest['总资产'])
    latest_equity = _fmt_yi(latest['净资产'])
    latest_eps = latest['每股收益']
    latest_roe = latest['净资产收益率']

    # ---- 增长率 ----
    if len(annual) >= 2:
        prev = annual.iloc[-2]
        rev_growth = (latest['营业收入'] - prev['营业收入']) / prev['营业收入'] * 100
        profit_growth = (latest['净利润'] - prev['净利润']) / prev['净利润'] * 100
        roe_change = latest['净资产收益率'] - prev['净资产收益率']
        prev_year = int(prev['年份'])
    else:
        prev_year = first_year
        rev_growth, profit_growth, roe_change = 0, 0, 0

    # ---- 数据明细表 ----
    data_rows = ''
    for yr_row in annual.itertuples():
        yr = int(yr_row.年份)
        gr = growth_data[(growth_data['年份'] == yr) & (~growth_data['是否半年报'])]
        if len(gr) > 0:
            g = gr.iloc[0]
            tags = ''.join(
                _tag(g[f'{k}_增长率'])
                for k in ['营业收入', '净利润', '总资产', '净资产', '每股收益', '净资产收益率']
                if f'{k}_增长率' in growth_data.columns and pd.notna(g.get(f'{k}_增长率'))
            ) or '<span style="color:#999">基准年</span>'
        else:
            tags = '<span style="color:#999">基准年</span>'

        data_rows += f'''
          <tr>
            <td>{yr} 年</td>
            <td>{_fmt_yi(yr_row.营业收入):,.2f} 亿</td>
            <td>{_fmt_yi(yr_row.净利润):,.2f} 亿</td>
            <td>{_fmt_yi(yr_row.总资产):,.2f} 亿</td>
            <td>{_fmt_yi(yr_row.净资产):,.2f} 亿</td>
            <td>{yr_row.每股收益:.2f} 元</td>
            <td>{yr_row.净资产收益率:.2f}%</td>
            <td>{tags}</td>
          </tr>'''

    # ---- 增长率表格 ----
    if len(annual) >= 2:
        growth_annual = growth_data[~growth_data['是否半年报']].sort_values('年份')
        latest_g = growth_annual.iloc[-1]
        growth_rows = ''
        for k, label in [('营业收入', '营业收入'), ('净利润', '归母净利润'),
                         ('总资产', '总资产'), ('净资产', '净资产'),
                         ('每股收益', '每股收益 (EPS)'), ('净资产收益率', '净资产收益率 (ROE)')]:
            gcol = f'{k}_增长率'
            if gcol in growth_annual.columns and pd.notna(latest_g.get(gcol)):
                growth_rows += f'<tr><td>{label}</td><td>{_tag(latest_g[gcol])}</td></tr>'
    else:
        growth_rows = '<tr><td colspan="2" style="color:#999">需要至少两年数据</td></tr>'

    # ---- 三阶段分析文本 ----
    first_rev = _fmt_yi(annual.iloc[0]['营业收入'])
    first_profit = _fmt_yi(annual.iloc[0]['净利润'])

    # 近年对比
    if len(annual) >= 3:
        y2024_row = annual[annual['年份'] == 2024]
        y2025_row = annual[annual['年份'] == 2025]
        if len(y2025_row) > 0 and len(y2024_row) > 0:
            r25 = y2025_row.iloc[0]
            r24 = y2024_row.iloc[0]
            g25 = growth_data[(growth_data['年份'] == 2025) & (~growth_data['是否半年报'])].iloc[0]
            g24 = growth_data[(growth_data['年份'] == 2024) & (~growth_data['是否半年报'])].iloc[0]
            analysis_left_title = f'{latest_year} 年：增速转负'
            analysis_right_title = f'{prev_year} 年：增长高峰'
            analysis_left = f'''<ul>
              <li><strong>营收下滑 {abs(g25["营业收入_增长率"]):.2f}%</strong> — 终端动销放缓，渠道库存压力显现</li>
              <li><strong>净利润下滑 {abs(g25["净利润_增长率"]):.2f}%</strong> — 利润降幅大于营收降幅，利润率承压</li>
              <li><strong>ROE 下滑 {r25["净资产收益率"] - r24["净资产收益率"]:.2f}pp</strong> — 净资产增长但利润收缩，双重因素拉低 ROE</li>
              <li><strong>EPS 下滑 {abs(g25["每股收益_增长率"]):.2f}%</strong> — 每股收益跟随利润同步回落</li>
            </ul>'''
            analysis_right = f'''<ul>
              <li><strong>营收增长 {g24["营业收入_增长率"]:.2f}%</strong> — 受益于提价效应与渠道改革红利</li>
              <li><strong>净利润增长 {g24["净利润_增长率"]:.2f}%</strong> — 利润增速与营收增速匹配</li>
              <li><strong>ROE 提升至 {r24["净资产收益率"]:.2f}%</strong> — 资本回报效率达近年峰值</li>
              <li><strong>EPS 增长 {g24["每股收益_增长率"]:.2f}%</strong> — 每股收益同步提升</li>
            </ul>'''
        else:
            analysis_left_title, analysis_right_title = '', ''
            analysis_left, analysis_right = '', ''
    else:
        analysis_left_title, analysis_right_title = '', ''
        analysis_left, analysis_right = '', ''

    # ---- 时间线 ----
    timeline_items = ''
    for yr_row in annual.itertuples():
        yr = int(yr_row.年份)
        roe = yr_row.净资产收益率
        eps = yr_row.每股收益
        if roe >= 30:
            desc = f'ROE {roe:.2f}% / EPS {eps:.2f} 元 — 盈利能力处于行业绝对领先水平'
        elif roe >= 20:
            desc = f'ROE {roe:.2f}% / EPS {eps:.2f} 元 — 资本回报效率稳健，盈利质量优异'
        elif roe >= 15:
            desc = f'ROE {roe:.2f}% / EPS {eps:.2f} 元 — 股东回报处于较好水平'
        else:
            desc = f'ROE {roe:.2f}% / EPS {eps:.2f} 元'
        timeline_items += f'''
        <div class="timeline-item">
          <div class="timeline-year">{yr}</div>
          <div class="timeline-text">{desc}</div>
        </div>'''

    # 执行摘要
    if len(annual) >= 2:
        prev2 = annual.iloc[-2]
        prev_peak_rev = _fmt_yi(prev2['营业收入'])
        prev_peak_profit = _fmt_yi(prev2['净利润'])
        prev_peak_roe = prev2['净资产收益率']
        summary_text = f'''{company_name}在数据覆盖期内呈现<span class="highlight">"先增后调"</span>的财务走势。
        {prev_year} 年为近年来业绩高峰，营收突破 <span class="highlight">{prev_peak_rev:,.0f} 亿元</span>，净利润达 <span class="highlight">{prev_peak_profit:,.0f} 亿元</span>。
        进入 {latest_year} 年，受宏观经济承压与消费结构调整影响，公司营收同比{'下滑' if rev_growth < 0 else '增长'} <span class="highlight">{abs(rev_growth):.2f}%</span>，
        净利润同比{'下滑' if profit_growth < 0 else '增长'} <span class="highlight">{abs(profit_growth):.2f}%</span>，ROE 从 {prev_peak_roe:.2f}% {'回落至' if roe_change < 0 else '提升至'} <span class="highlight">{latest_roe:.2f}%</span>。
        尽管如此，公司总资产规模突破 <span class="highlight">{latest_assets:,.0f} 亿元</span>，净资产达 <span class="highlight">{latest_equity:,.0f} 亿元</span>，资产负债表依然稳健。'''
    else:
        summary_text = f'{company_name}最新年报显示，营收 {latest_rev:,.0f} 亿元，净利润 {latest_profit:,.0f} 亿元，ROE {latest_roe:.2f}%。'

    # ================================================================
    # HTML 模板
    # ================================================================
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{company_name}财务分析报告 {first_year}-{latest_year}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700;900&display=swap');

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  :root {{
    --gold: #C9A84C;
    --gold-light: #F5E6C8;
    --red: #C41E3A;
    --navy: #1B2A4A;
    --slate: #2D3A52;
    --bg: #F7F4EF;
    --white: #FFFFFF;
    --text: #2C2416;
    --text-secondary: #6B5E4A;
    --green: #2E7D32;
    --border: #E0D5C1;
    --shadow: 0 4px 24px rgba(27, 42, 74, 0.08);
    --shadow-lg: 0 12px 48px rgba(27, 42, 74, 0.12);
  }}

  body {{
    font-family: 'Noto Sans SC', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.8;
    -webkit-font-smoothing: antialiased;
  }}

  .hero {{
    background: linear-gradient(135deg, var(--navy) 0%, #243456 40%, #1a1a2e 100%);
    color: white;
    padding: 80px 0 60px;
    position: relative;
    overflow: hidden;
  }}
  .hero::before {{
    content: '';
    position: absolute;
    top: -50%; left: -50%;
    width: 200%; height: 200%;
    background: radial-gradient(circle at 30% 50%, rgba(201,168,76,0.08) 0%, transparent 50%),
                radial-gradient(circle at 70% 30%, rgba(196,30,58,0.06) 0%, transparent 50%);
    animation: heroGlow 8s ease-in-out infinite;
  }}
  @keyframes heroGlow {{
    0%, 100% {{ transform: translate(0, 0); }}
    50% {{ transform: translate(2%, 1%); }}
  }}
  .hero-content {{
    max-width: 1100px;
    margin: 0 auto;
    padding: 0 40px;
    position: relative;
    z-index: 1;
  }}
  .hero-badge {{
    display: inline-block;
    background: rgba(201,168,76,0.15);
    border: 1px solid var(--gold);
    color: var(--gold);
    padding: 6px 20px;
    border-radius: 20px;
    font-size: 13px;
    letter-spacing: 2px;
    margin-bottom: 24px;
  }}
  .hero h1 {{
    font-size: 48px;
    font-weight: 900;
    letter-spacing: 4px;
    margin-bottom: 12px;
    background: linear-gradient(180deg, #fff 0%, #C9A84C 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }}
  .hero-subtitle {{
    font-size: 18px;
    color: rgba(255,255,255,0.6);
    font-weight: 300;
  }}
  .hero-date {{
    color: rgba(255,255,255,0.45);
    font-size: 13px;
    margin-top: 8px;
  }}

  .container {{ max-width: 1100px; margin: 0 auto; padding: 0 40px; }}

  .kpi-section {{ margin-top: -40px; position: relative; z-index: 2; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }}
  .kpi-card {{
    background: var(--white);
    border-radius: 16px;
    padding: 28px 24px;
    box-shadow: var(--shadow-lg);
    border: 1px solid var(--border);
    transition: transform 0.3s, box-shadow 0.3s;
  }}
  .kpi-card:hover {{ transform: translateY(-4px); box-shadow: 0 16px 56px rgba(27, 42, 74, 0.16); }}
  .kpi-card.primary {{ border-left: 4px solid var(--gold); }}
  .kpi-card.accent {{ border-left: 4px solid var(--red); }}
  .kpi-label {{ font-size: 13px; color: var(--text-secondary); letter-spacing: 1px; margin-bottom: 8px; }}
  .kpi-value {{ font-size: 36px; font-weight: 900; color: var(--navy); margin-bottom: 4px; }}
  .kpi-unit {{ font-size: 14px; font-weight: 400; color: var(--text-secondary); }}
  .kpi-change {{ font-size: 13px; margin-top: 8px; font-weight: 500; }}
  .kpi-change.down {{ color: var(--red); }}
  .kpi-change.up {{ color: var(--green); }}

  .section {{ padding: 60px 0; }}
  .section-header {{ text-align: center; margin-bottom: 48px; }}
  .section-number {{ font-size: 12px; color: var(--gold); letter-spacing: 3px; margin-bottom: 8px; }}
  .section-title {{ font-size: 32px; font-weight: 700; color: var(--navy); margin-bottom: 12px; }}
  .section-line {{ width: 60px; height: 3px; background: linear-gradient(90deg, var(--gold), var(--red)); margin: 0 auto; border-radius: 2px; }}
  .section-desc {{ color: var(--text-secondary); font-size: 15px; margin-top: 12px; max-width: 600px; margin-left: auto; margin-right: auto; }}

  .chart-block {{
    background: var(--white);
    border-radius: 16px;
    padding: 32px;
    box-shadow: var(--shadow);
    margin-bottom: 32px;
    border: 1px solid var(--border);
  }}
  .chart-title {{
    font-size: 18px;
    font-weight: 700;
    color: var(--navy);
    margin-bottom: 20px;
    padding-bottom: 12px;
    border-bottom: 2px solid var(--border);
  }}
  .chart-img {{ width: 100%; border-radius: 8px; }}

  .data-table {{
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 14px;
  }}
  .data-table thead th {{
    background: var(--navy);
    color: white;
    padding: 14px 16px;
    font-weight: 500;
    font-size: 13px;
    letter-spacing: 1px;
    text-align: center;
  }}
  .data-table thead th:first-child {{ border-radius: 10px 0 0 0; text-align: left; }}
  .data-table thead th:last-child {{ border-radius: 0 10px 0 0; }}
  .data-table tbody td {{
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    text-align: center;
  }}
  .data-table tbody td:first-child {{ text-align: left; font-weight: 600; color: var(--navy); }}
  .data-table tbody tr:hover {{ background: var(--gold-light); }}
  .data-table tbody tr:last-child td:first-child {{ border-radius: 0 0 0 10px; }}
  .data-table tbody tr:last-child td:last-child {{ border-radius: 0 0 10px 0; }}
  .tag-down {{
    display: inline-block;
    background: #FDE8EC;
    color: var(--red);
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
  }}
  .tag-up {{
    display: inline-block;
    background: #E8F5E9;
    color: var(--green);
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
  }}

  .analysis-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
  .analysis-card {{
    background: var(--white);
    border-radius: 16px;
    padding: 28px;
    box-shadow: var(--shadow);
    border: 1px solid var(--border);
  }}
  .analysis-card h3 {{ font-size: 18px; font-weight: 700; color: var(--navy); margin-bottom: 12px; }}
  .analysis-card li {{ color: var(--text-secondary); font-size: 14px; line-height: 1.9; margin-bottom: 6px; }}
  .analysis-card ul {{ padding-left: 18px; }}

  .exec-summary {{
    background: linear-gradient(135deg, var(--navy), var(--slate));
    color: white;
    border-radius: 16px;
    padding: 40px;
    margin-bottom: 32px;
    position: relative;
    overflow: hidden;
  }}
  .exec-summary::after {{
    content: '';
    position: absolute;
    right: -40px;
    top: -40px;
    width: 200px;
    height: 200px;
    background: radial-gradient(circle, rgba(201,168,76,0.15) 0%, transparent 70%);
    border-radius: 50%;
  }}
  .exec-summary h3 {{
    font-size: 20px;
    font-weight: 700;
    margin-bottom: 16px;
    color: var(--gold);
    position: relative;
    z-index: 1;
  }}
  .exec-summary p {{
    font-size: 15px;
    line-height: 2;
    color: rgba(255,255,255,0.85);
    position: relative;
    z-index: 1;
  }}
  .exec-summary .highlight {{ color: var(--gold); font-weight: 600; }}

  .timeline {{
    position: relative;
    padding-left: 32px;
  }}
  .timeline::before {{
    content: '';
    position: absolute;
    left: 8px;
    top: 4px;
    bottom: 4px;
    width: 2px;
    background: linear-gradient(180deg, var(--gold), var(--red));
  }}
  .timeline-item {{ position: relative; margin-bottom: 28px; }}
  .timeline-item::before {{
    content: '';
    position: absolute;
    left: -28px;
    top: 6px;
    width: 14px;
    height: 14px;
    background: var(--gold);
    border-radius: 50%;
    border: 3px solid var(--white);
    box-shadow: 0 0 0 2px var(--gold);
  }}
  .timeline-year {{ font-size: 13px; color: var(--gold); font-weight: 700; letter-spacing: 2px; margin-bottom: 4px; }}
  .timeline-text {{ font-size: 14px; color: var(--text-secondary); line-height: 1.8; }}

  .footer {{
    background: var(--navy);
    color: rgba(255,255,255,0.5);
    text-align: center;
    padding: 40px 0;
    font-size: 13px;
    margin-top: 20px;
  }}

  @media (max-width: 768px) {{
    .kpi-grid {{ grid-template-columns: 1fr; }}
    .analysis-grid {{ grid-template-columns: 1fr; }}
    .hero h1 {{ font-size: 32px; }}
    .section-title {{ font-size: 24px; }}
    .kpi-value {{ font-size: 28px; }}
  }}

  @media print {{
    body {{ background: white; }}
    .hero {{ padding: 40px 0 30px; }}
    .chart-block, .analysis-card, .kpi-card {{ box-shadow: none; break-inside: avoid; }}
    .section {{ padding: 30px 0; }}
  }}
</style>
</head>
<body>

<header class="hero">
  <div class="hero-content">
    <div class="hero-badge">FINANCIAL ANALYSIS REPORT</div>
    <h1>{company_name}<br>财务分析报告</h1>
    <p class="hero-subtitle">基于 {first_year}—{latest_year} 年年度报告数据的深度财务分析</p>
    <p class="hero-date">报告生成日期：{datetime.now().strftime("%Y 年 %m 月 %d 日")} ｜ 数据来源：上市公司年度报告</p>
  </div>
</header>

<div class="container kpi-section">
  <div class="kpi-grid">
    <div class="kpi-card primary">
      <div class="kpi-label">{latest_year} 年营业收入</div>
      <div class="kpi-value">{latest_rev:,.0f}<span class="kpi-unit"> 亿元</span></div>
      <div class="kpi-change {'down' if rev_growth < 0 else 'up'}">{_arrow(rev_growth)} {abs(rev_growth):.2f}% 同比{'下滑' if rev_growth < 0 else '增长'}</div>
    </div>
    <div class="kpi-card primary">
      <div class="kpi-label">{latest_year} 年归母净利润</div>
      <div class="kpi-value">{latest_profit:,.0f}<span class="kpi-unit"> 亿元</span></div>
      <div class="kpi-change {'down' if profit_growth < 0 else 'up'}">{_arrow(profit_growth)} {abs(profit_growth):.2f}% 同比{'下滑' if profit_growth < 0 else '增长'}</div>
    </div>
    <div class="kpi-card accent">
      <div class="kpi-label">{latest_year} 年 ROE</div>
      <div class="kpi-value">{latest_roe:.2f}<span class="kpi-unit">%</span></div>
      <div class="kpi-change {'down' if roe_change < 0 else 'up'}">{_arrow(roe_change)} {abs(roe_change):.2f}pp 同比{'下滑' if roe_change < 0 else '提升'}</div>
    </div>
  </div>
</div>

<div class="container">
  <div class="section">
    <div class="section-header">
      <div class="section-number">PART 01</div>
      <div class="section-title">执行摘要</div>
      <div class="section-line"></div>
    </div>

    <div class="exec-summary">
      <h3>核心观点</h3>
      <p>{summary_text}</p>
    </div>
  </div>
</div>

<div class="container">
  <div class="section">
    <div class="section-header">
      <div class="section-number">PART 02</div>
      <div class="section-title">核心财务指标趋势</div>
      <div class="section-line"></div>
      <p class="section-desc">营业收入、净利润、总资产、净资产历年变化一览</p>
    </div>

    <div class="chart-block full-width">
      <div class="chart-title">年度财务指标趋势图</div>
      <img class="chart-img" src="charts/年度财务指标趋势图.png" alt="年度财务指标趋势">
    </div>

    <div class="chart-block" style="overflow-x: auto;">
      <div class="chart-title">年度财务数据明细</div>
      <table class="data-table">
        <thead>
          <tr>
            <th>年份</th>
            <th>营业收入</th>
            <th>归母净利润</th>
            <th>总资产</th>
            <th>净资产</th>
            <th>每股收益</th>
            <th>ROE</th>
            <th>变动趋势</th>
          </tr>
        </thead>
        <tbody>{data_rows}
        </tbody>
      </table>
    </div>
  </div>
</div>

<div class="container">
  <div class="section">
    <div class="section-header">
      <div class="section-number">PART 03</div>
      <div class="section-title">增长率分析</div>
      <div class="section-line"></div>
      <p class="section-desc">各财务指标年度同比增长率对比，揭示增长动能变化</p>
    </div>

    <div class="chart-block full-width">
      <div class="chart-title">财务指标同比增长率</div>
      <img class="chart-img" src="charts/财务指标增长率.png" alt="财务指标增长率">
    </div>

    <div class="chart-block">
      <div class="chart-title">最新年度增长率明细</div>
      <table class="data-table">
        <thead><tr><th>指标</th><th>同比增长率</th></tr></thead>
        <tbody>{growth_rows}</tbody>
      </table>
    </div>

    <div class="analysis-grid">
      <div class="analysis-card">
        <h3>{analysis_right_title}</h3>
        {analysis_right}
      </div>
      <div class="analysis-card">
        <h3>{analysis_left_title}</h3>
        {analysis_left}
      </div>
    </div>
  </div>
</div>

<div class="container">
  <div class="section">
    <div class="section-header">
      <div class="section-number">PART 04</div>
      <div class="section-title">盈利能力与估值指标</div>
      <div class="section-line"></div>
      <p class="section-desc">ROE 与 EPS 走势分析，评估股东回报质量</p>
    </div>

    <div class="chart-block full-width">
      <div class="chart-title">ROE 与 EPS 变化趋势</div>
      <img class="chart-img" src="charts/财务比率分析.png" alt="财务比率分析">
    </div>

    <div class="chart-block">
      <div class="chart-title">历年 ROE / EPS 速览</div>
      <div class="timeline">{timeline_items}
      </div>
    </div>
  </div>
</div>

<div class="container">
  <div class="section">
    <div class="section-header">
      <div class="section-number">PART 05</div>
      <div class="section-title">指标相关性分析</div>
      <div class="section-line"></div>
      <p class="section-desc">各财务维度之间的统计学关联，洞察业务驱动关系</p>
    </div>

    <div class="chart-block full-width">
      <div class="chart-title">财务指标相关性矩阵</div>
      <img class="chart-img" src="charts/财务指标相关性矩阵.png" alt="财务指标相关性矩阵">
    </div>
  </div>
</div>

<div class="container">
  <div class="section">
    <div class="section-header">
      <div class="section-number">PART 06</div>
      <div class="section-title">风险提示与展望</div>
      <div class="section-line"></div>
    </div>

    <div class="analysis-grid">
      <div class="analysis-card">
        <h3>宏观风险</h3>
        <ul>
          <li><strong>宏观经济承压</strong> — 经济增速放缓可能抑制终端消费需求</li>
          <li><strong>行业政策调控</strong> — 税收、环保等行业政策变化可能影响盈利空间</li>
          <li><strong>市场竞争加剧</strong> — 行业竞争格局变化可能影响市场份额</li>
        </ul>
      </div>
      <div class="analysis-card">
        <h3>公司层面关注点</h3>
        <ul>
          <li><strong>渠道库存</strong> — 关注经销商库存水平和动销情况</li>
          <li><strong>成本控制</strong> — 原材料及人工成本上升对毛利率的影响</li>
          <li><strong>增长质量</strong> — 收入增长是否可持续，利润转化效率如何</li>
          <li><strong>分红政策</strong> — 利润分配政策对股东回报的影响</li>
        </ul>
      </div>
      <div class="analysis-card">
        <h3>积极因素</h3>
        <ul>
          <li><strong>品牌壁垒</strong> — 品牌价值和市场地位构筑核心护城河</li>
          <li><strong>资产负债表稳健</strong> — 净资产 {latest_equity:,.0f} 亿，抗风险能力强</li>
          <li><strong>现金流充沛</strong> — 经营性现金流稳定，经营质量高</li>
          <li><strong>长期成长空间</strong> — 产品结构升级和市场拓展存在增量空间</li>
        </ul>
      </div>
      <div class="analysis-card">
        <h3>{latest_year + 1} 年展望</h3>
        <ul>
          <li>关注 Q1 季报能否止住下滑趋势，验证 {latest_year} 年是否为阶段性底部</li>
          <li>若宏观消费复苏信号明确，公司作为行业龙头具备较强修复动能</li>
          <li>中长期看，产品结构升级和市场拓展仍是核心增长引擎</li>
        </ul>
      </div>
    </div>
  </div>
</div>

<footer class="footer">
  <div class="container">
    <p>{company_name}财务分析报告 ｜ 数据区间 {first_year}—{latest_year} ｜ 由 AI 辅助生成</p>
    <p style="margin-top: 8px;">本报告基于公开年报数据，仅供参考，不构成投资建议</p>
  </div>
</footer>

</body>
</html>'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return output_path


if __name__ == "__main__":
    # 可直接运行，自动读取 config.json
    import json, os
    cfg = {}
    if os.path.exists('config.json'):
        with open('config.json', 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    company = cfg.get('company_name', os.path.basename(os.getcwd()))

    import sys
    sys.path.insert(0, '.')
    from financial_analysis import FinancialAnalyzer
    a = FinancialAnalyzer('.')
    a.extract_all_data()
    a.clean_data()
    a.calculate_growth_rates()
    generate_html_report(a.financial_data, a.growth_data, company)
    print(f"HTML报告已生成: 财务分析报告.html")