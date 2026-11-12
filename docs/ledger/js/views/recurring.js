// 固定收支：列表（#/recurring）與新增／編輯表單（#/recurring/new、#/recurring/<id>）。
import { deleteRule, generateDue, getRule, listRules, saveRule } from '../services/recurring.js';
import { listCategories } from '../services/categories.js';
import { dueDates, nextDate, suggestStartMonth } from '../domain/recurring.js';
import { formatAmount, isMonthStr, todayStr } from '../domain/format.js';
import { MAX_NOTE, ValidationError } from '../domain/validate.js';
import { goBack } from '../router.js';
import { catMap, categoryGrid, emptyState, esc, subHeader, toast } from './components.js';

export const fullscreen = (ctx) => Boolean(ctx.param);

export function render(el, ctx) {
  return ctx.param ? renderForm(el, ctx.param === 'new' ? null : ctx.param) : renderList(el);
}

const slash = (date) => date.replaceAll('-', '/');

async function renderList(el) {
  const today = todayStr();
  const [rules, cats] = await Promise.all([listRules(), listCategories({ includeHidden: true })]);
  const map = catMap(cats);

  const row = (r) => {
    const cat = map.get(r.categoryId);
    const next = nextDate(r, today);
    return `
      <li><a class="tx ${r.active ? '' : 'is-off'}" href="#/recurring/${encodeURIComponent(r.id)}">
        <span class="tx-icon" aria-hidden="true">${esc(cat?.icon ?? '❔')}</span>
        <span class="tx-main">
          <span class="tx-cat">${esc(r.note || cat?.name || '未知類別')}</span>
          <span class="tx-note">每月 ${r.day} 日・${next ? `下次 ${slash(next)}` : '已暫停'}</span>
        </span>
        <span class="tx-amt ${r.type}">${r.type === 'expense' ? '-' : '+'}${formatAmount(r.amount)}</span>
      </a></li>`;
  };

  el.innerHTML = `
    ${subHeader('固定收支')}
    <section class="card">
      ${rules.length ? `<ul class="tx-list">${rules.map(row).join('')}</ul>` : emptyState('還沒有固定收支')}
      <a class="btn block" href="#/recurring/new">＋ 新增固定收支</a>
      <p class="hint">像房租、薪水、訂閱費這種每月固定的收支，設定好之後，每次打開記帳本時會自動把到期的記進去。自動記入的紀錄會標示「固定」，一樣可以修改或刪除。</p>
    </section>`;
  el.querySelector('[data-act="back"]').addEventListener('click', () => goBack('#/settings'));
}

