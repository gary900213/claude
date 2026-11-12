// 類別管理：新增、改名、排序、隱藏、刪除。
import * as db from '../storage/db.js';
import { DEFAULT_CATEGORIES } from '../defaults.js';
import { validateCategory, ValidationError } from '../domain/validate.js';

export const SCHEMA_VERSION = 1;

export const ensureDefaults = () => db.initOnce(DEFAULT_CATEGORIES, SCHEMA_VERSION);

const byOrder = (a, b) => a.order - b.order;

export async function listCategories({ type, includeHidden = false } = {}) {
  let cats = await db.getAll('categories');
  if (type) cats = cats.filter((c) => c.type === type);
  if (!includeHidden) cats = cats.filter((c) => !c.hidden);
  return cats.sort(byOrder);
}

export async function addCategory(input) {
  const all = await db.getAll('categories');
  const v = validateCategory(input, all);
  if (!v.ok) throw new ValidationError(v.errors);
  const order = all.reduce((max, c) => Math.max(max, c.order), -1) + 1;
  const cat = { id: db.uid(), ...v.value, order, hidden: false, builtin: false };
  await db.put('categories', cat);
  return cat;
}

async function find(all, id) {
  const cur = all.find((c) => c.id === id);
  if (!cur) throw new Error('找不到這個類別');
  return cur;
}

export async function updateCategory(id, { name, icon }) {
  const all = await db.getAll('categories');
  const cur = await find(all, id);
  const v = validateCategory({ type: cur.type, name, icon }, all, id);
  if (!v.ok) throw new ValidationError(v.errors);
  return db.put('categories', { ...cur, name: v.value.name, icon: v.value.icon });
}

export async function setHidden(id, hidden) {
  const cur = await find(await db.getAll('categories'), id);
  return db.put('categories', { ...cur, hidden });
}

/** dir = -1 往上、+1 往下，和同類型相鄰的類別交換順序 */
export async function moveCategory(id, dir) {
  const all = await db.getAll('categories');
  const cur = await find(all, id);
  const list = all.filter((c) => c.type === cur.type).sort(byOrder);
  const i = list.findIndex((c) => c.id === id);
  const other = list[i + dir];
  if (!other) return;
  await db.putMany('categories', [
    { ...cur, order: other.order },
    { ...other, order: cur.order },
  ]);
}

/** 只能刪除沒有紀錄的類別；有紀錄的請改用隱藏 */
export async function deleteCategory(id) {
  const n = await db.countByIndex('transactions', 'categoryId', id);
  if (n > 0) throw new Error(`這個類別還有 ${n} 筆紀錄，不能刪除，可以改成隱藏`);
  const rules = (await db.getAll('recurring')).filter((r) => r.categoryId === id);
  if (rules.length) throw new Error(`有 ${rules.length} 個固定收支使用這個類別，請先修改或刪除`);
  await db.remove('categories', id);
  await db.remove('budgets', id);
}
