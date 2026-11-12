import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  dueDates, generateFor, MAX_CATCH_UP, nextDate, occurrenceDate, suggestStartMonth,
} from '../../docs/ledger/js/domain/recurring.js';
import { validateBackup, validateRecurring } from '../../docs/ledger/js/domain/validate.js';
import { DEFAULT_CATEGORIES as cats } from '../../docs/ledger/js/defaults.js';

const rule = (o = {}) => ({
  id: 'r1', type: 'expense', amount: 15000, categoryId: 'housing', note: '房租',
  day: 5, startMonth: '2026-09', lastGenerated: null, active: true, ...o,
});
let n = 0;
const uid = () => `id${++n}`;

test('occurrenceDate：沒有這天就用月底', () => {
  assert.equal(occurrenceDate('2026-02', 31), '2026-02-28');
  assert.equal(occurrenceDate('2028-02', 30), '2028-02-29');
  assert.equal(occurrenceDate('2026-11', 31), '2026-11-30');
  assert.equal(occurrenceDate('2026-11', 5), '2026-11-05');
});

test('dueDates：從開始月份補到今天，今天之後的不算', () => {
  assert.deepEqual(dueDates(rule(), '2026-11-12'), ['2026-09-05', '2026-10-05', '2026-11-05']);
  assert.deepEqual(dueDates(rule(), '2026-11-04'), ['2026-09-05', '2026-10-05']);
  assert.deepEqual(dueDates(rule({ day: 12 }), '2026-11-12').at(-1), '2026-11-12', '當天也算');
  assert.deepEqual(dueDates(rule({ lastGenerated: '2026-11' }), '2026-11-30'), []);
  assert.deepEqual(dueDates(rule({ active: false }), '2026-11-12'), []);
  assert.deepEqual(dueDates(rule({ startMonth: '2026-12' }), '2026-11-12'), []);
});

test('dueDates：開始月份太早，只補最近 24 個月', () => {
  const d = dueDates(rule({ startMonth: '2020-01' }), '2026-11-12');
  assert.equal(d.length, MAX_CATCH_UP);
  assert.equal(d[0], '2024-12-05');
  assert.equal(d.at(-1), '2026-11-05');
});

test('generateFor：產生紀錄並更新 lastGenerated，再跑一次不會重複', () => {
  const out = generateFor(rule(), '2026-11-12', { now: 1000, uid });
  assert.equal(out.transactions.length, 3);
  assert.deepEqual(out.transactions[2], {
    id: out.transactions[2].id, type: 'expense', amount: 15000, categoryId: 'housing',
    date: '2026-11-05', note: '房租', recurringId: 'r1', createdAt: 1002, updatedAt: 1002,
  });
  assert.equal(out.rule.lastGenerated, '2026-11');
  assert.equal(generateFor(out.rule, '2026-11-30', { uid }).transactions.length, 0);
  const dec = generateFor(out.rule, '2026-12-05', { uid });
  assert.deepEqual(dec.transactions.map((t) => t.date), ['2026-12-05']);
});

test('nextDate', () => {
  assert.equal(nextDate(rule({ lastGenerated: '2026-11' }), '2026-11-12'), '2026-12-05');
  assert.equal(nextDate(rule({ startMonth: '2026-11', day: 25 }), '2026-11-12'), '2026-11-25');
  assert.equal(nextDate(rule({ active: false }), '2026-11-12'), null);
});

test('suggestStartMonth：這個月的日期過了就從下個月開始', () => {
  assert.equal(suggestStartMonth(5, '2026-11-12'), '2026-12');
  assert.equal(suggestStartMonth(12, '2026-11-12'), '2026-11');
  assert.equal(suggestStartMonth(25, '2026-12-12'), '2026-12');
  assert.equal(suggestStartMonth(1, '2026-12-12'), '2027-01');
});

test('validateRecurring', () => {
  const input = { type: 'expense', amount: '15,000', categoryId: 'housing', note: '房租', day: '5', startMonth: '2026-12' };
  const v = validateRecurring(input, cats);
  assert.ok(v.ok);
  assert.deepEqual(v.value, { type: 'expense', amount: 15000, categoryId: 'housing', note: '房租', day: 5, startMonth: '2026-12', active: true });
  assert.ok(validateRecurring({ ...input, day: '32' }, cats).errors.day);
  assert.ok(validateRecurring({ ...input, startMonth: '2026-13' }, cats).errors.startMonth);
  assert.ok(validateRecurring({ ...input, categoryId: 'salary' }, cats).errors.categoryId);
  assert.ok(validateRecurring({ ...input, amount: '' }, cats).errors.amount);
});

test('備份 v2 含預算與固定收支；v1 備份也能匯入', () => {
  const t = { id: 't1', type: 'expense', amount: 15000, categoryId: 'housing', date: '2026-11-05', note: '房租', recurringId: 'r1', createdAt: 1 };
  const v2 = {
    app: 'ledger', version: 2, categories: cats, transactions: [t],
    budgets: [{ id: 'total', amount: 30000 }, { id: 'food', amount: 0 }],
    recurring: [rule({ lastGenerated: '2026-11' })],
  };
  const r = validateBackup(v2);
  assert.ok(r.ok, r.error);
  assert.deepEqual(r.value.budgets, [{ id: 'total', amount: 30000 }]);
  assert.equal(r.value.recurring[0].lastGenerated, '2026-11');
  assert.equal(r.value.transactions[0].recurringId, 'r1');

  const v1 = validateBackup({ app: 'ledger', version: 1, categories: cats, transactions: [t] });
  assert.ok(v1.ok);
  assert.deepEqual(v1.value.budgets, []);
  assert.deepEqual(v1.value.recurring, []);

  assert.ok(!validateBackup({ ...v2, budgets: [{ id: 'salary', amount: 100 }] }).ok, '收入類別不能設預算');
  assert.ok(!validateBackup({ ...v2, recurring: [rule({ day: 0 })] }).ok);
});
