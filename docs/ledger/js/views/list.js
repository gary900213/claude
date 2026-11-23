// 明細：依月份瀏覽，可篩類別、搜尋備註；也可以搜尋全部月份。
import { getAllTransactions, listByMonth } from '../services/ledger.js';
import { listCategories } from '../services/categories.js';
import { addMonths, isMonthStr, monthOf, todayStr } from '../domain/format.js';
import { filterTransactions, groupByDate, summarize } from '../domain/stats.js';
import { replaceRoute } from '../router.js';
import { catMap, emptyState, esc, groupedList, monthSwitcher, summaryCards } from './components.js';

// 篩選條件在切換頁面時保留
const filters = { categoryId: '', keyword: '', allMonths: false };

export async function render(el, ctx) {
  const month = isMonthStr(ctx.param) ? ctx.param : monthOf(todayStr());
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
      <label class="switch-row all-months"><input type="checkbox" data-f="all" ${filters.allMonths ? 'checked' : ''}>
        <span>搜尋全部月份</span></label>
    </div>
    <div data-summary></div>
    <div data-list></div>`;

  const summaryEl = el.querySelector('[data-summary]');
  const listEl = el.querySelector('[data-list]');

  let all = null; // 全部月份的紀錄，第一次需要時才讀
  let token = 0;
  const update = async () => {
    const mine = ++token;
    const searching = filters.allMonths && (filters.keyword.trim() || filters.categoryId);
    el.classList.toggle('all-months-on', Boolean(searching));
    if (searching && !all) all = await getAllTransactions();
    if (mine !== token) return; // 打字很快時只顯示最後一次的結果
    const source = searching ? all : txs;
    const shown = filterTransactions(source, filters);
    summaryEl.innerHTML =
      (searching ? `<p class="hint">全部月份共找到 <b>${shown.length}</b> 筆</p>` : '') + summaryCards(summarize(shown));
    listEl.innerHTML = shown.length
      ? `<div class="card">${groupedList(groupByDate(shown), map, { showTotals: true, showYear: Boolean(searching) })}</div>`
      : emptyState(
          searching
            ? '全部月份都沒有符合條件的紀錄'
            : txs.length
              ? '沒有符合條件的紀錄'
              : '這個月還沒有紀錄',
        );
  };

  el.querySelector('[data-f="cat"]').addEventListener('change', (e) => {
    filters.categoryId = e.target.value;
    update();
  });
  el.querySelector('[data-f="kw"]').addEventListener('input', (e) => {
    filters.keyword = e.target.value;
    update();
  });
  el.querySelector('[data-f="all"]').addEventListener('change', (e) => {
    filters.allMonths = e.target.checked;
    update();
  });
  el.addEventListener('click', (e) => {
    const nav = e.target.closest('[data-month-nav]');
    if (nav) replaceRoute(`#list-${addMonths(month, Number(nav.dataset.monthNav))}`);
  });

  update();
}
