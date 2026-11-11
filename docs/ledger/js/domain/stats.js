// 統計、分組、篩選。全部是純函式，輸入一般陣列、輸出新陣列。
import { addMonths, monthOf } from './format.js';

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
