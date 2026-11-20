import { test } from 'node:test';
import assert from 'node:assert/strict';
import { evalAmount, hasOperator, pressKey } from '../../docs/ledger/js/domain/amount.js';
import { parseAmount } from '../../docs/ledger/js/domain/validate.js';
import { changeRatio, daysElapsed, spentOn } from '../../docs/ledger/js/domain/stats.js';

const type = (keys) => keys.reduce(pressKey, '');

test('evalAmount：加減算式', () => {
  assert.equal(evalAmount('120+35-10'), 145);
  assert.equal(evalAmount('120+'), 120, '結尾的運算子忽略');
  assert.equal(evalAmount('1,200'), 1200);
  assert.ok(Number.isNaN(evalAmount('')));
  assert.ok(Number.isNaN(evalAmount('-5')));
  assert.ok(Number.isNaN(evalAmount('1++2')));
  assert.equal(evalAmount('100-300'), -200, '結果可以是負的，交給驗證擋下');
  assert.ok(hasOperator('1+2'));
  assert.ok(!hasOperator('12+'));
});

test('parseAmount 接受算式，結果 ≤ 0 時驗證不通過', () => {
  assert.equal(parseAmount('120+35'), 155);
  assert.equal(parseAmount('100-300'), -200);
});

test('pressKey：一般輸入', () => {
  assert.equal(type(['1', '2', '0', '+', '3', '5']), '120+35');
  assert.equal(type(['1', '2', 'back']), '1');
  assert.equal(type(['1', '2', 'clear']), '');
  assert.equal(type(['5', '00']), '500');
});

test('pressKey：運算子規則', () => {
  assert.equal(type(['+']), '', '不能用運算子開頭');
  assert.equal(type(['5', '+', '-']), '5-', '連按換掉前一個');
});

test('pressKey：0 的處理與長度上限', () => {
  assert.equal(type(['0', '5']), '5');
  assert.equal(type(['0', '0']), '0');
  assert.equal(type(['00']), '0');
  assert.equal(type(['1', '+', '0', '7']), '1+7');
  assert.equal(type(Array(12).fill('9')), '999999999', '單一數字最多 9 位');
});

test('daysElapsed、changeRatio、spentOn', () => {
  assert.equal(daysElapsed('2026-11', '2026-11-17'), 17);
  assert.equal(daysElapsed('2026-10', '2026-11-17'), 31);
  assert.equal(daysElapsed('2026-12', '2026-11-17'), 0);
  assert.equal(changeRatio(120, 100), 0.2);
  assert.equal(changeRatio(5, 0), null);
  const txs = [
    { type: 'expense', amount: 100, date: '2026-11-17' },
    { type: 'income', amount: 999, date: '2026-11-17' },
    { type: 'expense', amount: 50, date: '2026-11-16' },
  ];
  assert.equal(spentOn(txs, '2026-11-17'), 100);
});

test('expenseThroughDay：上個月同期', async () => {
  const { expenseThroughDay } = await import('../../docs/ledger/js/domain/stats.js');
  const txs = [
    { type: 'expense', amount: 100, date: '2026-10-01' },
    { type: 'expense', amount: 200, date: '2026-10-17' },
    { type: 'expense', amount: 400, date: '2026-10-18' },
    { type: 'income', amount: 999, date: '2026-10-05' },
    { type: 'expense', amount: 800, date: '2026-11-01' },
  ];
  assert.equal(expenseThroughDay(txs, '2026-10', 17), 300);
  assert.equal(expenseThroughDay(txs, '2026-10', 31), 700);
});
