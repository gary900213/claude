import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  addMonths, formatAmount, formatCompact, formatDay, formatMonth, formatSigned, isMonthStr, monthRange,
} from '../../docs/ledger/js/domain/format.js';

test('addMonths 跨年', () => {
  assert.equal(addMonths('2026-11', 2), '2027-01');
  assert.equal(addMonths('2026-01', -1), '2025-12');
  assert.equal(addMonths('2026-03', -5), '2025-10');
});

test('monthRange 處理大小月與閏年', () => {
  assert.deepEqual(monthRange('2026-02'), ['2026-02-01', '2026-02-28']);
  assert.deepEqual(monthRange('2028-02'), ['2028-02-01', '2028-02-29']);
  assert.deepEqual(monthRange('2026-11'), ['2026-11-01', '2026-11-30']);
});

test('isMonthStr', () => {
  assert.ok(isMonthStr('2026-11'));
  assert.ok(!isMonthStr('2026-13'));
  assert.ok(!isMonthStr('2026-1'));
  assert.ok(!isMonthStr(null));
});

test('金額格式', () => {
  assert.equal(formatAmount(1234567), '$1,234,567');
  assert.equal(formatAmount(0), '$0');
  assert.equal(formatSigned(-1500), '-$1,500');
  assert.equal(formatCompact(12000), '1.2萬');
  assert.equal(formatCompact(250000), '25萬');
  assert.equal(formatCompact(9999), '9,999');
});

test('日期與月份標籤', () => {
  assert.equal(formatDay('2026-11-09'), '11/9（週一）');
  assert.equal(formatMonth('2026-03'), '2026 年 3 月');
});
