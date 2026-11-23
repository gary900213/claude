// 每月預算的計算。純函式。
// 預算資料：[{ id: 'total' | <支出類別 id>, amount }]，每個月套用同一份。
import { monthOf, monthRange } from './format.js';

export const TOTAL_ID = 'total';

/** 這個月（從今天算起）還剩幾天，含今天；過去的月份為 0 */
export function daysLeftInMonth(month, today) {
  const last = monthRange(month)[1];
  const lastDay = Number(last.slice(8));
  const cur = monthOf(today);
  if (month < cur) return 0;
  if (month > cur) return lastDay;
  return lastDay - Number(today.slice(8)) + 1;
}

function line(budget, spent) {
  const remaining = budget - spent;
  return { budget, spent, remaining, ratio: budget ? spent / budget : 0, over: remaining < 0 };
}

/**
 * 計算某個月的預算使用狀況。
 * 回傳 { total, categories }：
 *   total：總預算（沒設定時為 null），附 perDay＝剩餘天數平均每天還能花多少
 *   categories：有設定預算的支出類別，使用比例高的排前面
 */
export function budgetStatus(monthTxs, budgets, categories, month, today) {
  const spentBy = new Map();
  let spentTotal = 0;
  for (const t of monthTxs) {
    if (t.type !== 'expense') continue;
    spentTotal += t.amount;
    spentBy.set(t.categoryId, (spentBy.get(t.categoryId) ?? 0) + t.amount);
  }

  const amounts = new Map(budgets.filter((b) => b.amount > 0).map((b) => [b.id, b.amount]));

  let total = null;
  if (amounts.has(TOTAL_ID)) {
    total = line(amounts.get(TOTAL_ID), spentTotal);
    const daysLeft = daysLeftInMonth(month, today);
    total.daysLeft = daysLeft;
    total.perDay = daysLeft && total.remaining > 0 ? Math.floor(total.remaining / daysLeft) : 0;
  }

  const rows = categories
    .filter((c) => c.type === 'expense' && amounts.has(c.id))
    .map((c) => ({ category: c, ...line(amounts.get(c.id), spentBy.get(c.id) ?? 0) }))
    .sort((a, b) => b.ratio - a.ratio);

  return { total, categories: rows };
}

/** 使用比例對應的狀態：ok／warn（80% 以上）／over（超過） */
export const budgetLevel = (ratio) => (ratio > 1 ? 'over' : ratio >= 0.8 ? 'warn' : 'ok');
