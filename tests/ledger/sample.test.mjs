import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildSample } from '../../docs/ledger/js/sample.js';
import { validateBackup } from '../../docs/ledger/js/domain/validate.js';
import { generateFor } from '../../docs/ledger/js/domain/recurring.js';

const ids = () => { let n = 0; return () => `s${++n}`; };

test('範例資料通過備份檔驗證、不會超過今天', () => {
  const today = '2026-11-16';
  const data = buildSample(today, ids());
  const r = validateBackup({ app: 'ledger', version: 2, ...data });
  assert.ok(r.ok, r.error);
  assert.ok(data.transactions.length > 60);
  assert.ok(data.transactions.every((t) => t.date >= '2026-09-01' && t.date <= today));
  // 固定收支會補上 9、10、11 月的房租與薪水
  const rent = data.recurring.find((x) => x.note === '房租');
  assert.equal(generateFor(rent, today, { uid: ids() }).transactions.length, 3);
});

test('同一天產生的範例資料相同', () => {
  const a = buildSample('2026-11-16', ids());
  const b = buildSample('2026-11-16', ids());
  assert.deepEqual(a.transactions.map((t) => [t.date, t.amount, t.note]), b.transactions.map((t) => [t.date, t.amount, t.note]));
});
