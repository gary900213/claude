// 產生 CSV（Excel 可直接開啟）。純函式。
import { sortTransactions } from './stats.js';

function cell(v) {
  let s = String(v ?? '');
  // 避免 Excel 把 =、+、-、@ 開頭的文字當成公式執行
  if (typeof v === 'string' && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function buildCSV(transactions, categories) {
  const catMap = new Map(categories.map((c) => [c.id, c]));
  const rows = [['日期', '類型', '類別', '金額', '備註']];
  for (const t of sortTransactions(transactions).reverse()) {
    rows.push([
      t.date,
      t.type === 'expense' ? '支出' : '收入',
      catMap.get(t.categoryId)?.name ?? '（未知類別）',
      t.amount,
      t.note,
    ]);
  }
  // 開頭加 BOM，Excel 才會用 UTF-8 讀取中文
  return `﻿${rows.map((r) => r.map(cell).join(',')).join('\r\n')}\r\n`;
}
