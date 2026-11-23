import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { buildAppsScript, buildQuery, isAppsScriptUrl } from '../../docs/ledger/js/domain/gmail.js';
import { parseInboxItem } from '../../docs/ledger/js/domain/inbox.js';

test('buildQuery', () => {
  assert.equal(buildQuery(''), 'subject:(刷卡 OR 消費 OR 交易 OR 授權) newer_than:30d -in:spam -in:trash');
  assert.equal(buildQuery('a@bank.com, b@bank.com'), 'from:(a@bank.com OR b@bank.com) newer_than:30d -in:spam -in:trash');
  assert.equal(buildQuery('bad"x'), buildQuery(''), '有引號的忽略，避免改到搜尋語法');
});

test('isAppsScriptUrl', () => {
  assert.ok(isAppsScriptUrl('https://script.google.com/macros/s/AKfycbx-abc_123/exec'));
  assert.ok(isAppsScriptUrl('https://script.google.com/a/example.com/macros/s/AKfy/exec'));
  assert.ok(!isAppsScriptUrl('https://script.google.com/macros/s/AKfy/dev'));
  assert.ok(!isAppsScriptUrl('https://evil.example.com/macros/s/AKfy/exec'));
});

// 用假的 GmailApp / ContentService 執行產生的程式碼
function runScript(code, messages) {
  const ctx = {
    GmailApp: {
      search: (q) => {
        ctx.lastQuery = q;
        return [{ getMessages: () => messages }];
      },
    },
    ContentService: {
      MimeType: { JSON: 'json' },
      createTextOutput: (text) => ({ text, setMimeType() { return this; } }),
    },
  };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return ctx;
}
const msg = (id, date, subject, body) => ({
  getId: () => id, getDate: () => new Date(date), getSubject: () => subject, getPlainBody: () => body,
});

test('Apps Script：要 KEY、依時間過濾、回傳信件開頭', () => {
  const code = buildAppsScript({ key: 'k123', query: buildQuery('notice@bank.com') });
  const messages = [
    msg('m2', '2026-11-17T06:00:00Z', '信用卡消費通知', '親愛的客戶您好：\n您的信用卡於11/17在 PCHOME 消費 NT$2,390。\n\n\n提醒您請勿洩漏密碼。' + '。'.repeat(2000)),
    msg('m1', '2026-11-10T06:00:00Z', '信用卡消費通知', '舊的'),
  ];
  const ctx = runScript(code, messages);
  assert.equal(JSON.parse(ctx.doGet({ parameter: { key: 'wrong' } }).text).ok, false);
  const since = Date.parse('2026-11-15T00:00:00Z');
  const out = JSON.parse(ctx.doGet({ parameter: { key: 'k123', since: String(since) } }).text);
  assert.equal(ctx.lastQuery, 'from:(notice@bank.com) newer_than:30d -in:spam -in:trash');
  assert.equal(out.ok, true);
  assert.deepEqual(out.items.map((i) => i.id), ['m2']);
  assert.ok(out.items[0].text.length <= 800);
  assert.ok(out.items[0].text.startsWith('信用卡消費通知\n親愛的客戶您好'));

  // 記帳本解析：底部的「請勿洩漏密碼」不會讓整封被略過
  const item = parseInboxItem(out.items[0].text, 'm2', '2026-11-17');
  assert.deepEqual(item, { key: 'm2', amount: 2390, merchant: 'PCHOME', date: '2026-11-17' });
});
