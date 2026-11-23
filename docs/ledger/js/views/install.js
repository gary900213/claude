// 「加到主畫面」引導：在手機瀏覽器（還沒安裝時）於首頁顯示。
import { PREVIEW } from '../config.js';
import { esc } from './components.js';

const DISMISS_KEY = 'ledger.installDismissed';
let deferredPrompt = null;

// Android／電腦版 Chrome：攔下安裝提示，改由我們的按鈕觸發
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
});

export const isStandalone = () =>
  window.navigator.standalone === true || matchMedia('(display-mode: standalone)').matches;

const isIOS = () =>
  /iphone|ipad|ipod/i.test(navigator.userAgent) ||
  (navigator.userAgent.includes('Macintosh') && navigator.maxTouchPoints > 1);

function dismissed() {
  try {
    return localStorage.getItem(DISMISS_KEY) === '1';
  } catch {
    return false;
  }
}

const SHARE_ICON =
  '<svg class="inline-icon" viewBox="0 0 24 24" aria-label="分享按鈕"><path d="M12 3v12M8 7l4-4 4 4M6 11H5v10h14V11h-1"/></svg>';

/** 要顯示的引導卡片（不需要時回傳空字串） */
export function installCard() {
  if (PREVIEW || isStandalone() || dismissed()) return '';
  if (isIOS()) {
    return card(`點 Safari 的分享按鈕 ${SHARE_ICON}，往下滑選「<b>加入主畫面</b>」。之後從桌面打開，就像一般 App，資料也會好好保存。`, false);
  }
  if (deferredPrompt) return card('裝到主畫面後打開比較快，沒有網路也能記帳。', true);
  return '';
}

const card = (text, canInstall) => `
  <section class="card install-card" data-install>
    <div class="section-head"><h2>📲 把記帳本加到主畫面</h2></div>
    <p>${text}</p>
    <div class="btn-row">
      ${canInstall ? '<button class="btn primary" type="button" data-install-act="install">安裝</button>' : ''}
      <button class="btn" type="button" data-install-act="dismiss">${canInstall ? '不用了' : '知道了'}</button>
    </div>
  </section>`;

/** 綁定卡片上的按鈕 */
export function bindInstall(el) {
  el.querySelector('[data-install]')?.addEventListener('click', async (e) => {
    const act = e.target.closest('[data-install-act]')?.dataset.installAct;
    if (!act) return;
    if (act === 'install' && deferredPrompt) {
      deferredPrompt.prompt();
      await deferredPrompt.userChoice.catch(() => null);
      deferredPrompt = null;
    }
    try {
      localStorage.setItem(DISMISS_KEY, '1');
    } catch {
      // 無痕模式等情況存不了，下次再顯示也沒關係
    }
    el.querySelector('[data-install]')?.remove();
  });
}

