// 備份：匯出／匯入 JSON、匯出 CSV。
import * as db from '../storage/db.js';
import { validateBackup } from '../domain/validate.js';
import { buildCSV } from '../domain/csv.js';
import { todayStr } from '../domain/format.js';

export const BACKUP_VERSION = 2; // v2 起包含預算與固定收支；匯入仍接受 v1

async function loadAll() {
  const lists = await Promise.all(db.DATA_STORES.map((name) => db.getAll(name)));
  return Object.fromEntries(db.DATA_STORES.map((name, i) => [name, lists[i]]));
}

function download(filename, content, mime) {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function exportJSON() {
  const data = await loadAll();
  const payload = { app: 'ledger', version: BACKUP_VERSION, exportedAt: new Date().toISOString(), ...data };
  download(`記帳本備份-${todayStr()}.json`, JSON.stringify(payload, null, 2), 'application/json');
  await db.put('meta', { key: 'lastExportAt', value: Date.now() });
  return data.transactions.length;
}

export async function exportCSV() {
  const { categories, transactions } = await loadAll();
  download(`記帳本-${todayStr()}.csv`, buildCSV(transactions, categories), 'text/csv;charset=utf-8');
  return transactions.length;
}

/** 讀取備份檔並「取代」目前全部資料 */
export async function importJSON(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error('檔案不是有效的 JSON');
  }
  const v = validateBackup(data);
  if (!v.ok) throw new Error(v.error);
  await db.replaceAll(v.value);
  return {
    categories: v.value.categories.length,
    transactions: v.value.transactions.length,
    recurring: v.value.recurring.length,
  };
}

export async function getLastExportAt() {
  return (await db.get('meta', 'lastExportAt'))?.value ?? null;
}
