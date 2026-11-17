// Apple Pay 收件匣：從 GitHub Gist 留言或文字檔匯入 iPhone 捷徑記下的交易。
//
// meta 資料：
//   inbox            { gistId, lastPage, lastSyncAt, lastError }
//   inboxSeen        [key, ...]   已經處理過的交易（避免重複記帳），只留最近 SEEN_LIMIT 筆
//   inboxPending     [item, ...]  沒帶到金額、等你補記的交易
//   merchantCategory { 商店鍵: 類別 id }  你改過的分類，下次同一家店自動套用
import * as db from '../storage/db.js';
import { guessCategory, merchantKey, parseInboxItem, parseInboxText, toTransaction } from '../domain/inbox.js';
import { todayStr } from '../domain/format.js';

const SEEN_LIMIT = 5000;
const metaValue = async (key, fallback) => (await db.get('meta', key))?.value ?? fallback;

export const getInbox = () => metaValue('inbox', {});
export const getPending = () => metaValue('inboxPending', []);
export const getLearned = () => metaValue('merchantCategory', {});

/** 從使用者貼上的 Gist 網址或 ID 取出 ID */
export function extractGistId(input) {
  const m = String(input ?? '').trim().match(/([0-9a-f]{20,40})\/?(#.*)?$/i);
  return m ? m[1].toLowerCase() : null;
}

export async function saveGistId(input) {
  const raw = String(input ?? '').trim();
  const gistId = raw ? extractGistId(raw) : '';
  if (gistId === null) throw new Error('看不懂這個 Gist 網址，請貼上像 https://gist.github.com/帳號/一串英數字 的網址');
  const cur = await getInbox();
  await db.put('meta', { key: 'inbox', value: { ...cur, gistId, lastPage: gistId === cur.gistId ? cur.lastPage : 1, lastError: null } });
  return gistId;
}

/**
 * 匯入一批交易（同一個資料庫交易內完成，不會重複記帳）。
 * 回傳 { added, pending, skipped }：新增幾筆、幾筆缺金額待補、幾筆之前就處理過。
 */
export function importItems(items) {
  const today = todayStr();
  return db.run(['transactions', 'categories', 'meta'], 'readwrite', (t) => {
    const result = { added: 0, pending: 0, skipped: 0 };
    const meta = t.objectStore('meta');
    const cats = t.objectStore('categories').getAll();
    const seenReq = meta.get('inboxSeen');
    const learnedReq = meta.get('merchantCategory');
    const pendingReq = meta.get('inboxPending');
    // 同一個交易裡的 request 依序完成，最後一個完成時其他的都已經有結果
    pendingReq.onsuccess = () => {
      const seenList = seenReq.result?.value ?? [];
      const seen = new Set(seenList);
      const learned = learnedReq.result?.value ?? {};
      const pending = pendingReq.result?.value ?? [];
      const txs = t.objectStore('transactions');
      let now = Date.now();
      for (const item of items) {
        if (!item || seen.has(item.key)) {
          result.skipped += 1;
          continue;
        }
        seen.add(item.key);
        seenList.push(item.key);
        if (!item.amount) {
          pending.push(item);
          result.pending += 1;
          continue;
        }
        const categoryId = guessCategory(item.merchant, learned, cats.result);
        if (!categoryId) {
          pending.push(item);
          result.pending += 1;
          continue;
        }
        txs.put(toTransaction(item, categoryId, { today, now: now++, uid: db.uid }));
        result.added += 1;
      }
      meta.put({ key: 'inboxSeen', value: seenList.slice(-SEEN_LIMIT) });
      meta.put({ key: 'inboxPending', value: pending });
    };
    return result;
  });
}

export const importFileText = (text) => importItems(parseInboxText(text));

let syncing = null;

/**
 * 從 Gist 留言同步。每則留言是一筆交易；已經處理過的會跳過。
 * 沒設定 Gist 時回傳 null。
 */
export function syncGist({ fetchImpl = globalThis.fetch } = {}) {
  // 同時被呼叫多次（開啟 App、切回前景）時只跑一次
  if (!syncing) {
    syncing = doSync(fetchImpl).finally(() => {
      syncing = null;
    });
  }
  return syncing;
}

async function doSync(fetchImpl) {
  const inbox = await getInbox();
  if (!inbox.gistId) return null;
  const items = [];
  let page = inbox.lastPage || 1;
  try {
    for (;;) {
      const res = await fetchImpl(
        `https://api.github.com/gists/${inbox.gistId}/comments?per_page=100&page=${page}`,
        { headers: { Accept: 'application/vnd.github+json' }, cache: 'no-store' },
      );
      if (res.status === 404) throw new Error('找不到這個 Gist，請檢查網址');
      if (res.status === 403 || res.status === 429) throw new Error('GitHub 暫時限制查詢次數，請過一陣子再同步');
      if (!res.ok) throw new Error(`GitHub 回應錯誤（${res.status}）`);
      const comments = await res.json();
      for (const c of comments) {
        const item = parseInboxItem(String(c.body ?? ''), `g${c.id}`);
        if (item) {
          if (!item.date && c.created_at) item.date = toLocalDate(c.created_at);
          items.push(item);
        }
      }
      if (comments.length < 100) break;
      page += 1;
    }
  } catch (err) {
    const message = err instanceof TypeError ? '連不上 GitHub，請確認網路' : err.message;
    await db.put('meta', { key: 'inbox', value: { ...inbox, lastError: message, lastSyncAt: Date.now() } });
    throw new Error(message);
  }
  const result = await importItems(items);
  await db.put('meta', { key: 'inbox', value: { ...inbox, lastPage: page, lastError: null, lastSyncAt: Date.now() } });
  return result;
}

/** ISO 時間（UTC）→ 手機當地的日期 */
function toLocalDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** 記住「這家店 → 這個類別」，之後同一家店（含其他分店）自動套用 */
export async function learnCategory(merchant, categoryId) {
  const key = merchantKey(merchant);
  if (!key) return;
  const learned = await getLearned();
  if (learned[key] === categoryId) return;
  await db.put('meta', { key: 'merchantCategory', value: { ...learned, [key]: categoryId } });
}

export async function forgetMerchant(key) {
  const learned = { ...(await getLearned()) };
  delete learned[key];
  await db.put('meta', { key: 'merchantCategory', value: learned });
}

export async function removePending(key) {
  const pending = (await getPending()).filter((p) => p.key !== key);
  await db.put('meta', { key: 'inboxPending', value: pending });
}
