// 收支紀錄的新增、修改、刪除、查詢。
import * as db from '../storage/db.js';
import { validateTransaction, ValidationError } from '../domain/validate.js';
import { monthRange } from '../domain/format.js';
import { sortTransactions } from '../domain/stats.js';

export async function addTransaction(input) {
  const v = validateTransaction(input, await db.getAll('categories'));
  if (!v.ok) throw new ValidationError(v.errors);
  const now = Date.now();
  const tx = { id: db.uid(), ...v.value, createdAt: now, updatedAt: now };
  await db.put('transactions', tx);
  return tx;
}

export async function updateTransaction(id, input) {
  const cur = await db.get('transactions', id);
  if (!cur) throw new Error('找不到這筆紀錄，可能已經被刪除');
  const v = validateTransaction(input, await db.getAll('categories'));
  if (!v.ok) throw new ValidationError(v.errors);
  const tx = { ...cur, ...v.value, updatedAt: Date.now() };
  await db.put('transactions', tx);
  return tx;
}

export const getTransaction = (id) => db.get('transactions', id);

export const deleteTransaction = (id) => db.remove('transactions', id);

export const getAllTransactions = () => db.getAll('transactions');

/** fromMonth 到 toMonth（含）之間的全部紀錄 */
export function listMonths(fromMonth, toMonth) {
  return db.getByRange('transactions', 'date', monthRange(fromMonth)[0], monthRange(toMonth)[1]);
}

export const listByMonth = (month) => listMonths(month, month);

export async function listRecent(limit = 20) {
  return sortTransactions(await db.getAll('transactions')).slice(0, limit);
}
