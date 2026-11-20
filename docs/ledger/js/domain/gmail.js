// Gmail 刷卡通知：產生使用者貼到 Google Apps Script 的程式碼。純函式。
//
// 運作方式：使用者把這段程式部署成「網頁應用程式」（以自己的身分執行），
// 記帳本開啟時呼叫它的網址，它從 Gmail 找出刷卡通知信，回傳信件開頭的文字。
// 搜尋條件寫死在程式裡（不從網址傳入），就算網址外流也只能讀到刷卡通知，讀不到其他信。

export const MAX_CHARS = 800;
export const SEARCH_DAYS = 30;
const DEFAULT_SUBJECT = '(刷卡 OR 消費 OR 交易 OR 授權)';

/** 從使用者輸入的寄件人（逗號或空白分隔）組出 Gmail 搜尋條件 */
export function buildQuery(senders = '') {
  const list = String(senders)
    .split(/[\s,，;；]+/)
    .map((s) => s.trim())
    .filter((s) => /^[^\s"()]+$/.test(s));
  const from = list.length ? `from:(${list.join(' OR ')}) ` : `subject:${DEFAULT_SUBJECT} `;
  return `${from}newer_than:${SEARCH_DAYS}d -in:spam -in:trash`;
}

/** 網址看起來是 Apps Script 網頁應用程式（.../macros/s/<id>/exec） */
export const isAppsScriptUrl = (url) =>
  /^https:\/\/script\.google\.com\/(a\/[^/]+\/)?macros\/s\/[\w-]+\/exec$/.test(String(url ?? '').trim());

/** 產生貼到 Apps Script 的完整程式碼 */
export function buildAppsScript({ key, query }) {
  return `// 記帳本：讀取 Gmail 裡的刷卡通知，提供給記帳本自動記帳。
// 只會回傳符合 QUERY 的信件開頭 ${MAX_CHARS} 個字，而且要有正確的 KEY 才能讀取。
// 這段程式是記帳本自動產生的，請不要把網址或 KEY 給別人。
const KEY = ${JSON.stringify(key)};
const QUERY = ${JSON.stringify(query)};
const MAX_CHARS = ${MAX_CHARS};

function doGet(e) {
  const p = (e && e.parameter) || {};
  if (p.key !== KEY) return reply({ ok: false, error: 'key' });
  const since = Number(p.since) || 0;
  const items = [];
  GmailApp.search(QUERY, 0, 100).forEach(function (thread) {
    thread.getMessages().forEach(function (m) {
      const date = m.getDate().getTime();
      if (date <= since) return;
      const text = (m.getSubject() + '\\n' + m.getPlainBody())
        .replace(/[ \\t]+/g, ' ')
        .replace(/\\s*\\n\\s*/g, '\\n')
        .slice(0, MAX_CHARS);
      items.push({ id: m.getId(), date: date, text: text });
    });
  });
  items.sort(function (a, b) { return a.date - b.date; });
  return reply({ ok: true, items: items });
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// 第一次部署前先執行這個函式一次，讓 Google 詢問 Gmail 的讀取權限
function authorize() {
  GmailApp.search(QUERY, 0, 1);
}
`;
}
