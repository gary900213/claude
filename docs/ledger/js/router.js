// hash 路由：#/、#/list?m=2026-11、#/stats、#/settings、#/add?type=income、#/edit/<id>
import * as home from './views/home.js';
import * as list from './views/list.js';
import * as stats from './views/stats.js';
import * as settings from './views/settings.js';
import * as edit from './views/edit.js';
import { esc } from './views/components.js';

const views = { home, list, stats, settings, add: edit, edit };

let navigated = false;
let renderToken = 0;

export function parseHash(hash = location.hash) {
  const h = hash.replace(/^#/, '') || '/';
  const [path, qs = ''] = h.split('?');
  const parts = path.split('/').filter(Boolean);
  return {
    name: parts[0] && views[parts[0]] ? parts[0] : 'home',
    param: parts[1] ? decodeURIComponent(parts[1]) : null,
    query: new URLSearchParams(qs),
  };
}

/** 回上一頁；如果是直接開啟這一頁（沒有上一頁），就回首頁 */
export function goBack(fallback = '#/') {
  if (navigated) history.back();
  else location.replace(fallback);
}

/** 換頁但不留下瀏覽紀錄（例如切換月份） */
export const replaceRoute = (hash) => location.replace(hash);

export function startRouter(container) {
  const render = async () => {
    const token = ++renderToken;
    const ctx = parseHash();
    document.body.dataset.route = ctx.name;
    for (const a of document.querySelectorAll('.tabbar a')) {
      a.toggleAttribute('aria-current', a.dataset.tab === ctx.name);
    }
    const el = document.createElement('div');
    el.className = `page page-${ctx.name}`;
    let mounted;
    try {
      mounted = await views[ctx.name].render(el, ctx);
    } catch (err) {
      console.error(err);
      el.innerHTML = `<p class="empty error">發生錯誤：${esc(err.message)}</p>`;
    }
    if (token !== renderToken) return; // 已經換到別頁了
    container.replaceChildren(el);
    window.scrollTo(0, 0);
    if (typeof mounted === 'function') mounted();
  };

  window.addEventListener('hashchange', () => {
    navigated = true;
    render();
  });
  render();
}
