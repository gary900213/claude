import { test } from 'node:test';
import assert from 'node:assert/strict';
import { budgetLevel, budgetStatus, daysLeftInMonth } from '../../docs/ledger/js/domain/budget.js';
import { parseBudgetAmount } from '../../docs/ledger/js/domain/validate.js';
import { DEFAULT_CATEGORIES as cats } from '../../docs/ledger/js/defaults.js';

const tx = (categoryId, amount, type = 'expense') => ({ type, categoryId, amount, date: '2026-11-05' });
const txs = [tx('food', 3000), tx('food', 2500), tx('housing', 15000), tx('salary', 50000, 'income')];

test('daysLeftInMonth 含今天', () => {
  assert.equal(daysLeftInMonth('2026-11', '2026-11-12'), 19);
  assert.equal(daysLeftInMonth('2026-11', '2026-11-30'), 1);
  assert.equal(daysLeftInMonth('2026-10', '2026-11-12'), 0);
  assert.equal(daysLeftInMonth('2026-12', '2026-11-12'), 31);
});

test('總預算：剩餘金額與每日可花（收入不算）', () => {
  const s = budgetStatus(txs, [{ id: 'total', amount: 30000 }], cats, '2026-11', '2026-11-12');
  assert.equal(s.total.spent, 20500);
  assert.equal(s.total.remaining, 9500);
  assert.equal(s.total.daysLeft, 19);
  assert.equal(s.total.perDay, 500);
  assert.equal(s.total.over, false);
  assert.deepEqual(s.categories, []);
});

test('超支時每日可花為 0', () => {
  const s = budgetStatus(txs, [{ id: 'total', amount: 20000 }], cats, '2026-11', '2026-11-12');
  assert.equal(s.total.over, true);
  assert.equal(s.total.remaining, -500);
  assert.equal(s.total.perDay, 0);
});

test('類別預算依使用比例排序，沒花錢的類別也列出', () => {
  const budgets = [
    { id: 'food', amount: 5000 },
    { id: 'housing', amount: 20000 },
    { id: 'transport', amount: 2000 },
    { id: 'social', amount: 0 }, // 0 = 不設定
  ];
  const s = budgetStatus(txs, budgets, cats, '2026-11', '2026-11-12');
  assert.equal(s.total, null);
  assert.deepEqual(
    s.categories.map((r) => [r.category.id, r.spent, r.over]),
    [['food', 5500, true], ['housing', 15000, false], ['transport', 0, false]],
  );
});

test('budgetLevel', () => {
  assert.equal(budgetLevel(0.5), 'ok');
  assert.equal(budgetLevel(0.8), 'warn');
  assert.equal(budgetLevel(1), 'warn');
  assert.equal(budgetLevel(1.01), 'over');
});

test('parseBudgetAmount', () => {
  assert.deepEqual(parseBudgetAmount(''), { ok: true, amount: 0 });
  assert.deepEqual(parseBudgetAmount('20,000'), { ok: true, amount: 20000 });
  assert.equal(parseBudgetAmount('-1').ok, false);
  assert.equal(parseBudgetAmount('1.5').ok, false);
});