async function renderForm(el, id) {
  const today = todayStr();
  const rule = id ? await getRule(id) : null;
  if (id && !rule) {
    el.innerHTML = `${subHeader('固定收支')}${emptyState('找不到這個固定收支，可能已經被刪除')}`;
    el.querySelector('[data-act="back"]').addEventListener('click', () => goBack('#/recurring'));
    return;
  }
  const allCats = await listCategories({ includeHidden: true });
  const state = { type: rule?.type ?? 'expense', categoryId: rule?.categoryId ?? null };
  const day0 = rule?.day ?? Number(today.slice(8));
  let startTouched = Boolean(rule);

  el.innerHTML = `
    ${subHeader(rule ? '編輯固定收支' : '新增固定收支')}
    <form class="edit-form" novalidate>
      <div class="segmented" role="radiogroup" aria-label="收支類型">
        <button type="button" role="radio" data-type="expense">支出</button>
        <button type="button" role="radio" data-type="income">收入</button>
      </div>

      <label class="amount-field">
        <span aria-hidden="true">$</span>
        <input name="amount" inputmode="numeric" pattern="[0-9]*" autocomplete="off"
               placeholder="0" aria-label="金額" value="${rule?.amount ?? ''}">
      </label>
      <p class="field-error" data-err="amount"></p>

      <div class="cat-grid" data-cats role="radiogroup" aria-label="類別"></div>
      <p class="field-error" data-err="categoryId"></p>

      <label class="field">
        <span>名稱</span>
        <input name="note" maxlength="${MAX_NOTE}" placeholder="例如：房租、薪水、Netflix" value="${esc(rule?.note ?? '')}">
      </label>
      <p class="field-error" data-err="note"></p>

      <div class="field-row">
        <label class="field">
          <span>每月幾號</span>
          <select name="day">
            ${Array.from({ length: 31 }, (_, i) => i + 1)
              .map((d) => `<option value="${d}" ${d === day0 ? 'selected' : ''}>${d} 日${d >= 29 ? '（沒有這天就用月底）' : ''}</option>`)
              .join('')}
          </select>
        </label>
        <label class="field">
          <span>從哪個月開始</span>
          <input type="month" name="startMonth" value="${rule?.startMonth ?? suggestStartMonth(day0, today)}">
        </label>
      </div>
      <p class="field-error" data-err="day"></p>
      <p class="field-error" data-err="startMonth"></p>

      ${
        rule
          ? `<label class="switch-row"><input type="checkbox" name="active" ${rule.active ? 'checked' : ''}>
               <span>啟用（關掉就暫停自動記入）</span></label>`
          : ''
      }
      <p class="hint" data-preview></p>

      <button class="btn primary block" type="submit">儲存</button>
      ${rule ? '<button class="btn danger block" type="button" data-act="delete">刪除這個固定收支</button>' : ''}
    </form>`;

  const form = el.querySelector('form');
  const grid = el.querySelector('[data-cats]');
  const f = form.elements;

  function paint() {
    form.dataset.type = state.type;
    for (const b of el.querySelectorAll('[data-type]')) b.setAttribute('aria-checked', String(b.dataset.type === state.type));
    const cats = allCats.filter((c) => c.type === state.type && (!c.hidden || c.id === rule?.categoryId));
    if (!cats.some((c) => c.id === state.categoryId)) state.categoryId = cats[0]?.id ?? null;
    grid.innerHTML = categoryGrid(cats, state.categoryId);
  }

  function preview() {
    const day = Number(f.day.value);
    if (!startTouched) f.startMonth.value = suggestStartMonth(day, today);
    const start = f.startMonth.value;
    const active = f.active ? f.active.checked : true;
    const p = el.querySelector('[data-preview]');
    if (!isMonthStr(start) || !active) {
      p.textContent = active ? '' : '暫停中，不會自動記入。';
      return;
    }
    // 開始月份沒改的話，沿用已經產生到哪個月
    const lastGenerated = rule && rule.startMonth === start ? rule.lastGenerated : null;
    const draft = { day, startMonth: start, lastGenerated, active: true };
    const due = dueDates(draft, today);
    p.textContent = due.length
      ? `儲存後會馬上記入 ${due.length} 筆（${slash(due[0])}${due.length > 1 ? ` ～ ${slash(due.at(-1))}` : ''}）。`
      : `下次自動記入：${slash(nextDate(draft, today))}`;
  }

  const showErrors = (errors = {}) => {
    for (const p of el.querySelectorAll('[data-err]')) p.textContent = errors[p.dataset.err] ?? '';
  };

  el.addEventListener('click', async (e) => {
    const typeBtn = e.target.closest('[data-type]');
    const catBtn = e.target.closest('[data-cat]');
    if (typeBtn && typeBtn.dataset.type !== state.type) {
      state.type = typeBtn.dataset.type;
      paint();
    } else if (catBtn) {
      state.categoryId = catBtn.dataset.cat;
      paint();
      showErrors();
    } else if (e.target.closest('[data-act="back"]')) {
      goBack('#/recurring');
    } else if (e.target.closest('[data-act="delete"]')) {
      if (!confirm('確定要刪除這個固定收支嗎？\n已經記入的紀錄會保留。')) return;
      await deleteRule(rule.id);
      toast('已刪除');
      goBack('#/recurring');
    }
  });

  form.addEventListener('input', (e) => {
    if (e.target === f.amount) {
      const digits = f.amount.value.replace(/\D/g, '').replace(/^0+(?=\d)/, '');
      if (digits !== f.amount.value) f.amount.value = digits;
    }
    if (e.target === f.startMonth) startTouched = true;
    const p = el.querySelector(`[data-err="${e.target.name}"]`);
    if (p) p.textContent = '';
    preview();
  });
  form.addEventListener('change', preview);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = {
      type: state.type,
      amount: f.amount.value,
      categoryId: state.categoryId,
      note: f.note.value,
      day: f.day.value,
      startMonth: f.startMonth.value,
      active: f.active ? f.active.checked : true,
    };
    try {
      await saveRule(rule?.id ?? null, input);
    } catch (err) {
      if (err instanceof ValidationError) showErrors(err.errors);
      else toast(err.message);
      return;
    }
    const n = await generateDue();
    toast(n ? `已儲存，並自動記入 ${n} 筆` : '已儲存');
    goBack('#/recurring');
  });

  paint();
  preview();
}
