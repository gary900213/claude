// 進入點：開資料庫、寫入預設類別、啟動路由、註冊離線快取。
import { ensureDefaults } from './services/categories.js';
import { startRouter } from './router.js';
import { esc } from './views/components.js';

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

  startRouter(view);

  const secure = location.protocol === 'https:' || ['localhost', '127.0.0.1'].includes(location.hostname);
  if ('serviceWorker' in navigator && secure) {
    navigator.serviceWorker.register('./sw.js').catch((err) => console.warn('Service Worker 註冊失敗', err));
  }
}

main();
