// 每月預算的讀取與儲存。
import * as db from '../storage/db.js';
import { parseBudgetAmount, ValidationError } from '../domain/validate.js';

export const getBudgets = () => db.getAll('budgets');

/**
 * 整份預算一起儲存。input：{ [id]: 金額字串 }，id 是 'total' 或支出類別 id。
 * 空白或 0 代表不設定。
 */
export async function saveBudgets(input) {
  const errors = {};
  const rows = [];
  for (const [id, raw] of Object.entries(input)) {
    const r = parseBudgetAmount(raw);
    if (!r.ok) errors[id] = r.error;
    else if (r.amount > 0) rows.push({ id, amount: r.amount });
  }
  if (Object.keys(errors).length) throw new ValidationError(errors);
  await db.replaceStore('budgets', rows);
  return rows;
}
