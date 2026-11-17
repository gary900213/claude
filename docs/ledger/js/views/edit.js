// 新增／編輯一筆紀錄。金額用畫面上的記帳鍵盤輸入，可以直接算加減。
import { addTransaction, deleteTransaction, getTransaction, updateTransaction } from '../services/ledger.js';
import { listCategories } from '../services/categories.js';
import { formatAmount, todayStr } from '../domain/format.js';
import { evalAmount, hasOperator, pressKey } from '../domain/amount.js';
import { MAX_NOTE, ValidationError } from '../domain/validate.js';
import { goBack } from '../router.js';
import { categoryGrid, confirmDialog, emptyState, esc, subHeader, toast } from './components.js';

export const fullscreen = true;

// 記住支出、收入各自上一次用的類別，連續記帳比較快
const lastCategory = { expense: null, income: null };

// 「再記一筆一樣的」帶過來的內容
let prefill = null;

const KEYS = [
  ['7', '8', '9', 'back'],
  ['4', '5', '6', '+'],
  ['1', '2', '3', '-'],
  ['00', '0', 'clear', 'save'],
];
const KEY_LABEL = { back: '⌫', clear: 'C', '-': '−', save: '儲存' };
const KEY_ARIA = { back: '刪除一個數字', clear: '清除金額', '+': '加', '-': '減' };

