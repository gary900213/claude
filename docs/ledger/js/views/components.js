// 共用的畫面片段（回傳 HTML 字串）與小工具。
import { formatAmount, formatDay, formatMonth, formatSigned } from '../domain/format.js';

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
        <span class="tx-cat">${esc(cat?.name ?? '未知類別')}</span>
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
