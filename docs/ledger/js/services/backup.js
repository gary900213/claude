// 備份：匯出／匯入 JSON、匯出 CSV。
import * as db from '../storage/db.js';
import { validateBackup } from '../domain/validate.js';
import { buildCSV } from '../domain/csv.js';
import { todayStr } from '../domain/format.js';
import { PREVIEW } from '../config.js';

export const BACKUP_VERSION = 2; // v2 起包含預算與固定收支；匯入仍接受 v1

async function loadAll() {
  const lists = await Promise.all(db.DATA_STORES.map((name) => db.getAll(name)));
  return Object.fromEntries(db.DATA_STORES.map((name, i) => [name, lists[i]]));
}

function download(filename, content, mime) {
  if (PREVIEW) throw new Error('預覽頁不能下載檔案，正式網站上就可以匯出');
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

const BACKUP_EVERY_DAYS = 30;
const MIN_RECORDS = 20;

/** 該提醒備份了嗎：紀錄夠多，而且超過 30 天沒備份（按「稍後」會延後 7 天） */
export async function backupDue(count) {
  if (PREVIEW || count < MIN_RECORDS) return null;
  const [last, snooze] = await Promise.all([getLastExportAt(), db.get('meta', 'backupSnoozeUntil')]);
  const now = Date.now();
  if ((snooze?.value ?? 0) > now) return null;
  if (last && now - last < BACKUP_EVERY_DAYS * 86400e3) return null;
  return { days: last ? Math.floor((now - last) / 86400e3) : null };
}

export const snoozeBackup = () => db.put('meta', { key: 'backupSnoozeUntil', value: Date.now() + 7 * 86400e3 });
