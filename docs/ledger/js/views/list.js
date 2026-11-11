// 明細：依月份瀏覽，可篩類別、搜尋備註。
import { listByMonth } from '../services/ledger.js';
import { listCategories } from '../services/categories.js';
import { addMonths, isMonthStr, monthOf, todayStr } from '../domain/format.js';
import { filterTransactions, groupByDate, summarize } from '../domain/stats.js';
import { replaceRoute } from '../router.js';
import { catMap, emptyState, esc, groupedList, monthSwitcher, summaryCards } from './components.js';

// 篩選條件在切換頁面時保留
const filters = { categoryId: '', keyword: '' };

export async function render(el, ctx) {
  const m = ctx.query.get('m');
  const month = isMonthStr(m) ? m : monthOf(todayStr());
  const [txs, cats] = await Promise.all([listByMonth(month), listCategories({ includeHidden: true })]);
  const map = catMap(cats);
  if (filters.categoryId && !map.has(filters.categoryId)) filters.categoryId = '';

  const options = (type, label) => `
    <optgroup label="${label}">
      ${cats
        .filter((c) => c.type === type)
        .map((c) => `<option value="${esc(c.id)}" ${c.id === filters.categoryId ? 'selected' : ''}>${esc(c.icon)} ${esc(c.name)}</option>`)
        .join('')}
    </optgroup>`;

  el.innerHTML = `
    <header class="page-head">${monthSwitcher(month)}</header>
    <div class="filters">
      <select data-f="cat" aria-label="類別篩選">
        <option value="">全部類別</option>
        ${options('expense', '支出')}${options('income', '收入')}
      </select>
      <input type="search" data-f="kw" placeholder="搜尋備註" aria-label="搜尋備註" value="${esc(filters.keyword)}">
    </div>
    <div data-summary></div>
    <div data-list></div>`;

  const summaryEl = el.querySelector('[data-summary]');
  const listEl = el.querySelector('[data-list]');

  const update = () => {
    const shown = filterTransactions(txs, filters);
    summaryEl.innerHTML = summaryCards(summarize(shown));
    listEl.innerHTML = shown.length
      ? `<div class="card">${groupedList(groupByDate(shown), map, { showTotals: true })}</div>`
      : emptyState(txs.length ? '沒有符合條件的紀錄' : '這個月還沒有紀錄');
  };

  el.querySelector('[data-f="cat"]').addEventListener('change', (e) => {
    filters.categoryId = e.target.value;
    update();
  });
  el.querySelector('[data-f="kw"]').addEventListener('input', (e) => {
    filters.keyword = e.target.value;
    update();
  });
  el.addEventListener('click', (e) => {
    const nav = e.target.closest('[data-month-nav]');
    if (nav) replaceRoute(`#/list?m=${addMonths(month, Number(nav.dataset.monthNav))}`);
  });

  update();
}
