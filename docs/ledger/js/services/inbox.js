// 刷卡自動記帳的收件匣。交易來源有三種：
//   1. Gmail：使用者部署的 Google Apps Script 讀取 Gmail 裡的刷卡通知（最省事，不用 iPhone 捷徑）
//   2. GitHub Gist：iPhone 捷徑把 Apple Pay 交易或刷卡簡訊留言到 Gist
//   3. 文字檔：iPhone 捷徑附加到 iCloud 雲碟的文字檔，手動匯入
//
// meta 資料：
//   inbox            { gistId, lastPage, gmailUrl, gmailKey, gmailSince, lastSyncAt, lastError }
//   inboxSeen        [key, ...]   已經處理過的交易（避免重複記帳），只留最近 SEEN_LIMIT 筆
//   inboxPending     [item, ...]  沒帶到金額、等你補記的交易
//   merchantCategory { 商店鍵: 類別 id }  你改過的分類，下次同一家店自動套用
import * as db from '../storage/db.js';
import { guessCategory, merchantKey, parseInboxItem, parseInboxText, toTransaction } from '../domain/inbox.js';
import { todayStr } from '../domain/format.js';
import { buildAppsScript, buildQuery, isAppsScriptUrl } from '../domain/gmail.js';

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

// ---------- Gmail（Google Apps Script） ----------

function randomKey() {
  const bytes = new Uint8Array(18);
  globalThis.crypto.getRandomValues(bytes);
  return [...bytes].map((b) => b.toString(36).padStart(2, '0')).join('').slice(0, 24);
}

/** 產生要貼到 Google Apps Script 的程式碼（同時記住 KEY 和寄件人設定） */
export async function generateGmailScript(senders) {
  const cur = await getInbox();
  const gmailKey = cur.gmailKey || randomKey();
  await setInbox({ gmailKey, gmailSenders: String(senders ?? '').trim() });
  return buildAppsScript({ key: gmailKey, query: buildQuery(senders) });
}

async function setInbox(patch) {
  const cur = await getInbox();
  const next = { ...cur, ...patch };
  await db.put('meta', { key: 'inbox', value: next });
  return next;
}

export async function saveGmailUrl(url) {
  const value = String(url ?? '').trim();
  if (value && !isAppsScriptUrl(value)) {
    throw new Error('網址不對：要用部署後的「網頁應用程式」網址，開頭是 https://script.google.com/macros/s/，結尾是 /exec');
  }
  const cur = await getInbox();
  if (value && !cur.gmailKey) throw new Error('請先按「產生程式碼」，把程式碼貼到 Google 再部署');
  // 第一次設定時從昨天開始抓，不會一口氣匯入一個月前的通知
  const d = new Date();
  d.setDate(d.getDate() - 1);
  d.setHours(0, 0, 0, 0);
  const gmailSince = value && value !== cur.gmailUrl ? d.getTime() : cur.gmailSince ?? d.getTime();
  return setInbox({ gmailUrl: value, gmailSince, gmailError: null });
}

async function doSyncGmail(fetchImpl) {
  const inbox = await getInbox();
  if (!inbox.gmailUrl) return null;
  let data;
  try {
    const url = `${inbox.gmailUrl}?key=${encodeURIComponent(inbox.gmailKey)}&since=${inbox.gmailSince ?? 0}`;
    // 不帶自訂標頭，瀏覽器才不會先送 OPTIONS 預檢（Apps Script 不支援）
    const res = await fetchImpl(url, { cache: 'no-store', redirect: 'follow' });
    if (!res.ok) throw new Error(`Google 回應錯誤（${res.status}）`);
    const text = await res.text();
    try {
      data = JSON.parse(text);
    } catch {
      throw new Error('讀不到腳本的回應：部署時「誰可以存取」要選「所有人」，而且要用最新的部署網址');
    }
    if (!data.ok) {
      throw new Error(data.error === 'key' ? '腳本的 KEY 和記帳本不一致，請重新產生程式碼並更新部署' : '腳本執行失敗');
    }
  } catch (err) {
    const message = err instanceof TypeError ? '連不上 Google，請確認網路' : err.message;
    await setInbox({ gmailError: message, lastSyncAt: Date.now() });
    throw new Error(message);
  }
  const items = [];
  let since = inbox.gmailSince ?? 0;
  for (const m of data.items ?? []) {
    since = Math.max(since, Number(m.date) || 0);
    const item = parseInboxItem(String(m.text ?? ''), `m${m.id}`);
    if (!item) continue;
    if (!item.date && m.date) item.date = toLocalDate(new Date(Number(m.date)).toISOString());
    items.push(item);
  }
  const result = await importItems(items);
  await setInbox({ gmailSince: since, gmailError: null, lastSyncAt: Date.now() });
  return result;
}

// ---------- 同步 ----------

let syncing = null;

/**
 * 從所有設定好的來源同步（Gmail、Gist）。已經處理過的交易會跳過。
 * 都沒設定時回傳 null；有來源失敗時，其他來源照常匯入，最後丟出第一個錯誤。
 */
export function syncAll({ fetchImpl = globalThis.fetch } = {}) {
  // 同時被呼叫多次（開啟 App、切回前景）時只跑一次
  if (!syncing) {
    syncing = (async () => {
      const results = await Promise.allSettled([doSyncGmail(fetchImpl), doSync(fetchImpl)]);
      const done = results.filter((r) => r.status === 'fulfilled' && r.value).map((r) => r.value);
      const failed = results.find((r) => r.status === 'rejected');
      const total = done.reduce(
        (a, r) => ({ added: a.added + r.added, pending: a.pending + r.pending, skipped: a.skipped + r.skipped }),
        { added: 0, pending: 0, skipped: 0 },
      );
      if (failed) {
        const err = new Error(failed.reason.message);
        err.partial = total;
        throw err;
      }
      return done.length ? total : null;
    })().finally(() => {
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
