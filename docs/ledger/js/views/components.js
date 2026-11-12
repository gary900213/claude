// 共用的畫面片段（回傳 HTML 字串）與小工具。
import { formatAmount, formatDay, formatMonth, formatSigned } from '../domain/format.js';
import { budgetLevel } from '../domain/budget.js';

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

/** 使用者輸入的文字放進 HTML 前一定要經過 esc */
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ESC[c]);

export const catMap = (cats) => new Map(cats.map((c) => [c.id, c]));

export function summaryCards({ income, expense, balance }) {
  return `
    <div class="summary">
      <div class="summary-item"><span>收入</span><strong class="income">${formatAmount(income)}</strong></div>
      <div class="summary-item"><span>支出</span><strong class="expense">${formatAmount(expense)}</strong></div>
      <div class="summary-item"><span>結餘</span><strong class="${balance < 0 ? 'expense' : ''}">${formatSigned(balance)}</strong></div>
    </div>`;
}

export function monthSwitcher(month) {
  return `
    <div class="month-switcher">
      <button class="icon-btn" type="button" data-month-nav="-1" aria-label="上個月">‹</button>
      <h1>${formatMonth(month)}</h1>
      <button class="icon-btn" type="button" data-month-nav="1" aria-label="下個月">›</button>
    </div>`;
}

export function txItem(tx, cat) {
  const sign = tx.type === 'expense' ? '-' : '+';
  return `
    <li><a class="tx" href="#/edit/${encodeURIComponent(tx.id)}">
      <span class="tx-icon" aria-hidden="true">${esc(cat?.icon ?? '❔')}</span>
      <span class="tx-main">
        <span class="tx-cat">${esc(cat?.name ?? '未知類別')}${tx.recurringId ? '<span class="badge">固定</span>' : ''}</span>
        ${tx.note ? `<span class="tx-note">${esc(tx.note)}</span>` : ''}
      </span>
      <span class="tx-amt ${tx.type}">${sign}${formatAmount(tx.amount)}</span>
    </a></li>`;
}

/** 依日期分組的紀錄列表；showTotals 時每天顯示小計 */
export function groupedList(groups, cats, { showTotals = false } = {}) {
  return groups
    .map(
      (g) => `
      <section class="day">
        <h3 class="day-head">
          <span>${formatDay(g.date)}</span>
          ${showTotals ? `<span class="day-total">${g.income ? `<span class="income">+${formatAmount(g.income)}</span>` : ''}${g.expense ? `<span class="expense">-${formatAmount(g.expense)}</span>` : ''}</span>` : ''}
        </h3>
        <ul class="tx-list">${g.items.map((t) => txItem(t, cats.get(t.categoryId))).join('')}</ul>
      </section>`,
    )
    .join('');
}

export const emptyState = (text) => `<p class="empty">${esc(text)}</p>`;

let toastTimer;
export function toast(message) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
}

/** 類別顏色：同一個類別在每張圖都是同一個顏色 */
const PALETTE = ['#f97316', '#3b82f6', '#a855f7', '#ec4899', '#64748b', '#14b8a6', '#eab308', '#ef4444', '#22c55e', '#6366f1'];
export function categoryColors(cats) {
  const colors = new Map();
  for (const type of ['expense', 'income']) {
    cats
      .filter((c) => c.type === type)
      .sort((a, b) => a.order - b.order)
      .forEach((c, i) => colors.set(c.id, PALETTE[i % PALETTE.length]));
  }
  return colors;
}

/** 類別選擇格（記一筆、固定收支共用） */
export function categoryGrid(cats, selectedId) {
  if (!cats.length) return '<p class="muted">沒有可用的類別，請到「設定」新增</p>';
  return cats
    .map(
      (c) => `
      <button type="button" class="cat" role="radio" data-cat="${esc(c.id)}" aria-checked="${c.id === selectedId}">
        <span class="cat-icon" aria-hidden="true">${esc(c.icon)}</span>
        <span class="cat-name">${esc(c.name)}</span>
      </button>`,
    )
    .join('');
}

export function progressBar(ratio, label = '') {
  const pct = Math.round(ratio * 100);
  return `<div class="progress ${budgetLevel(ratio)}" role="progressbar" aria-label="${esc(label)}"
    aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.min(pct, 100)}"><i style="width:${Math.min(pct, 100)}%"></i></div>`;
}

/** 預算卡片。status 來自 domain/budget.js 的 budgetStatus() */
export function budgetCard(status, { editLink = true } = {}) {
  const { total, categories } = status;
  if (!total && !categories.length) return '';
  const totalHtml = total
    ? `
      <div class="budget-total">
        <div class="budget-line"><span>總預算</span><strong>${formatAmount(total.spent)} / ${formatAmount(total.budget)}</strong></div>
        ${progressBar(total.ratio, '總預算使用比例')}
        <p class="budget-note ${budgetLevel(total.ratio)}">${
          total.over
            ? `已超支 ${formatAmount(-total.remaining)}`
            : `還可以花 ${formatAmount(total.remaining)}${total.daysLeft ? `，接下來 ${total.daysLeft} 天平均每天 ${formatAmount(total.perDay)}` : ''}`
        }</p>
      </div>`
    : '';
  const rows = categories
    .map(
      (r) => `
      <li>
        <div class="budget-line">
          <span>${esc(r.category.icon)} ${esc(r.category.name)}${r.over ? '<span class="badge over">超支</span>' : ''}</span>
          <span class="muted">${formatAmount(r.spent)} / ${formatAmount(r.budget)}</span>
        </div>
        ${progressBar(r.ratio, `${r.category.name}預算使用比例`)}
      </li>`,
    )
    .join('');
  return `
    <section class="card">
      <div class="section-head"><h2>本月預算</h2>${editLink ? '<a href="#/budget">調整 ›</a>' : ''}</div>
      ${totalHtml}
      ${rows ? `<ul class="budget-rows">${rows}</ul>` : ''}
    </section>`;
}

/** 子頁面的頁首（有返回鍵） */
export const subHeader = (title) => `
  <header class="page-head with-back">
    <button class="icon-btn" type="button" data-act="back" aria-label="返回">‹</button>
    <h1>${esc(title)}</h1>
  </header>`;
