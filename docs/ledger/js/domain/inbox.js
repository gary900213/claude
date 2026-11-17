// Apple Pay 收件匣：解析 iPhone 捷徑送來的交易、依商店名稱猜類別。純函式。
//
// 捷徑送來的每一筆是一行 JSON，例如：
//   {"amount":"NT$1,234.00","merchant":"7-ELEVEN 信義門市","time":"2026-11-17 12:34"}
// 金額、時間的格式依手機設定而不同，這裡盡量寬鬆地解析。
import { isValidDate } from './validate.js';

/** "NT$1,234.50" → 1235；找不到數字回傳 null */
export function parseAmountText(v) {
  if (typeof v === 'number') return Number.isFinite(v) && v > 0 ? Math.round(v) : null;
  const s = String(v ?? '')
    .replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .replace(/，/g, ',');
  const m = s.match(/\d[\d,]*(\.\d+)?/);
  if (!m) return null;
  const n = Math.round(Number(m[0].replace(/,/g, '')));
  return n > 0 ? n : null;
}

/** 各種日期寫法 → "YYYY-MM-DD"；看不懂回傳 null */
export function parseDateText(v) {
  const m = String(v ?? '').match(/(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})/);
  if (!m) return null;
  const date = `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`;
  return isValidDate(date) ? date : null;
}

/** 字串的簡單雜湊，給沒有 id 的交易當作去重用的鍵 */
export function hashText(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return (h >>> 0).toString(36);
}

/**
 * 解析一筆交易。key 是去重用的唯一鍵（同一筆不會記兩次）。
 * 回傳 { key, amount, merchant, date }；amount 可能是 null（捷徑沒帶到金額）。
 */
export function parseInboxItem(raw, key) {
  let obj = raw;
  if (typeof raw === 'string') {
    const text = raw.trim();
    if (!text) return null;
    try {
      obj = JSON.parse(text);
    } catch {
      // 不是 JSON：整行當成「商店 金額」之類的文字，盡量抓出金額
      obj = { merchant: text.replace(/(NT)?\$?\s*\d[\d,.]*\s*(元|TWD)?/i, '').trim(), amount: text };
    }
  }
  if (!obj || typeof obj !== 'object') return null;
  const merchant = String(obj.merchant ?? obj.name ?? '').trim().slice(0, 100);
  return {
    key: key ?? String(obj.id ?? `h${hashText(JSON.stringify(obj))}`),
    amount: parseAmountText(obj.amount),
    merchant,
    date: parseDateText(obj.time ?? obj.date),
  };
}

/** 整個文字檔（每行一筆）→ 交易清單 */
export function parseInboxText(text) {
  return String(text ?? '')
    .split(/\r?\n/)
    .map((line) => parseInboxItem(line, line.trim() ? `f${hashText(line.trim())}` : null))
    .filter(Boolean);
}

/** 商店名稱的比對用鍵：小寫、去掉分店名稱（「7-ELEVEN 信義門市」→「7-eleven」） */
export function merchantKey(merchant) {
  return String(merchant ?? '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[\s\-－_(（][^\s\-－_(（]*(門市|分店|店|站)[)）]?$/, '')
    .trim();
}

// 依商店名稱的關鍵字猜類別。順序有意義：「uber eats」要先比對到餐飲，才不會被「uber」歸到交通。
export const DEFAULT_RULES = [
  ['food', ['uber eats', 'foodpanda', '7-eleven', '7-11', '統一超商', '全家', 'familymart', '萊爾富', 'hi-life',
    'ok超商', 'ok mart', '麥當勞', 'mcdonald', '星巴克', 'starbucks', '路易莎', 'louisa', '85度c', '摩斯', 'mos burger',
    '肯德基', 'kfc', '漢堡王', '必勝客', '達美樂', '全聯', 'pxmart', '家樂福', 'carrefour', '美廉社',
    '餐', '食', '飯', '麵', '咖啡', 'cafe', 'coffee', '茶', '飲', '烘焙', 'bakery', 'restaurant']],
  ['transport', ['中油', 'cpc', '台塑石油', '加油', '捷運', 'metro', '台鐵', '高鐵', 'thsr', 'uber', '計程車', 'taxi',
    'yoxi', '停車', 'parking', '悠遊卡', 'easycard', '一卡通', 'ipass', 'irent', 'gogoro', 'wemo']],
  ['housing', ['ikea', '特力屋', 'hola', '台電', '台灣電力', '自來水', '瓦斯', '中華電信', '台灣大哥大', '遠傳', '亞太電信']],
];

/**
 * 猜類別：先看使用者改過的（learned：{ 商店鍵: 類別 id }），再看預設關鍵字，最後用「其他支出」。
 * 只會回傳目前存在、沒有隱藏的支出類別。
 */
export function guessCategory(merchant, learned, categories) {
  const usable = new Set(categories.filter((c) => c.type === 'expense' && !c.hidden).map((c) => c.id));
  const key = merchantKey(merchant);
  const name = String(merchant ?? '').toLowerCase();
  if (key && learned?.[key] && usable.has(learned[key])) return learned[key];
  for (const [id, words] of DEFAULT_RULES) {
    if (usable.has(id) && words.some((w) => name.includes(w))) return id;
  }
  if (usable.has('other_expense')) return 'other_expense';
  return categories.find((c) => usable.has(c.id))?.id ?? null;
}

/** 收件匣的一筆 → 紀錄 */
export function toTransaction(item, categoryId, { today, now, uid }) {
  return {
    id: uid(),
    type: 'expense',
    amount: item.amount,
    categoryId,
    date: item.date ?? today,
    note: item.merchant || 'Apple Pay',
    source: 'applepay',
    createdAt: now,
    updatedAt: now,
  };
}
