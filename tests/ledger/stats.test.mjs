import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  countByCategory, filterTransactions, groupByCategory, groupByDate, monthlyTrend, sortTransactions, summarize,
} from '../../docs/ledger/js/domain/stats.js';
import { buildCSV } from '../../docs/ledger/js/domain/csv.js';
import { DEFAULT_CATEGORIES as cats } from '../../docs/ledger/js/defaults.js';

let n = 0;
const tx = (date, type, categoryId, amount, note = '') => ({ id: `t${++n}`, date, type, categoryId, amount, note, createdAt: n });

const txs = [
  tx('2026-11-01', 'income', 'salary', 50000),
  tx('2026-11-01', 'expense', 'food', 120, '早餐'),
  tx('2026-11-03', 'expense', 'housing', 15000, '房租'),
  tx('2026-11-03', 'expense', 'food', 280, '晚餐 火鍋'),
  tx('2026-10-15', 'expense', 'transport', 1200, '加油'),
  tx('2026-06-01', 'expense', 'food', 99),
];
const nov = txs.filter((t) => t.date.startsWith('2026-11'));

test('summarize', () => {
  assert.deepEqual(summarize(nov), { income: 50000, expense: 15400, balance: 34600 });
  assert.deepEqual(summarize([]), { income: 0, expense: 0, balance: 0 });
});

test('sortTransactions：日期新到舊，同天後建立的在前', () => {
  const ids = sortTransactions(nov).map((t) => t.id);
  assert.deepEqual(ids, ['t4', 't3', 't2', 't1']);
});

test('groupByDate 附每日小計', () => {
  const g = groupByDate(nov);
  assert.equal(g.length, 2);
  assert.deepEqual(
    g.map(({ date, income, expense, items }) => [date, income, expense, items.length]),
    [['2026-11-03', 0, 15280, 2], ['2026-11-01', 50000, 120, 2]],
  );
});

test('groupByCategory 依金額排序並算佔比', () => {
  const g = groupByCategory(nov, cats, 'expense');
  assert.deepEqual(g.map((x) => [x.categoryId, x.total, x.count]), [['housing', 15000, 1], ['food', 400, 2]]);
  assert.equal(g[0].category.name, '居住');
  assert.ok(Math.abs(g.reduce((s, x) => s + x.ratio, 0) - 1) < 1e-9);
  assert.deepEqual(groupByCategory([], cats), []);
});

test('monthlyTrend 補齊沒有紀錄的月份', () => {
  const t = monthlyTrend(txs, '2026-11', 6);
  assert.deepEqual(t.map((r) => r.month), ['2026-06', '2026-07', '2026-08', '2026-09', '2026-10', '2026-11']);
  assert.deepEqual(t.map((r) => r.expense), [99, 0, 0, 0, 1200, 15400]);
  assert.equal(t[5].balance, 34600);
});

test('filterTransactions', () => {
  assert.equal(filterTransactions(nov, { categoryId: 'food' }).length, 2);
  assert.equal(filterTransactions(nov, { keyword: '火鍋' }).length, 1);
  assert.equal(filterTransactions(nov, { categoryId: 'housing', keyword: '火鍋' }).length, 0);
  assert.equal(filterTransactions(nov, {}).length, 4);
});

test('countByCategory', () => {
  assert.equal(countByCategory(txs).get('food'), 3);
});

test('buildCSV：BOM、舊到新、跳脫逗號引號與公式', () => {
  const rows = [
    tx('2026-11-02', 'expense', 'food', 100, '便當, "大"'),
    tx('2026-11-01', 'income', 'salary', 500, '=1+1'),
  ];
  const csv = buildCSV(rows, cats);
  assert.ok(csv.startsWith('﻿日期,類型,類別,金額,備註\r\n'));
  const lines = csv.slice(1).trim().split('\r\n');
  assert.equal(lines[1], "2026-11-01,收入,薪資,500,'=1+1");
  assert.equal(lines[2], '2026-11-02,支出,餐飲,100,"便當, ""大"""');
});
