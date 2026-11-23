// 固定收支：每月固定日期自動產生紀錄。純函式。
//
// 規則格式：
// { id, type, amount, categoryId, note,
//   day: 1~31（該月沒有這天就用月底），
//   startMonth: 'YYYY-MM'（從哪個月開始），
//   lastGenerated: 'YYYY-MM' | null（已經產生到哪個月），
//   active: true/false }
import { addMonths, monthOf, monthRange, pad2 } from './format.js';

/** 最多往回補幾個月，避免開始月份設太早時一口氣產生太多筆 */
export const MAX_CATCH_UP = 24;

/** 某個月的扣款日；31 號在 2 月會變成 2/28（或 2/29） */
export function occurrenceDate(month, day) {
  const lastDay = Number(monthRange(month)[1].slice(8));
  return `${month}-${pad2(Math.min(day, lastDay))}`;
}

/** 下一個要產生的月份（只往回補最近 MAX_CATCH_UP 個月） */
function firstPendingMonth(rule, today) {
  const next = rule.lastGenerated ? addMonths(rule.lastGenerated, 1) : rule.startMonth;
  const earliest = addMonths(monthOf(today), -(MAX_CATCH_UP - 1));
  return next > earliest ? next : earliest;
}

/** 到 today（含）為止，還沒產生的日期清單（舊到新） */
export function dueDates(rule, today) {
  if (!rule.active) return [];
  const out = [];
  const cur = monthOf(today);
  for (let m = firstPendingMonth(rule, today); m <= cur; m = addMonths(m, 1)) {
    const date = occurrenceDate(m, rule.day);
    if (date > today) break;
    out.push(date);
  }
  return out;
}

/** 下一次會記入的日期（停用時為 null） */
export function nextDate(rule, today) {
  if (!rule.active) return null;
  return dueDates(rule, today)[0] ?? occurrenceDate(firstPendingMonth(rule, today), rule.day);
}

/**
 * 依規則產生紀錄。回傳 { transactions, rule }，rule 是更新過 lastGenerated 的新物件；
 * 沒有要產生的就回傳空陣列和原本的 rule。
 */
export function generateFor(rule, today, { now = Date.now(), uid }) {
  const dates = dueDates(rule, today);
  if (!dates.length) return { transactions: [], rule };
  const transactions = dates.map((date, i) => ({
    id: uid(),
    type: rule.type,
    amount: rule.amount,
    categoryId: rule.categoryId,
    date,
    note: rule.note,
    recurringId: rule.id,
    createdAt: now + i,
    updatedAt: now + i,
  }));
  return { transactions, rule: { ...rule, lastGenerated: monthOf(dates.at(-1)) } };
}

/** 建議的開始月份：這個月的日期已經過了就從下個月開始，避免和手動記過的重複 */
export function suggestStartMonth(day, today) {
  const cur = monthOf(today);
  return occurrenceDate(cur, day) < today ? addMonths(cur, 1) : cur;
}
