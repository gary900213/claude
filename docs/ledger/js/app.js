// 進入點：開資料庫、寫入預設類別、啟動路由、註冊離線快取。
import { ensureDefaults } from './services/categories.js';
import { generateDue } from './services/recurring.js';
import { refresh, startRouter } from './router.js';
import { esc, toast } from './views/components.js';

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

  await runRecurring({ rerender: false });
  startRouter(view);

  // App 一直開著跨過午夜、或從背景切回來時，再檢查一次
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') runRecurring({ rerender: true });
  });

  const secure = location.protocol === 'https:' || ['localhost', '127.0.0.1'].includes(location.hostname);
  if ('serviceWorker' in navigator && secure) {
    navigator.serviceWorker.register('./sw.js').catch((err) => console.warn('Service Worker 註冊失敗', err));
  }
}

main();
