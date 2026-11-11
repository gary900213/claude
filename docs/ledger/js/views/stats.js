// 統計：本月支出類別分佈、近 6 個月收支趨勢。
import { listMonths } from '../services/ledger.js';
import { listCategories } from '../services/categories.js';
import { addMonths, formatAmount, formatSigned, isMonthStr, monthOf, todayStr } from '../domain/format.js';
import { groupByCategory, monthlyTrend, summarize } from '../domain/stats.js';
import { replaceRoute } from '../router.js';
import { categoryColors, emptyState, esc, monthSwitcher, summaryCards } from './components.js';
import { drawBars, drawDonut } from './charts.js';

const TREND_MONTHS = 6;

export async function render(el, ctx) {
  const m = ctx.query.get('m');
  const month = isMonthStr(m) ? m : monthOf(todayStr());
  const [trendTxs, cats] = await Promise.all([
    listMonths(addMonths(month, -(TREND_MONTHS - 1)), month),
    listCategories({ includeHidden: true }),
  ]);
  const monthTxs = trendTxs.filter((t) => monthOf(t.date) === month);
  const summary = summarize(monthTxs);
  const groups = groupByCategory(monthTxs, cats, 'expense');
  const trend = monthlyTrend(trendTxs, month, TREND_MONTHS).map((r) => ({
    ...r,
    label: `${Number(r.month.slice(5))}月`,
  }));
  const colors = categoryColors(cats);
  const colorOf = (id) => colors.get(id) ?? '#94a3b8';

  el.innerHTML = `
    <header class="page-head">${monthSwitcher(month)}</header>
    ${summaryCards(summary)}

    <section class="card">
      <div class="section-head"><h2>支出分佈</h2></div>
      ${
        groups.length
          ? `<canvas class="chart" data-chart="donut" role="img" aria-label="本月各類別支出佔比"></canvas>
             <ul class="rank">
               ${groups
                 .map(
                   (g) => `
                 <li>
                   <span class="rank-dot" style="background:${colorOf(g.categoryId)}"></span>
                   <span class="rank-name">${esc(g.category?.icon ?? '❔')} ${esc(g.category?.name ?? '未知類別')}
                     <small>${g.count} 筆</small></span>
                   <span class="rank-pct">${(g.ratio * 100).toFixed(1)}%</span>
                   <span class="rank-amt">${formatAmount(g.total)}</span>
                   <span class="rank-bar"><i style="width:${(g.ratio * 100).toFixed(1)}%;background:${colorOf(g.categoryId)}"></i></span>
                 </li>`,
                 )
                 .join('')}
             </ul>`
          : emptyState('這個月還沒有支出')
      }
    </section>

    <section class="card">
      <div class="section-head">
        <h2>近 ${TREND_MONTHS} 個月收支</h2>
        <span class="legend"><i class="income-bg"></i>收入 <i class="expense-bg"></i>支出</span>
      </div>
      <canvas class="chart" data-chart="bars" role="img" aria-label="近 ${TREND_MONTHS} 個月收入與支出長條圖"></canvas>
      <table class="trend-table">
        <thead><tr><th>月份</th><th>收入</th><th>支出</th><th>結餘</th></tr></thead>
        <tbody>
          ${trend
            .slice()
            .reverse()
            .map(
              (r) => `
            <tr>
              <td>${r.label}</td>
              <td class="income">${formatAmount(r.income)}</td>
              <td class="expense">${formatAmount(r.expense)}</td>
              <td class="${r.balance < 0 ? 'expense' : ''}">${formatSigned(r.balance)}</td>
            </tr>`,
            )
            .join('')}
        </tbody>
      </table>
    </section>`;

  el.addEventListener('click', (e) => {
    const nav = e.target.closest('[data-month-nav]');
    if (nav) replaceRoute(`#/stats?m=${addMonths(month, Number(nav.dataset.monthNav))}`);
  });

  // 圖表要等元素放進畫面、量得到寬度之後才畫
  return () => {
    const draw = () => {
      const donut = el.querySelector('[data-chart="donut"]');
      if (donut) {
        drawDonut(donut, groups.map((g) => ({ value: g.total, color: colorOf(g.categoryId) })), summary.expense);
      }
      drawBars(el.querySelector('[data-chart="bars"]'), trend);
    };
    draw();
    const redraw = () => (el.isConnected ? draw() : cleanup());
    const scheme = matchMedia('(prefers-color-scheme: dark)');
    const cleanup = () => {
      window.removeEventListener('resize', redraw);
      scheme.removeEventListener('change', redraw);
    };
    window.addEventListener('resize', redraw);
    scheme.addEventListener('change', redraw);
  };
}
