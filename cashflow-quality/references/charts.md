# 现金流质量图表模板

四张标准图的 Chart.js 配置。依赖 `<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>`。

> 若嵌入的是 Artifact 或有 CSP 限制的页面，外部 CDN 会被拦截，需改用内联的 Chart.js
> 或改画内联 SVG。

## 数据准备

把提取脚本产出的 JSON 转成 JS 数组（单位统一为亿元，保留 2 位小数）：

```python
import json
d = json.load(open("<公司名>_现金流数据.json"))
yi = lambda v: None if v is None else round(v / 1e8, 2)
arr = lambda k: [yi(r.get(k)) for r in d]

print("const CF_Y =", json.dumps([str(r["年份"]) for r in d]))
for js, key in [("CF_REV","营业收入"), ("CF_PROFIT","归母净利润"), ("CF_OCF","经营现金流"),
                ("CF_SALESCASH","销售收现"), ("CF_CAPEX","资本开支"),
                ("CF_DIV","分红支出"), ("CF_CASH","现金余额"), ("CF_DEBT","有息负债")]:
    print(f"const {js} =", json.dumps(arr(key)) + ";")
print("const CF_CASHRATIO = CF_SALESCASH.map(function(v,i){return v/CF_REV[i]*100;});")
```

配色（金/红/深蓝/青，与深色导航栏搭配）：

```js
var C = ['#C9A84C','#C41E3A','#1B2A4A','#4ecdc4','#fd79a8','#a29bfe','#00b894','#e17055'];
```

## 图 1：经营现金流 vs 净利润

实线为现金流、虚线为利润，两线贴合说明利润有现金支撑；现金流长期低于利润要警惕。

```js
new Chart(document.getElementById('chart_cf_profit'), { type: 'line',
  data: { labels: CF_Y, datasets: [
    { label: '净利润(亿)', data: CF_PROFIT, borderColor: C[1], borderDash: [6,4],
      tension: 0.2, pointRadius: 3, borderWidth: 2, fill: false },
    { label: '经营活动现金流量净额(亿)', data: CF_OCF, borderColor: C[2],
      tension: 0.2, pointRadius: 3, borderWidth: 3, fill: false }
  ] },
  options: { responsive: true, plugins: { legend: { position: 'top' } },
             scales: { y: { title: { display: true, text: '亿元' } } } }
});
```

## 图 2：销售收现 vs 营业收入

```js
new Chart(document.getElementById('chart_cf_sales'), { type: 'line',
  data: { labels: CF_Y, datasets: [
    { label: '销售商品、提供劳务收到的现金(亿)', data: CF_SALESCASH, borderColor: C[0],
      borderDash: [6,4], tension: 0.2, pointRadius: 3, borderWidth: 2, fill: false },
    { label: '营业收入(亿)', data: CF_REV, borderColor: C[2],
      tension: 0.2, pointRadius: 3, borderWidth: 3, fill: false }
  ] },
  options: { responsive: true, plugins: { legend: { position: 'top' } },
             scales: { y: { title: { display: true, text: '亿元' } } } }
});
```

## 图 3：收现比

柱状更适合逐年比较。以 100% 为界着色——达标金色、不达标红色，异常年份一眼可见。

```js
new Chart(document.getElementById('chart_cf_ratio'), { type: 'bar',
  data: { labels: CF_Y, datasets: [{ label: '收现比%', data: CF_CASHRATIO,
    backgroundColor: CF_CASHRATIO.map(function(v){ return v >= 100 ? C[0]+'99' : C[1]+'99'; }) }] },
  options: { responsive: true, plugins: { legend: { display: false } },
             scales: { y: { title: { display: true, text: '收现比 %' }, suggestedMin: 90 } } }
});
```

## 图 4：现金余额 / 资本开支 / 现金分红 / 有息负债

四条线量级差异大，现金余额会把其余三条压到底部——这本身就是结论（现金充裕、
不靠借钱、分红与资本开支相对可控），不必强行拆成双轴。

```js
new Chart(document.getElementById('chart_cf_balance'), { type: 'line',
  data: { labels: CF_Y, datasets: [
    { label: '现金余额(亿)', data: CF_CASH, borderColor: C[2], tension: 0.2, pointRadius: 3, borderWidth: 3, fill: false },
    { label: '资本开支(亿)', data: CF_CAPEX, borderColor: C[3], tension: 0.2, pointRadius: 2, borderWidth: 2, fill: false },
    { label: '现金分红(亿)', data: CF_DIV, borderColor: C[0], borderDash: [6,4], tension: 0.2, pointRadius: 3, borderWidth: 2, fill: false },
    { label: '有息负债(亿)', data: CF_DEBT, borderColor: C[1], tension: 0.2, pointRadius: 1, borderWidth: 2, fill: false }
  ] },
  options: { responsive: true, plugins: { legend: { position: 'top' } },
             scales: { y: { title: { display: true, text: '亿元' } } } }
});
```

## HTML 骨架

```html
<div class="section" id="sec-cashflow">
  <div class="chart-row single full"><div class="chart-block">
    <h3>经营活动现金流量净额 vs 净利润（亿元，YYYY—YYYY）</h3>
    <canvas id="chart_cf_profit"></canvas></div></div>
  <!-- 其余三张同构 -->
  <div class="chart-row single full"><div class="chart-block">
    <p style="font-size:12px;color:#888;margin:0;line-height:1.7">口径说明……</p></div></div>
</div>
```

图表在 Tab 首次显示时才初始化——隐藏容器宽度为 0，提前建的图会画不出来：

```js
if (!cr[id]) { cr[id] = true; var f = { cashflow: initCashflow, /* … */ }; if (f[id]) f[id](); }
```

## 判读话术

写结论时用数据说话，避免空泛的「现金流良好」。可套用的表述：

- **收现比**：「N 年间每年均 >100%，最低 X 年 A%，最高 Y 年 B%——收入基本全部收到现金，
  应收账款压力小。」含税收现天然高于不含税营收，故 100%~120% 属正常区间；
  若长期 <100%，说明赊销严重。
- **净现比背离**：「X 年经营现金流 A 亿远超当年净利润 B 亿，主因预收款（经销商打款）
  大幅增加」——预收暴增是需求旺盛的先行信号；反之现金流持续低于利润，要查应收与存货。
- **有息负债**：「N 年间几乎零有息负债，扩张完全依靠自身造血。」
- **现金去向**：对比资本开支与分红的相对规模，说明公司处于扩张期还是回报期。

## 验证清单

图表上线前逐项确认（可在浏览器控制台跑）：

```js
['chart_cf_profit','chart_cf_sales','chart_cf_ratio','chart_cf_balance'].forEach(function(id){
  var el = document.getElementById(id), ch = el && Chart.getChart(el);
  console.log(id, ch ? ch.data.labels.length + '点 painted=' + (el.toDataURL().length > 5000) : 'FAIL');
});
```

- [ ] 每张图的数据点数 = 年份数，无 null（有 null 说明提取漏了，回头补）
- [ ] `painted=true`（canvas 真的画出了像素，不只是建了对象）
- [ ] 销售收现每年 ≥ 营业收入（若某年反了，多半是取到了母公司报表）
- [ ] 经营现金流与其他来源的数据交叉核对一致
- [ ] 口径说明已写在图表下方
