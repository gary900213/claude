import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  guessCategory, merchantKey, parseAmountText, parseDateText, parseInboxItem, parseInboxText, toTransaction,
} from '../../docs/ledger/js/domain/inbox.js';
import { DEFAULT_CATEGORIES as cats } from '../../docs/ledger/js/defaults.js';

test('parseAmountText：各種金額寫法', () => {
  assert.equal(parseAmountText('NT$1,234.00'), 1234);
  assert.equal(parseAmountText('$85'), 85);
  assert.equal(parseAmountText('85.50 TWD'), 86);
  assert.equal(parseAmountText('１２０元'), 120);
  assert.equal(parseAmountText(99), 99);
  assert.equal(parseAmountText(''), null);
  assert.equal(parseAmountText('NT$0.00'), null);
});

test('parseDateText', () => {
  assert.equal(parseDateText('2026-11-17 12:34'), '2026-11-17');
  assert.equal(parseDateText('2026/1/5 下午3:00'), '2026-01-05');
  assert.equal(parseDateText('2026年11月7日'), '2026-11-07');
  assert.equal(parseDateText('2026-02-30'), null);
  assert.equal(parseDateText('今天'), null);
});

test('parseInboxItem：JSON 與純文字', () => {
  const a = parseInboxItem('{"amount":"NT$85.00","merchant":"7-ELEVEN 信義門市","time":"2026-11-17 08:01"}', 'k1');
  assert.deepEqual(a, { key: 'k1', amount: 85, merchant: '7-ELEVEN 信義門市', date: '2026-11-17' });
  const b = parseInboxItem('星巴克 NT$150', 'k2');
  assert.equal(b.amount, 150);
  assert.equal(b.merchant, '星巴克');
  assert.equal(parseInboxItem('{"merchant":"全家"}', 'k3').amount, null, '沒帶金額');
  assert.equal(parseInboxItem('   ', 'k4'), null);
});

test('parseInboxText：同一行內容的鍵相同（重複匯入不會重複記）', () => {
  const text = '{"amount":"85","merchant":"全家","time":"2026-11-17 08:01"}\n\n{"amount":"60","merchant":"捷運","time":"2026-11-17 09:00"}\n';
  const a = parseInboxText(text);
  const b = parseInboxText(text);
  assert.equal(a.length, 2);
  assert.deepEqual(a.map((x) => x.key), b.map((x) => x.key));
  assert.notEqual(a[0].key, a[1].key);
});

test('merchantKey 去掉分店名稱', () => {
  assert.equal(merchantKey('7-ELEVEN 信義門市'), '7-eleven');
  assert.equal(merchantKey('全家便利商店-民生店'), '全家便利商店');
  assert.equal(merchantKey('STARBUCKS'), 'starbucks');
  assert.equal(merchantKey('台北捷運'), '台北捷運');
});

test('guessCategory：學過的優先，再看關鍵字', () => {
  assert.equal(guessCategory('7-ELEVEN 信義門市', {}, cats), 'food');
  assert.equal(guessCategory('Uber Eats', {}, cats), 'food');
  assert.equal(guessCategory('UBER TRIP', {}, cats), 'transport');
  assert.equal(guessCategory('台灣中油 民生站', {}, cats), 'transport');
  assert.equal(guessCategory('IKEA 新店', {}, cats), 'housing');
  for (const m of ['台灣高速鐵路股份有限公司', 'TAIWAN HIGH SPEED RAIL', 'THSR 台北站', '臺灣鐵路管理局', 'TAIPEI METRO', '國光客運', '遠通電收 eTag']) {
    assert.equal(guessCategory(m, {}, cats), 'transport', m);
  }
  assert.equal(guessCategory('某某精品', {}, cats), 'other_expense');
  assert.equal(guessCategory('7-ELEVEN 民生門市', { '7-eleven': 'social' }, cats), 'social', '學過的分店也適用');
  const hiddenFood = cats.map((c) => (c.id === 'food' ? { ...c, hidden: true } : c));
  assert.equal(guessCategory('全家', {}, hiddenFood), 'other_expense', '隱藏的類別不用');
});

test('toTransaction', () => {
  const t = toTransaction({ amount: 85, merchant: '全家', date: null }, 'food', { today: '2026-11-17', now: 5, uid: () => 'x' });
  assert.deepEqual(t, {
    id: 'x', type: 'expense', amount: 85, categoryId: 'food', date: '2026-11-17', note: '全家',
    source: 'applepay', createdAt: 5, updatedAt: 5,
  });
});
