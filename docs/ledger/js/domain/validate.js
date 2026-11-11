// 輸入驗證。全部是純函式；驗證失敗時回傳每個欄位的錯誤訊息。

export const MAX_AMOUNT = 999_999_999;
export const MAX_NOTE = 100;
export const MAX_CATEGORY_NAME = 8;
export const TYPES = ['expense', 'income'];

export class ValidationError extends Error {
  constructor(errors) {
    super(Object.values(errors)[0] || '資料格式錯誤');
    this.errors = errors;
  }
}

export function isValidDate(s) {
  if (typeof s !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const [y, m, d] = s.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d;
}

/** "1,200" → 1200；不是正整數字串就回傳 NaN */
export function parseAmount(v) {
  if (typeof v === 'number') return v;
  const s = String(v ?? '').replace(/[,\s]/g, '');
  return /^\d+$/.test(s) ? Number(s) : NaN;
}

/** 計算字數，emoji 組合字算一個 */
export function charCount(s) {
  if (typeof Intl !== 'undefined' && Intl.Segmenter) {
    return [...new Intl.Segmenter('zh-Hant', { granularity: 'grapheme' }).segment(s)].length;
  }
  return [...s].length;
}

export function validateTransaction(input, categories) {
  const errors = {};
  const { type, categoryId, date } = input;

  if (!TYPES.includes(type)) errors.type = '請選擇支出或收入';

  const amount = parseAmount(input.amount);
  if (!Number.isInteger(amount) || amount <= 0) errors.amount = '請輸入大於 0 的整數金額';
  else if (amount > MAX_AMOUNT) errors.amount = '金額太大了';

  const cat = categories.find((c) => c.id === categoryId);
  if (!cat) errors.categoryId = '請選擇類別';
  else if (cat.type !== type) errors.categoryId = '類別和收支類型不符';

  if (!isValidDate(date)) errors.date = '請選擇正確的日期';

  const note = String(input.note ?? '').trim();
  if (charCount(note) > MAX_NOTE) errors.note = `備註最多 ${MAX_NOTE} 個字`;

  const ok = Object.keys(errors).length === 0;
  return { ok, errors, value: ok ? { type, amount, categoryId, date, note } : null };
}

export function validateCategory(input, categories, selfId = null) {
  const errors = {};
  const name = String(input.name ?? '').trim();
  const icon = String(input.icon ?? '').trim();

  if (!TYPES.includes(input.type)) errors.type = '類型錯誤';
  if (!name) errors.name = '請輸入名稱';
  else if (charCount(name) > MAX_CATEGORY_NAME) errors.name = `名稱最多 ${MAX_CATEGORY_NAME} 個字`;
  else if (categories.some((c) => c.id !== selfId && c.type === input.type && c.name === name)) {
    errors.name = '已經有同名的類別';
  }

  if (!icon) errors.icon = '請選一個圖示';
  else if (charCount(icon) > 2) errors.icon = '圖示請用 1 個 emoji';

  const ok = Object.keys(errors).length === 0;
  return { ok, errors, value: ok ? { type: input.type, name, icon } : null };
}

/**
 * 檢查備份檔內容。成功時回傳整理過的資料（只保留認得的欄位）。
 */
export function validateBackup(data) {
  const fail = (error) => ({ ok: false, error, value: null });

  if (!data || typeof data !== 'object' || data.app !== 'ledger') return fail('這不是記帳本的備份檔');
  if (!Array.isArray(data.categories) || !Array.isArray(data.transactions)) return fail('備份檔缺少資料');

  const categories = [];
  const ids = new Set();
  for (const [i, c] of data.categories.entries()) {
    if (!c || typeof c.id !== 'string' || !c.id || ids.has(c.id)) return fail(`第 ${i + 1} 個類別的 id 有問題`);
    const v = validateCategory(c, categories);
    if (!v.ok) return fail(`類別「${c.name ?? i + 1}」：${Object.values(v.errors)[0]}`);
    ids.add(c.id);
    categories.push({
      id: c.id,
      ...v.value,
      order: Number.isFinite(c.order) ? c.order : i,
      hidden: Boolean(c.hidden),
      builtin: Boolean(c.builtin),
    });
  }

  const transactions = [];
  const txIds = new Set();
  for (const [i, t] of data.transactions.entries()) {
    if (!t || typeof t.id !== 'string' || !t.id || txIds.has(t.id)) return fail(`第 ${i + 1} 筆紀錄的 id 有問題`);
    const v = validateTransaction(t, categories);
    if (!v.ok) return fail(`第 ${i + 1} 筆紀錄（${t.date ?? '無日期'}）：${Object.values(v.errors)[0]}`);
    txIds.add(t.id);
    const createdAt = Number.isFinite(t.createdAt) ? t.createdAt : 0;
    transactions.push({
      id: t.id,
      ...v.value,
      createdAt,
      updatedAt: Number.isFinite(t.updatedAt) ? t.updatedAt : createdAt,
    });
  }

  return { ok: true, error: null, value: { categories, transactions } };
}
