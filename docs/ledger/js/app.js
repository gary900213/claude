// 進入點：開資料庫、寫入預設類別、啟動路由、註冊離線快取。
import { ensureDefaults } from './services/categories.js';
import { generateDue } from './services/recurring.js';
import { syncAll } from './services/inbox.js';
import { refresh, startRouter } from './router.js';
import { confirmDialog, esc, toast } from './views/components.js';
import { PREVIEW } from './config.js';
import { clearAllData, loadSample, loadSampleOnce } from './services/preview.js';

/** 預覽版：頁面最上方的說明列，可以清空或放回範例資料 */
function mountPreviewBar(view) {
  const wrap = document.createElement('div');
  wrap.className = 'preview-wrap';
  wrap.innerHTML = `
    <div class="preview-bar" role="note">
      <span>預覽版：目前是範例資料，只存在你的瀏覽器裡，可以隨意新增、修改、刪除試試看。</span>
      <span class="btn-row">
        <button class="btn small" type="button" data-preview="clear">清空資料</button>
        <button class="btn small" type="button" data-preview="sample">放回範例資料</button>
      </span>
    </div>`;
  view.before(wrap);
  wrap.addEventListener('click', async (e) => {
    const act = e.target.closest('[data-preview]')?.dataset.preview;
    if (!act) return;
    const clear = act === 'clear';
    const ok = await confirmDialog(
      clear ? '要清空所有紀錄、預算和固定收支嗎？類別會恢復成預設。' : '要用範例資料取代目前的所有資料嗎？',
      { ok: clear ? '清空' : '放回範例', danger: true },
    );
    if (!ok) return;
    if (clear) await clearAllData();
    else {
      await loadSample();
      await generateDue();
    }
    toast(clear ? '已清空' : '已放回範例資料');
    refresh();
  });
}

let lastSync = 0;

/** 從刷卡自動記帳的收件匣同步（最多一分鐘一次）；有新紀錄就重畫目前頁面 */
async function runInbox() {
  if (PREVIEW || !navigator.onLine || Date.now() - lastSync < 60_000) return;
  lastSync = Date.now();
  try {
    const r = await syncAll();
    if (r?.added || r?.pending) {
      refresh();
      const parts = [];
      if (r.added) parts.push(`記入 ${r.added} 筆`);
      if (r.pending) parts.push(`${r.pending} 筆待補金額（設定 → 刷卡自動記帳）`);
      toast(`刷卡自動記帳：${parts.join('，')}`);
    }
  } catch (err) {
    // 有一個來源失敗時，其他來源記到的照樣提示
    if (err.partial?.added) {
      refresh();
      toast(`刷卡自動記帳：記入 ${err.partial.added} 筆（有一個來源同步失敗）`);
    }
    console.warn('刷卡自動記帳同步失敗', err);
  }
}

/** 自動記入到期的固定收支；有新紀錄就重畫目前頁面 */
async function runRecurring({ rerender }) {
  try {
    const n = await generateDue();
    if (n) {
      if (rerender) refresh();
      toast(`已自動記入 ${n} 筆固定收支`);
    }
  } catch (err) {
    console.error('固定收支產生失敗', err);
  }
}

async function main() {
  const view = document.getElementById('view');
  try {
    await ensureDefaults();
  } catch (err) {
    console.error(err);
    view.innerHTML = `<p class="empty error">無法開啟資料庫：${esc(err.message)}<br>如果是無痕模式，請改用一般模式開啟。</p>`;
    return;
  }

  // 請瀏覽器不要在空間不足時自動清掉資料
  navigator.storage?.persist?.().catch(() => {});

  if (PREVIEW) {
    await loadSampleOnce().catch((err) => console.error('範例資料載入失敗', err));
    mountPreviewBar(view);
  }
  await runRecurring({ rerender: false });
  startRouter(view);
  runInbox();

  // App 一直開著跨過午夜、或從背景切回來時，再檢查一次
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      runRecurring({ rerender: true });
      runInbox();
    }
  });

  const secure = location.protocol === 'https:' || ['localhost', '127.0.0.1'].includes(location.hostname);
  if ('serviceWorker' in navigator && secure && !PREVIEW) {
    navigator.serviceWorker.register('./sw.js').catch((err) => console.warn('Service Worker 註冊失敗', err));
  }
}

main();
