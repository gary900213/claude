// 設定：類別管理、備份與還原。
import {
  addCategory,
  deleteCategory,
  listCategories,
  moveCategory,
  setHidden,
  updateCategory,
} from '../services/categories.js';
import { getAllTransactions } from '../services/ledger.js';
import { exportCSV, exportJSON, getLastExportAt, importJSON } from '../services/backup.js';
import { countByCategory } from '../domain/stats.js';
import { ValidationError } from '../domain/validate.js';
import { emptyState, esc, toast } from './components.js';

const ICON_CHOICES = ['🍜', '☕', '🚗', '⛽', '✈️', '🏍️', '🏥', '👕', '📱', '🎮', '🐶', '👶', '💄', '📚', '🎬', '🛒', '🏋️', '💳', '🧾', '🎂'];

let tab = 'expense';

export async function render(el) {
  el.innerHTML = `
    <header class="page-head"><h1>設定</h1></header>

    <section class="card">
      <div class="section-head"><h2>類別管理</h2></div>
      <div class="segmented small" role="tablist">
        <button type="button" role="tab" data-tab="expense">支出類別</button>
        <button type="button" role="tab" data-tab="income">收入類別</button>
      </div>
      <ul class="cat-rows" data-rows></ul>
      <button class="btn block" type="button" data-act="add">＋ 新增類別</button>
      <p class="hint">有紀錄的類別不能刪除，可以「隱藏」，記帳時就不會出現，舊紀錄不受影響。</p>
    </section>

    <section class="card">
      <div class="section-head"><h2>備份與還原</h2></div>
      <p class="hint" data-backup-info></p>
      <div class="btn-row">
        <button class="btn" type="button" data-act="export-json">匯出備份</button>
        <button class="btn" type="button" data-act="export-csv">匯出 CSV</button>
        <label class="btn">匯入備份<input type="file" accept=".json,application/json" data-act="import" hidden></label>
      </div>
      <p class="hint">資料只存在這個瀏覽器裡，清除瀏覽器資料或換手機前，請先「匯出備份」。CSV 可以用 Excel 開啟。</p>
    </section>

    <dialog class="sheet" data-dialog>
      <form method="dialog" novalidate>
        <h2 data-dialog-title></h2>
        <label class="field"><span>名稱</span><input name="name" maxlength="8" autocomplete="off" required></label>
        <p class="field-error" data-err="name"></p>
        <label class="field"><span>圖示</span><input name="icon" class="icon-input" autocomplete="off" required></label>
        <div class="icon-choices">${ICON_CHOICES.map((i) => `<button type="button" data-icon="${i}">${i}</button>`).join('')}</div>
        <p class="field-error" data-err="icon"></p>
        <div class="dialog-extra" data-extra></div>
        <div class="btn-row">
          <button class="btn" value="cancel" formnovalidate>取消</button>
          <button class="btn primary" value="save">儲存</button>
        </div>
      </form>
    </dialog>`;

  const rowsEl = el.querySelector('[data-rows]');
  const dialog = el.querySelector('[data-dialog]');
  const dForm = dialog.querySelector('form');
  let cats = [];
  let counts = new Map();
  let editing = null; // 正在編輯的類別；null = 新增

  async function refresh() {
    const [allCats, txs, lastExport] = await Promise.all([
      listCategories({ includeHidden: true }),
      getAllTransactions(),
      getLastExportAt(),
    ]);
    cats = allCats;
    counts = countByCategory(txs);
    el.querySelector('[data-backup-info]').textContent =
      `目前共 ${txs.length} 筆紀錄。` +
      (lastExport ? `上次匯出備份：${new Date(lastExport).toLocaleString('zh-TW')}` : '還沒有匯出過備份。');
    paint();
  }

  function paint() {
    for (const b of el.querySelectorAll('[data-tab]')) b.setAttribute('aria-selected', String(b.dataset.tab === tab));
    const list = cats.filter((c) => c.type === tab);
    rowsEl.innerHTML = list.length
      ? list
          .map(
            (c, i) => `
        <li class="cat-row ${c.hidden ? 'is-hidden' : ''}" data-id="${esc(c.id)}">
          <span class="cat-icon" aria-hidden="true">${esc(c.icon)}</span>
          <span class="cat-row-name">${esc(c.name)}
            <small>${counts.get(c.id) ?? 0} 筆${c.hidden ? '・已隱藏' : ''}</small></span>
          <button class="icon-btn" type="button" data-act="up" aria-label="往上移" ${i === 0 ? 'disabled' : ''}>↑</button>
          <button class="icon-btn" type="button" data-act="down" aria-label="往下移" ${i === list.length - 1 ? 'disabled' : ''}>↓</button>
          <button class="btn small" type="button" data-act="edit">編輯</button>
        </li>`,
          )
          .join('')
      : emptyState('沒有類別');
  }

  function openDialog(cat) {
    editing = cat;
    dialog.querySelector('[data-dialog-title]').textContent = cat ? '編輯類別' : `新增${tab === 'expense' ? '支出' : '收入'}類別`;
    dForm.elements.name.value = cat?.name ?? '';
    dForm.elements.icon.value = cat?.icon ?? '';
    for (const p of dialog.querySelectorAll('[data-err]')) p.textContent = '';
    const used = cat ? counts.get(cat.id) ?? 0 : 0;
    dialog.querySelector('[data-extra]').innerHTML = cat
      ? `<button class="btn block" type="button" data-act="toggle-hidden">${cat.hidden ? '取消隱藏' : '隱藏這個類別'}</button>
         ${used ? '' : '<button class="btn danger block" type="button" data-act="delete">刪除這個類別</button>'}`
      : '';
    dialog.showModal();
  }

  async function act(fn, okMessage) {
    try {
      await fn();
      if (okMessage) toast(okMessage);
      await refresh();
      return true;
    } catch (err) {
      if (err instanceof ValidationError) {
        for (const p of dialog.querySelectorAll('[data-err]')) p.textContent = err.errors[p.dataset.err] ?? '';
      } else {
        toast(err.message);
      }
      return false;
    }
  }

  el.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-tab],[data-act],[data-icon]');
    if (!t) return;
    if (t.dataset.tab) {
      tab = t.dataset.tab;
      paint();
      return;
    }
    if (t.dataset.icon) {
      dForm.elements.icon.value = t.dataset.icon;
      return;
    }
    const id = t.closest('[data-id]')?.dataset.id;
    switch (t.dataset.act) {
      case 'add':
        openDialog(null);
        break;
      case 'edit':
        openDialog(cats.find((c) => c.id === id));
        break;
      case 'up':
      case 'down':
        await act(() => moveCategory(id, t.dataset.act === 'up' ? -1 : 1));
        break;
      case 'toggle-hidden':
        if (await act(() => setHidden(editing.id, !editing.hidden), editing.hidden ? '已取消隱藏' : '已隱藏')) dialog.close();
        break;
      case 'delete':
        if (!confirm(`確定要刪除「${editing.name}」嗎？`)) return;
        if (await act(() => deleteCategory(editing.id), '已刪除')) dialog.close();
        break;
      case 'export-json':
        await act(exportJSON, '已匯出備份');
        break;
      case 'export-csv':
        await act(exportCSV, '已匯出 CSV');
        break;
    }
  });

  dForm.addEventListener('submit', async (e) => {
    if (e.submitter?.value !== 'save') return; // 取消：讓 dialog 自己關閉
    e.preventDefault();
    const input = { type: tab, name: dForm.elements.name.value, icon: dForm.elements.icon.value };
    const ok = await act(
      () => (editing ? updateCategory(editing.id, input) : addCategory(input)),
      editing ? '已更新類別' : '已新增類別',
    );
    if (ok) dialog.close();
  });

  el.querySelector('[data-act="import"]').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    if (!confirm('匯入會「取代」目前所有的類別和紀錄，確定要繼續嗎？\n建議先匯出一份目前的備份。')) return;
    await act(async () => {
      const r = await importJSON(await file.text());
      toast(`已匯入 ${r.transactions} 筆紀錄、${r.categories} 個類別`);
    });
  });

  await refresh();
}
