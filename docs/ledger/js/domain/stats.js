// 統計、分組、篩選。全部是純函式，輸入一般陣列、輸出新陣列。
import { addMonths, monthOf, monthRange } from './format.js';

/** 依日期新到舊排序；同一天依建立時間新到舊 */
export function sortTransactions(txs) {
  return [...txs].sort((a, b) =>
    a.date === b.date ? b.createdAt - a.createdAt : a.date < b.date ? 1 : -1,
  );
}

export function summarize(txs) {
  let income = 0;
  let expense = 0;
  for (const t of txs) {
    if (t.type === 'income') income += t.amount;
    else expense += t.amount;
  }
  return { income, expense, balance: income - expense };
}

/** 依日期分組（新到舊），每組附當天收入／支出小計 */
export function groupByDate(txs) {
  const groups = [];
  let cur = null;
  for (const t of sortTransactions(txs)) {
    if (!cur || cur.date !== t.date) {
      cur = { date: t.date, items: [], income: 0, expense: 0 };
      groups.push(cur);
    }
    cur.items.push(t);
    cur[t.type] += t.amount;
  }
  return groups;
}

/** 某一類型（預設支出）依類別加總，金額大到小，附佔比 */
export function groupByCategory(txs, categories, type = 'expense') {
  const byId = new Map();
  let total = 0;
  for (const t of txs) {
    if (t.type !== type) continue;
    total += t.amount;
    const g = byId.get(t.categoryId) ?? { categoryId: t.categoryId, total: 0, count: 0 };
    g.total += t.amount;
    g.count += 1;
    byId.set(t.categoryId, g);
  }
  const catMap = new Map(categories.map((c) => [c.id, c]));
  return [...byId.values()]
    .map((g) => ({ ...g, category: catMap.get(g.categoryId) ?? null, ratio: total ? g.total / total : 0 }))
    .sort((a, b) => b.total - a.total);
}

/** 以 endMonth 為最後一個月，往前共 n 個月的收支 */
export function monthlyTrend(txs, endMonth, n = 6) {
  const months = Array.from({ length: n }, (_, i) => addMonths(endMonth, i - n + 1));
  const rows = new Map(months.map((m) => [m, { month: m, income: 0, expense: 0 }]));
  for (const t of txs) {
    const row = rows.get(monthOf(t.date));
    if (row) row[t.type] += t.amount;
  }
  return months.map((m) => {
    const r = rows.get(m);
    return { ...r, balance: r.income - r.expense };
  });
}

/** 依類別與備註關鍵字篩選（關鍵字不分大小寫） */
export function filterTransactions(txs, { categoryId = '', keyword = '' } = {}) {
  const kw = keyword.trim().toLowerCase();
  return txs.filter(
    (t) => (!categoryId || t.categoryId === categoryId) && (!kw || t.note.toLowerCase().includes(kw)),
  );
}

/** 每個類別各有幾筆紀錄 */
export function countByCategory(txs) {
  const counts = new Map();
  for (const t of txs) counts.set(t.categoryId, (counts.get(t.categoryId) ?? 0) + 1);
  return counts;
}

/** 這個月到今天為止過了幾天（含今天）；過去的月份是整個月，未來的月份是 0 */
export function daysElapsed(month, today) {
  const cur = monthOf(today);
  if (month > cur) return 0;
  if (month < cur) return Number(monthRange(month)[1].slice(8));
  return Number(today.slice(8));
}

/** 和前一期相比的變化比例；前一期是 0 時無法比較，回傳 null */
export const changeRatio = (cur, prev) => (prev ? (cur - prev) / prev : null);

/** 某一天的支出合計 */
export const spentOn = (txs, date) =>
  txs.reduce((sum, t) => (t.type === 'expense' && t.date === date ? sum + t.amount : sum), 0);

/** 某個月 1 號到 day 號（含）的支出合計；day 超過該月天數就算到月底 */
export function expenseThroughDay(txs, month, day) {
  const last = `${month}-${String(day).padStart(2, '0')}`;
  return txs.reduce(
    (sum, t) => (t.type === 'expense' && t.date >= `${month}-01` && t.date <= last ? sum + t.amount : sum),
    0,
  );
}