export async function render(el, ctx) {
  const isEdit = ctx.name === 'edit';
  const tx = isEdit ? await getTransaction(ctx.param) : null;
  if (isEdit && !tx) {
    el.innerHTML = `${subHeader('編輯紀錄')}${emptyState('找不到這筆紀錄，可能已經被刪除')}`;
    bindBack(el);
    return;
  }

  const from = tx ?? (isEdit ? null : prefill);
  prefill = null;
  const allCats = await listCategories({ includeHidden: true });
  const state = {
    type: from?.type ?? (ctx.param === 'income' ? 'income' : 'expense'),
    categoryId: from?.categoryId ?? null,
    expr: from ? String(from.amount) : '',
  };
  if (!state.categoryId) state.categoryId = lastCategory[state.type];

  el.innerHTML = `
    ${subHeader(isEdit ? '編輯紀錄' : '記一筆')}
    <form class="edit-form" novalidate>
      <div class="segmented" role="radiogroup" aria-label="收支類型">
        <button type="button" role="radio" data-type="expense">支出</button>
        <button type="button" role="radio" data-type="income">收入</button>
      </div>

      <div class="amount-field" role="status" aria-label="金額">
        <span aria-hidden="true">$</span>
        <output class="amount-expr" data-expr></output>
        <span class="amount-result" data-result></span>
      </div>
      <p class="field-error" data-err="amount"></p>

      <div class="cat-grid" data-cats role="radiogroup" aria-label="類別"></div>
      <p class="field-error" data-err="categoryId"></p>

      <div class="field-row">
        <label class="field">
          <span>日期</span>
          <input type="date" name="date" value="${tx?.date ?? todayStr()}" required>
        </label>
        <label class="field">
          <span>備註</span>
          <input name="note" maxlength="${MAX_NOTE}" placeholder="選填" enterkeyhint="done" value="${esc(from?.note ?? '')}">
        </label>
      </div>
      <p class="field-error" data-err="date"></p>
      <p class="field-error" data-err="note"></p>

      ${
        isEdit
          ? `<div class="btn-row">
               <button class="btn" type="button" data-act="copy">再記一筆一樣的</button>
               <button class="btn danger" type="button" data-act="delete">刪除這筆</button>
             </div>`
          : ''
      }

      <div class="keypad" role="group" aria-label="金額鍵盤">
        ${KEYS.flat()
          .map((k) =>
            k === 'save'
              ? '<button class="key save" type="submit">儲存</button>'
              : `<button class="key ${/^\d+$/.test(k) ? '' : 'op'}" type="button" data-key="${k}"
                   ${KEY_ARIA[k] ? `aria-label="${KEY_ARIA[k]}"` : ''}>${KEY_LABEL[k] ?? k}</button>`,
          )
          .join('')}
      </div>
    </form>`;

  const form = el.querySelector('form');
  const grid = el.querySelector('[data-cats]');
  const exprEl = el.querySelector('[data-expr]');
  const resultEl = el.querySelector('[data-result]');

  function paint() {
    form.dataset.type = state.type;
    for (const b of el.querySelectorAll('[data-type]')) {
      b.setAttribute('aria-checked', String(b.dataset.type === state.type));
    }
    // 隱藏的類別不顯示，但正在編輯的紀錄用的類別要留著
    const cats = allCats.filter((c) => c.type === state.type && (!c.hidden || c.id === tx?.categoryId));
    if (!cats.some((c) => c.id === state.categoryId)) state.categoryId = cats[0]?.id ?? null;
    grid.innerHTML = categoryGrid(cats, state.categoryId);
  }

  function paintAmount() {
    exprEl.textContent = state.expr ? state.expr.replace(/-/g, '−') : '0';
    exprEl.classList.toggle('placeholder', !state.expr);
    const value = evalAmount(state.expr);
    resultEl.textContent = hasOperator(state.expr) && Number.isFinite(value) ? `= ${formatAmount(value)}` : '';
  }

  function showErrors(errors = {}) {
    for (const p of el.querySelectorAll('[data-err]')) p.textContent = errors[p.dataset.err] ?? '';
  }

  function press(key) {
    state.expr = pressKey(state.expr, key);
    el.querySelector('[data-err="amount"]').textContent = '';
    paintAmount();
  }

  el.addEventListener('click', async (e) => {
    const typeBtn = e.target.closest('[data-type]');
    const catBtn = e.target.closest('[data-cat]');
    const keyBtn = e.target.closest('[data-key]');
    if (keyBtn) {
      press(keyBtn.dataset.key);
    } else if (typeBtn && typeBtn.dataset.type !== state.type) {
      state.type = typeBtn.dataset.type;
      state.categoryId = lastCategory[state.type];
      paint();
    } else if (catBtn) {
      state.categoryId = catBtn.dataset.cat;
      paint();
      showErrors();
    } else if (e.target.closest('[data-act="copy"]')) {
      prefill = { type: tx.type, categoryId: tx.categoryId, amount: tx.amount, note: tx.note };
      location.replace('#add');
    } else if (e.target.closest('[data-act="delete"]')) {
      if (!(await confirmDialog('確定要刪除這筆紀錄嗎？', { ok: '刪除', danger: true }))) return;
      await deleteTransaction(tx.id);
      toast('已刪除');
      goBack('#home');
    }
  });
  bindBack(el);

  // 電腦上可以直接用鍵盤輸入金額（游標在日期、備註欄位時除外）
  const onKey = (e) => {
    if (!el.isConnected) {
      document.removeEventListener('keydown', onKey);
      return;
    }
    if (e.target.closest?.('input, select, textarea, dialog') || e.metaKey || e.ctrlKey || e.altKey) return;
    const key = e.key === 'Backspace' ? 'back' : e.key === 'Escape' ? null : e.key;
    if (e.key === 'Enter') {
      e.preventDefault();
      form.requestSubmit();
    } else if (key && /^[\d+-]$|^back$/.test(key)) {
      e.preventDefault();
      press(key);
    }
  };
  document.addEventListener('keydown', onKey);

  // 修改欄位時清掉該欄位的錯誤訊息
  form.addEventListener('input', (e) => {
    const p = el.querySelector(`[data-err="${e.target.name}"]`);
    if (p) p.textContent = '';
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = {
      type: state.type,
      amount: state.expr,
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
    goBack('#home');
  });

  paint();
  paintAmount();
}

function bindBack(el) {
  el.querySelector('[data-act="back"]').addEventListener('click', () => goBack('#home'));
}
