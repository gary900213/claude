// hash 路由：#/、#/list?m=2026-11、#/stats、#/settings、#/add?type=income、#/edit/<id>、
//          #/budget、#/recurring、#/recurring/new、#/recurring/<id>
import * as home from './views/home.js';
import * as list from './views/list.js';
import * as stats from './views/stats.js';
import * as settings from './views/settings.js';
import * as edit from './views/edit.js';
import * as budget from './views/budget.js';
import * as recurring from './views/recurring.js';
import { esc } from './views/components.js';

const views = { home, list, stats, settings, add: edit, edit, budget, recurring };

// 子頁面在底部選單要亮哪一個分頁
const TAB_OF = { budget: 'settings', recurring: 'settings' };

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

let renderCurrent = () => {};

/** 重畫目前的頁面（例如背景自動記入固定收支之後） */
export const refresh = () => renderCurrent();

export function startRouter(container) {
  const render = async () => {
    const token = ++renderToken;
    const ctx = parseHash();
    const view = views[ctx.name];
    const tab = TAB_OF[ctx.name] ?? ctx.name;
    // fullscreen 的頁面（新增／編輯表單）不顯示底部選單
    const full = typeof view.fullscreen === 'function' ? view.fullscreen(ctx) : Boolean(view.fullscreen);
    document.body.classList.toggle('fullscreen', full);
    for (const a of document.querySelectorAll('.tabbar a')) {
      a.toggleAttribute('aria-current', a.dataset.tab === tab);
    }
    const el = document.createElement('div');
    el.className = `page page-${ctx.name}`;
    let mounted;
    try {
      mounted = await view.render(el, ctx);
    } catch (err) {
      console.error(err);
      el.innerHTML = `<p class="empty error">發生錯誤：${esc(err.message)}</p>`;
    }
    if (token !== renderToken) return; // 已經換到別頁了
    container.replaceChildren(el);
    window.scrollTo(0, 0);
    if (typeof mounted === 'function') mounted();
  };

  renderCurrent = render;
  window.addEventListener('hashchange', () => {
    navigated = true;
    render();
  });
  render();
}
