// IndexedDB 包裝：整個 App 只有這個檔案直接碰資料庫。
// 之後要換成雲端儲存，只需要改這一層。

const DB_NAME = 'ledger';
const DB_VERSION = 2;
// 備份／匯入涵蓋的資料表
export const DATA_STORES = ['categories', 'transactions', 'budgets', 'recurring'];

let dbPromise = null;

export function openDB() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('categories')) {
          db.createObjectStore('categories', { keyPath: 'id' }).createIndex('type', 'type');
        }
        if (!db.objectStoreNames.contains('transactions')) {
          const s = db.createObjectStore('transactions', { keyPath: 'id' });
          s.createIndex('date', 'date');
          s.createIndex('categoryId', 'categoryId');
        }
        if (!db.objectStoreNames.contains('meta')) {
          db.createObjectStore('meta', { keyPath: 'key' });
        }
        // v2：每月預算、固定收支
        if (!db.objectStoreNames.contains('budgets')) {
          db.createObjectStore('budgets', { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains('recurring')) {
          db.createObjectStore('recurring', { keyPath: 'id' });
        }
      };
      req.onsuccess = () => {
        const db = req.result;
        // 其他分頁要升級資料庫時，讓出連線，避免卡住
        db.onversionchange = () => {
          db.close();
          dbPromise = null;
        };
        resolve(db);
      };
      req.onerror = () => reject(req.error);
      req.onblocked = () => reject(new Error('資料庫被其他分頁占用，請關閉其他記帳本分頁後重新整理'));
    });
    dbPromise.catch(() => {
      dbPromise = null;
    });
  }
  return dbPromise;
}

/**
 * 在一個交易中執行 fn。fn 回傳 IDBRequest 時，結果是該 request 的 result。
 * 等交易真正完成（資料寫入）後才 resolve。
 */
export async function run(stores, mode, fn) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const t = db.transaction(stores, mode);
    let out;
    try {
      out = fn(t);
    } catch (err) {
      t.abort();
      reject(err);
      return;
    }
    t.oncomplete = () => resolve(out instanceof IDBRequest ? out.result : out);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error ?? new Error('資料庫交易中止'));
  });
}

export const uid = () =>
  globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

export const get = (store, key) => run(store, 'readonly', (t) => t.objectStore(store).get(key));

export const getAll = (store) => run(store, 'readonly', (t) => t.objectStore(store).getAll());

export const put = (store, value) =>
  run(store, 'readwrite', (t) => {
    t.objectStore(store).put(value);
    return value;
  });

export const putMany = (store, values) =>
  run(store, 'readwrite', (t) => {
    const s = t.objectStore(store);
    for (const v of values) s.put(v);
    return values.length;
  });

export const remove = (store, key) =>
  run(store, 'readwrite', (t) => {
    t.objectStore(store).delete(key);
  });

/** 依索引查詢範圍 [lower, upper]（含兩端） */
export const getByRange = (store, index, lower, upper) =>
  run(store, 'readonly', (t) => t.objectStore(store).index(index).getAll(IDBKeyRange.bound(lower, upper)));

export const countByIndex = (store, index, key) =>
  run(store, 'readonly', (t) => t.objectStore(store).index(index).count(key));

/** 用一個交易清空並寫入全部資料（匯入備份用），失敗時整批還原 */
export const replaceAll = (data) =>
  run([...DATA_STORES, 'meta'], 'readwrite', (t) => {
    for (const name of DATA_STORES) {
      const s = t.objectStore(name);
      s.clear();
      for (const v of data[name] ?? []) s.put(v);
    }
    t.objectStore('meta').put({ key: 'initialized', value: true });
  });

/** 一個交易內清空某個資料表再寫入（例如整份預算一起儲存） */
export const replaceStore = (store, values) =>
  run(store, 'readwrite', (t) => {
    const s = t.objectStore(store);
    s.clear();
    for (const v of values) s.put(v);
  });

/** 第一次啟動時寫入預設類別（同一個交易，不會寫一半） */
export const initOnce = (categories, schemaVersion) =>
  run(['categories', 'meta'], 'readwrite', (t) => {
    const meta = t.objectStore('meta');
    const req = meta.get('initialized');
    req.onsuccess = () => {
      if (req.result) return;
      const s = t.objectStore('categories');
      for (const c of categories) s.put(c);
      meta.put({ key: 'initialized', value: true });
      meta.put({ key: 'schemaVersion', value: schemaVersion });
    };
  });
