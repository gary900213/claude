import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  isValidDate, parseAmount, validateBackup, validateCategory, validateTransaction,
} from '../../docs/ledger/js/domain/validate.js';
import { DEFAULT_CATEGORIES } from '../../docs/ledger/js/defaults.js';

const cats = DEFAULT_CATEGORIES;
const good = { type: 'expense', amount: '1,200', categoryId: 'food', date: '2026-11-09', note: '  午餐 ' };

test('預設類別：支出 5 個、收入 5 個，id 不重複', () => {
  assert.deepEqual(
    cats.filter((c) => c.type === 'expense').map((c) => c.name),
    ['餐飲', '交通', '居住', '人情交際', '其他支出'],
  );
  assert.equal(cats.filter((c) => c.type === 'income').length, 5);
  assert.equal(new Set(cats.map((c) => c.id)).size, cats.length);
});

test('合法紀錄會被整理（金額轉數字、備註去空白）', () => {
  const r = validateTransaction(good, cats);
  assert.ok(r.ok);
  assert.deepEqual(r.value, { type: 'expense', amount: 1200, categoryId: 'food', date: '2026-11-09', note: '午餐' });
});

test('金額必須是正整數', () => {
  for (const amount of ['', '0', '-5', '12.5', 'abc', 1.5, 0]) {
    assert.ok(validateTransaction({ ...good, amount }, cats).errors.amount, `amount=${amount}`);
  }
  assert.ok(validateTransaction({ ...good, amount: 1_000_000_000 }, cats).errors.amount);
  assert.equal(parseAmount('1,000'), 1000);
});

test('類別必須存在且類型相符', () => {
  assert.ok(validateTransaction({ ...good, categoryId: 'nope' }, cats).errors.categoryId);
  assert.ok(validateTransaction({ ...good, categoryId: 'salary' }, cats).errors.categoryId);
  assert.ok(validateTransaction({ ...good, type: 'income', categoryId: 'salary' }, cats).ok);
});

test('日期驗證', () => {
  assert.ok(isValidDate('2028-02-29'));
  assert.ok(!isValidDate('2026-02-29'));
  assert.ok(!isValidDate('2026/11/09'));
  assert.ok(validateTransaction({ ...good, date: '' }, cats).errors.date);
});

test('備註長度上限', () => {
  assert.ok(validateTransaction({ ...good, note: '字'.repeat(101) }, cats).errors.note);
  assert.ok(validateTransaction({ ...good, note: '字'.repeat(100) }, cats).ok);
});

test('類別驗證：名稱必填、不重複、圖示 1 個 emoji', () => {
  assert.ok(validateCategory({ type: 'expense', name: '寵物', icon: '🐶' }, cats).ok);
  assert.ok(validateCategory({ type: 'expense', name: '餐飲', icon: '🍜' }, cats).errors.name);
  // 收入和支出可以同名
  assert.ok(validateCategory({ type: 'income', name: '餐飲', icon: '🍜' }, cats).ok);
  // 改自己的名稱不算重複
  assert.ok(validateCategory({ type: 'expense', name: '餐飲', icon: '🍜' }, cats, 'food').ok);
  assert.ok(validateCategory({ type: 'expense', name: '', icon: '🐶' }, cats).errors.name);
  assert.ok(validateCategory({ type: 'expense', name: '寵物', icon: '' }, cats).errors.icon);
  assert.ok(validateCategory({ type: 'expense', name: '寵物', icon: '🐶🐱🐭' }, cats).errors.icon);
  assert.ok(validateCategory({ type: 'expense', name: '健身', icon: '🏋️‍♀️' }, cats).ok, '組合 emoji 算一個');
});

test('備份檔驗證', () => {
  const tx = { id: 't1', type: 'expense', amount: 100, categoryId: 'food', date: '2026-11-01', note: '', createdAt: 1 };
  const backup = { app: 'ledger', version: 1, categories: cats, transactions: [tx] };
  const r = validateBackup(backup);
  assert.ok(r.ok);
  assert.equal(r.value.transactions[0].updatedAt, 1);

  assert.ok(!validateBackup(null).ok);
  assert.ok(!validateBackup({ app: 'other', categories: [], transactions: [] }).ok);
  assert.ok(!validateBackup({ ...backup, transactions: [tx, tx] }).ok, '重複 id');
  assert.ok(!validateBackup({ ...backup, transactions: [{ ...tx, categoryId: 'x' }] }).ok, '類別不存在');
  assert.ok(!validateBackup({ ...backup, categories: [...cats, cats[0]] }).ok, '類別 id 重複');
});
