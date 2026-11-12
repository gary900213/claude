// 每月預算：設定總預算與各支出類別預算，並顯示本月使用狀況。
import { getBudgets, saveBudgets } from '../services/budget.js';
import { listByMonth } from '../services/ledger.js';
import { listCategories } from '../services/categories.js';
import { budgetStatus, TOTAL_ID } from '../domain/budget.js';
import { monthOf, todayStr } from '../domain/format.js';
import { ValidationError } from '../domain/validate.js';
import { goBack } from '../router.js';
import { budgetCard, esc, subHeader, toast } from './components.js';

export async function render(el) {
  const today = todayStr();
  const month = monthOf(today);
  const [budgets, cats, monthTxs] = await Promise.all([
    getBudgets(),
    listCategories({ type: 'expense', includeHidden: true }),
    listByMonth(month),
  ]);
  const amountOf = new Map(budgets.map((b) => [b.id, b.amount]));
  // 隱藏的類別如果還有預算，也要列出來，才能清掉
  const shown = cats.filter((c) => !c.hidden || amountOf.has(c.id));

  const input = (id, label, icon = '') => `
    <label class="budget-input">
      <span class="budget-input-name">${icon ? `<span class="cat-icon" aria-hidden="true">${esc(icon)}</span>` : ''}${esc(label)}</span>
      <span class="money-input"><span aria-hidden="true">$</span>
        <input name="${esc(id)}" inputmode="numeric" pattern="[0-9]*" autocomplete="off" placeholder="不設定"
               value="${amountOf.get(id) ?? ''}" aria-label="${esc(label)}預算"></span>
    </label>
    <p class="field-error" data-err="${esc(id)}"></p>`;

  el.innerHTML = `
    ${subHeader('每月預算')}
    <div data-status>${budgetCard(budgetStatus(monthTxs, budgets, cats, month, today), { editLink: false })}</div>
    <form class="card budget-form" novalidate>
      <div class="section-head"><h2>每月總預算</h2></div>
      ${input(TOTAL_ID, '全部支出')}
      <div class="section-head"><h2>各類別預算</h2></div>
      ${shown.map((c) => input(c.id, c.name, c.icon)).join('')}
      <p class="hint">留空代表不設定。每個月都套用同一份預算；類別預算加起來不需要等於總預算。</p>
      <button class="btn primary block" type="submit">儲存預算</button>
    </form>`;

  el.querySelector('[data-act="back"]').addEventListener('click', () => goBack('#/settings'));

  const form = el.querySelector('form');
  form.addEventListener('input', (e) => {
    const t = e.target;
    const digits = t.value.replace(/\D/g, '').replace(/^0+(?=\d)/, '');
    if (digits !== t.value) t.value = digits;
    const err = form.querySelector(`[data-err="${CSS.escape(t.name)}"]`);
    if (err) err.textContent = '';
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const values = Object.fromEntries([...form.elements].filter((i) => i.name).map((i) => [i.name, i.value]));
    try {
      const saved = await saveBudgets(values);
      el.querySelector('[data-status]').innerHTML = budgetCard(
        budgetStatus(monthTxs, saved, cats, month, today),
        { editLink: false },
      );
      toast(saved.length ? '已儲存預算' : '已清除預算');
    } catch (err) {
      if (err instanceof ValidationError) {
        for (const [id, msg] of Object.entries(err.errors)) {
          form.querySelector(`[data-err="${CSS.escape(id)}"]`).textContent = msg;
        }
      } else toast(err.message);
    }
  });
}
