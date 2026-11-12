// 首頁：本月收支摘要＋最近紀錄。
import { listByMonth, listRecent } from '../services/ledger.js';
import { listCategories } from '../services/categories.js';
import { getBudgets } from '../services/budget.js';
import { budgetStatus } from '../domain/budget.js';
import { formatMonth, monthOf, todayStr } from '../domain/format.js';
import { groupByDate, summarize } from '../domain/stats.js';
import { budgetCard, catMap, emptyState, groupedList, summaryCards } from './components.js';

export async function render(el) {
  const today = todayStr();
  const month = monthOf(today);
  const [monthTxs, recent, cats, budgets] = await Promise.all([
    listByMonth(month),
    listRecent(20),
    listCategories({ includeHidden: true }),
    getBudgets(),
  ]);

  el.innerHTML = `
    <header class="page-head">
      <h1>${formatMonth(month)}</h1>
    </header>
    ${summaryCards(summarize(monthTxs))}
    ${
      budgets.length
        ? budgetCard(budgetStatus(monthTxs, budgets, cats, month, today))
        : recent.length
          ? '<a class="card link-card" href="#/budget"><span>🎯 設定每月預算，隨時知道還能花多少</span><span aria-hidden="true">›</span></a>'
          : ''
    }
    <section class="card">
      <div class="section-head">
        <h2>最近紀錄</h2>
        ${recent.length ? '<a href="#/list">看全部 ›</a>' : ''}
      </div>
      ${recent.length ? groupedList(groupByDate(recent), catMap(cats)) : emptyState('還沒有任何紀錄，按右下角的「＋」記第一筆吧')}
    </section>`;
}
