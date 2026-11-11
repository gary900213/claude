// 新增／編輯一筆紀錄。
import { addTransaction, deleteTransaction, getTransaction, updateTransaction } from '../services/ledger.js';
import { listCategories } from '../services/categories.js';
import { todayStr } from '../domain/format.js';
import { MAX_NOTE, ValidationError } from '../domain/validate.js';
import { goBack } from '../router.js';
import { emptyState, esc, toast } from './components.js';

// 記住支出、收入各自上一次用的類別，連續記帳比較快
const lastCategory = { expense: null, income: null };

export async function render(el, ctx) {
  const isEdit = ctx.name === 'edit';
  const tx = isEdit ? await getTransaction(ctx.param) : null;
  if (isEdit && !tx) {
    el.innerHTML = `${header('編輯紀錄')}${emptyState('找不到這筆紀錄，可能已經被刪除')}`;
    bindBack(el);
    return;
  }

  const allCats = await listCategories({ includeHidden: true });
  const queryType = ctx.query.get('type');
  const state = {
    type: tx?.type ?? (queryType === 'income' ? 'income' : 'expense'),
    categoryId: tx?.categoryId ?? null,
  };
  if (!state.categoryId) state.categoryId = lastCategory[state.type];

  el.innerHTML = `
    ${header(isEdit ? '編輯紀錄' : '記一筆')}
    <form class="edit-form" novalidate>
      <div class="segmented" role="radiogroup" aria-label="收支類型">
        <button type="button" role="radio" data-type="expense">支出</button>
        <button type="button" role="radio" data-type="income">收入</button>
      </div>

      <label class="amount-field">
        <span aria-hidden="true">$</span>
        <input name="amount" inputmode="numeric" pattern="[0-9]*" autocomplete="off"
               placeholder="0" aria-label="金額" value="${tx ? tx.amount : ''}">
      </label>
      <p class="field-error" data-err="amount"></p>

      <div class="cat-grid" data-cats role="radiogroup" aria-label="類別"></div>
      <p class="field-error" data-err="categoryId"></p>

      <label class="field">
        <span>日期</span>
        <input type="date" name="date" value="${tx?.date ?? todayStr()}" required>
      </label>
      <p class="field-error" data-err="date"></p>

      <label class="field">
        <span>備註</span>
        <input name="note" maxlength="${MAX_NOTE}" placeholder="選填，例如：午餐便當" value="${esc(tx?.note ?? '')}">
      </label>
      <p class="field-error" data-err="note"></p>

      <button class="btn primary block" type="submit">儲存</button>
      ${isEdit ? '<button class="btn danger block" type="button" data-act="delete">刪除這筆</button>' : ''}
    </form>`;

  const form = el.querySelector('form');
  const grid = el.querySelector('[data-cats]');
  const amountInput = form.elements.amount;

  function paint() {
    form.dataset.type = state.type;
    for (const b of el.querySelectorAll('[data-type]')) {
      b.setAttribute('aria-checked', String(b.dataset.type === state.type));
    }
    // 隱藏的類別不顯示，但正在編輯的紀錄用的類別要留著
    const cats = allCats.filter((c) => c.type === state.type && (!c.hidden || c.id === tx?.categoryId));
    if (!cats.some((c) => c.id === state.categoryId)) state.categoryId = cats[0]?.id ?? null;
    grid.innerHTML = cats.length
      ? cats
          .map(
            (c) => `
          <button type="button" class="cat" role="radio" data-cat="${esc(c.id)}"
                  aria-checked="${c.id === state.categoryId}">
            <span class="cat-icon" aria-hidden="true">${esc(c.icon)}</span>
            <span class="cat-name">${esc(c.name)}</span>
          </button>`,
          )
          .join('')
      : '<p class="muted">沒有可用的類別，請到「設定」新增</p>';
  }

  function showErrors(errors = {}) {
    for (const p of el.querySelectorAll('[data-err]')) p.textContent = errors[p.dataset.err] ?? '';
  }

  el.addEventListener('click', async (e) => {
    const typeBtn = e.target.closest('[data-type]');
    const catBtn = e.target.closest('[data-cat]');
    if (typeBtn && typeBtn.dataset.type !== state.type) {
      state.type = typeBtn.dataset.type;
      state.categoryId = lastCategory[state.type];
      paint();
    } else if (catBtn) {
      state.categoryId = catBtn.dataset.cat;
      paint();
      showErrors();
    } else if (e.target.closest('[data-act="delete"]')) {
      if (!confirm('確定要刪除這筆紀錄嗎？')) return;
      await deleteTransaction(tx.id);
      toast('已刪除');
      goBack('#/');
    }
  });
  bindBack(el);

  // 金額只留數字
  amountInput.addEventListener('input', () => {
    const digits = amountInput.value.replace(/\D/g, '').replace(/^0+(?=\d)/, '');
    if (digits !== amountInput.value) amountInput.value = digits;
  });

  // 修改欄位時清掉該欄位的錯誤訊息
  form.addEventListener('input', (e) => {
    const p = el.querySelector(`[data-err="${e.target.name}"]`);
    if (p) p.textContent = '';
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = {
      type: state.type,
      amount: amountInput.value,
      categoryId: state.categoryId,
      date: form.elements.date.value,
      note: form.elements.note.value,
    };
    try {
      if (isEdit) await updateTransaction(tx.id, input);
      else await addTransaction(input);
    } catch (err) {
      if (err instanceof ValidationError) showErrors(err.errors);
      else toast(err.message);
      return;
    }
    if (!isEdit) lastCategory[state.type] = state.categoryId;
    toast('已儲存');
    goBack('#/');
  });

  paint();
  if (!isEdit) return () => amountInput.focus();
}

const header = (title) => `
  <header class="page-head with-back">
    <button class="icon-btn" type="button" data-act="back" aria-label="返回">‹</button>
    <h1>${title}</h1>
  </header>`;

function bindBack(el) {
  el.querySelector('[data-act="back"]').addEventListener('click', () => goBack('#/'));
}
